"""Chunk persistence and semantic retrieval.

Cosine distance over a single vector index, always scoped to one project. There
are no cross-project reads: a project is the durable boundary that owns
everything derived within it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session as DbSession

from kae_memory.domain.chunks import (
    EMBEDDING_VERSION,
    MAX_DISTANCE,
    EmbeddingState,
    KnowledgeChunk,
    strip_metadata_prefix,
)
from kae_memory.domain.identifiers import ChunkId, KnowledgeItemId, ProjectId
from kae_memory.domain.lexical import MIN_COVERAGE, LexicalMatch, match
from kae_memory.domain.lifecycle import RETRIEVABLE, LifecycleState
from kae_memory.domain.models import KnowledgeKind

from .providers import DatabaseProvider as _Provider
from .providers import ProviderAdapter, adapter_for
from .providers import ProviderConfigurationError as _ConfigError
from .providers import resolve as _resolve
from .tables import KnowledgeChunkRow
from .timestamps import as_aware


def _default_adapter() -> ProviderAdapter:
    """Return the configured adapter, or CockroachDB when nothing is set.

    A repository constructed in a unit test has no configured provider and must
    still import; a deployment resolves explicitly and refuses a missing one at
    startup.
    """

    try:
        return _resolve().adapter
    except _ConfigError:
        return adapter_for(_Provider.COCKROACHDB)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One semantic hit, with everything needed to explain why it was returned."""

    chunk: KnowledgeChunk
    distance: float
    lifecycle: LifecycleState = LifecycleState.PROPOSED
    """The owning item's state, read live rather than from the embedded text.

    The chunk body carries a metadata prefix naming the status at the time it
    was written, and nothing rewrites it when a person confirms the statement.
    Labelling a result from that text would report a confirmed statement as
    proposed.
    """

    @property
    def similarity(self) -> float:
        """Cosine similarity, for reporting. Lower distance means more similar."""

        return 1.0 - self.distance


@dataclass(frozen=True, slots=True)
class LexicalChunk:
    """One lexical hit. Carries no distance: no vector was consulted."""

    chunk: KnowledgeChunk
    match: LexicalMatch
    lifecycle: LifecycleState = LifecycleState.PROPOSED
    """The owning item's state, read live. See :class:`RetrievedChunk`."""


def _as_vector(value: object) -> tuple[float, ...] | None:
    """Read a stored embedding as floats, however the driver hands it back.

    Through the ORM a `Vector` column arrives as a sequence; through raw SQL the
    same column can arrive as its text form, `"[0.1,0.2,...]"`. Iterating that
    string yields characters, and `float("[")` raises — which is how this was
    found, by a test that was the first thing ever to read a stored vector back.
    """

    if value is None:
        return None
    if isinstance(value, str):
        body = value.strip().strip("[]")
        if not body:
            return None
        return tuple(float(part) for part in body.split(","))
    return tuple(float(part) for part in cast(Sequence[float], value))


class ChunkRepository:
    """Persistence boundary for knowledge chunks and their embeddings."""

    def __init__(self, session: DbSession, adapter: ProviderAdapter | None = None) -> None:
        self._session = session
        # The distance expression is the one piece of retrieval SQL that a
        # provider could spell differently. Asking the adapter keeps that
        # possibility open without putting a provider check in this file.
        self._adapter = adapter or _default_adapter()

    def add(self, chunk: KnowledgeChunk) -> None:
        """Persist a chunk with no embedding yet."""

        self._session.add(
            KnowledgeChunkRow(
                chunk_id=str(chunk.id),
                project_id=str(chunk.project_id),
                knowledge_id=str(chunk.knowledge_id),
                knowledge_kind=chunk.knowledge_kind.value,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.text,
                embedding=None,
                embedding_state=chunk.state.value,
                embedding_model=chunk.embedding_model,
                embedding_dimensions=chunk.embedding_dimensions,
                embedding_version=chunk.embedding_version,
                content_hash=chunk.hash_value,
                embedded_at=chunk.embedded_at,
                created_at=chunk.created_at,
            )
        )

    def get(self, chunk_id: ChunkId) -> KnowledgeChunk | None:
        """Return a chunk by identifier."""

        row = self._session.get(KnowledgeChunkRow, str(chunk_id))
        return None if row is None else _to_domain(row)

    def list_for_knowledge(self, knowledge_id: KnowledgeItemId) -> tuple[KnowledgeChunk, ...]:
        """Return a knowledge item's chunks in order."""

        rows = self._session.scalars(
            select(KnowledgeChunkRow)
            .where(KnowledgeChunkRow.knowledge_id == str(knowledge_id))
            .order_by(KnowledgeChunkRow.chunk_index)
        ).all()
        return tuple(_to_domain(row) for row in rows)

    def supersede(self, chunk: KnowledgeChunk) -> None:
        """Replace a chunk's text, keeping its vector until a re-embed lands.

        The old vector describes text that no longer exists, but the row's text
        is current, so a semantic hit returns the right words with a stale
        ranking. Deleting instead would make the item vanish from vector search
        entirely — retrieval should degrade, not disappear (ADR-0008).
        """

        self._session.execute(
            update(KnowledgeChunkRow)
            .where(KnowledgeChunkRow.chunk_id == str(chunk.id))
            .values(
                chunk_text=chunk.text,
                content_hash=chunk.hash_value,
                embedding_state=EmbeddingState.STALE.value,
            )
        )

    def delete_for_knowledge(self, knowledge_id: KnowledgeItemId) -> int:
        """Remove every chunk of one knowledge item. Returns how many went.

        Used when a correction leaves fewer chunks than before; a surplus chunk
        left behind would keep matching text the item no longer says.
        """

        existing = len(self.list_for_knowledge(knowledge_id))
        self._session.execute(
            delete(KnowledgeChunkRow).where(KnowledgeChunkRow.knowledge_id == str(knowledge_id))
        )
        return existing

    def delete(self, chunk_id: ChunkId) -> None:
        """Remove one chunk."""

        self._session.execute(
            delete(KnowledgeChunkRow).where(KnowledgeChunkRow.chunk_id == str(chunk_id))
        )

    def counts_for_project(self, project_id: ProjectId) -> tuple[int, int]:
        """Return ``(chunks, embedded)`` for one project.

        The signal that separates "nothing matched" from "nothing is indexed",
        which are the same empty list to a caller who cannot tell them apart.
        """

        total = self._session.scalar(
            select(func.count())
            .select_from(KnowledgeChunkRow)
            .where(KnowledgeChunkRow.project_id == str(project_id))
        )
        embedded = self._session.scalar(
            select(func.count())
            .select_from(KnowledgeChunkRow)
            .where(
                KnowledgeChunkRow.project_id == str(project_id),
                KnowledgeChunkRow.embedding.is_not(None),
            )
        )
        return int(total or 0), int(embedded or 0)

    def list_needing_embedding(
        self,
        project_id: ProjectId | None = None,
        limit: int = 100,
        embedding_version: int = EMBEDDING_VERSION,
    ) -> tuple[KnowledgeChunk, ...]:
        """Return chunks needing an embedding in the current space, oldest first.

        Eligible on **either** count, not state alone:

        * the state is pending, stale, or failed; or
        * the vector belongs to a different embedding version.

        The second is what makes a migration possible. A chunk embedded at
        version 1 is marked ``embedded`` and is entirely correct about itself —
        it simply holds a vector from a space the current search no longer
        queries. Selecting on state alone would leave it behind forever.

        Claimed chunks are excluded: a second runner picking one up is the race
        this design prevents. Recovery from a crashed runner is explicit, via
        :meth:`release_claims`.

        Ordering is by creation then identifier, so two runners walking the same
        corpus see the same sequence and a resumed run continues where it left
        off rather than re-deriving a different order.
        """

        needs_work = KnowledgeChunkRow.embedding_state.in_(
            [
                EmbeddingState.PENDING.value,
                EmbeddingState.STALE.value,
                EmbeddingState.FAILED.value,
            ]
        )
        wrong_version = or_(
            KnowledgeChunkRow.embedding_version != embedding_version,
            KnowledgeChunkRow.embedding_version.is_(None),
        )
        conditions = [
            or_(needs_work, wrong_version),
            KnowledgeChunkRow.embedding_state != EmbeddingState.CLAIMED.value,
        ]
        if project_id is not None:
            conditions.append(KnowledgeChunkRow.project_id == str(project_id))

        rows = self._session.scalars(
            select(KnowledgeChunkRow)
            .where(*conditions)
            .order_by(KnowledgeChunkRow.created_at, KnowledgeChunkRow.chunk_id)
            .limit(limit)
        ).all()
        return tuple(_to_domain(row) for row in rows)

    def claim(self, chunk_id: ChunkId, expected_state: EmbeddingState) -> bool:
        """Take exclusive ownership of a chunk. Returns whether this caller won.

        A compare-and-set rather than a row lock, because embedding is an
        external call and the application never holds a transaction open across
        one (ADR-0004). Two runners reaching the same chunk both attempt the
        transition; the ``WHERE`` clause means exactly one row is updated.
        """

        result = self._session.execute(
            update(KnowledgeChunkRow)
            .where(
                KnowledgeChunkRow.chunk_id == str(chunk_id),
                KnowledgeChunkRow.embedding_state == expected_state.value,
            )
            .values(embedding_state=EmbeddingState.CLAIMED.value)
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    def release_claims(self, project_id: ProjectId | None = None) -> int:
        """Return claimed chunks to pending. Returns how many were released.

        For recovering from a runner that died mid-flight. Deliberately manual:
        an automatic timeout would race with a slow-but-alive runner and embed
        the same chunk twice.
        """

        conditions = [KnowledgeChunkRow.embedding_state == EmbeddingState.CLAIMED.value]
        if project_id is not None:
            conditions.append(KnowledgeChunkRow.project_id == str(project_id))
        stranded = self._session.scalars(select(KnowledgeChunkRow).where(*conditions)).all()
        self._session.execute(
            update(KnowledgeChunkRow)
            .where(*conditions)
            .values(embedding_state=EmbeddingState.PENDING.value)
        )
        return len(stranded)

    def store_embedding(
        self,
        chunk_id: ChunkId,
        vector: Sequence[float],
        model: str,
        dimensions: int,
        moment: datetime,
        embedding_version: int = EMBEDDING_VERSION,
    ) -> None:
        """Attach a vector to a chunk and mark it embedded, in one statement.

        Vector, version, model, dimensions, and state move together. A vector
        written without its version would sit in the current search space
        claiming to be something it is not, which is the failure the version
        exists to prevent.

        Called only after the provider has returned. The previous vector is
        still in place until this runs, so a failed request costs recall for one
        chunk and destroys nothing.
        """

        self._session.execute(
            update(KnowledgeChunkRow)
            .where(KnowledgeChunkRow.chunk_id == str(chunk_id))
            .values(
                embedding=list(vector),
                embedding_state=EmbeddingState.EMBEDDED.value,
                embedding_model=model,
                embedding_dimensions=dimensions,
                embedding_version=embedding_version,
                embedded_at=moment,
            )
        )

    def mark_failed(self, chunk_id: ChunkId) -> None:
        """Record that embedding failed, leaving the chunk retryable."""

        self._session.execute(
            update(KnowledgeChunkRow)
            .where(KnowledgeChunkRow.chunk_id == str(chunk_id))
            .values(embedding_state=EmbeddingState.FAILED.value)
        )

    def search(
        self,
        project_id: ProjectId,
        query_vector: Sequence[float],
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
        embedding_version: int = EMBEDDING_VERSION,
        max_distance: float | None = MAX_DISTANCE,
        lifecycle: frozenset[LifecycleState] = RETRIEVABLE,
    ) -> tuple[RetrievedChunk, ...]:
        """Return the nearest chunks by cosine distance, within ``max_distance``.

        Scoped to one project, and to one embedding version: vectors produced by
        different models occupy different spaces, so mixing them in a single
        ranking would return confident nonsense.

        Scoped to ``lifecycle`` in SQL rather than afterwards. Rejected knowledge
        was ranked and returned for as long as the only mention of lifecycle was
        inside the embedded text, where no query could reach it — a statement a
        person had ruled out came back as a result like any other. Filtering
        after the fact would not fix it either: a rejected chunk that displaces a
        good one inside ``LIMIT`` is already lost by the time the caller sees it.

        The cutoff is what makes this a search rather than a listing. Nearest-
        neighbour with only a ``LIMIT`` returns ``limit`` rows whatever the
        query, so on a small corpus every query returns the entire corpus in some
        order. Passing ``max_distance=None`` restores that behaviour, which is
        useful for testing the plumbing and misleading for anything else.
        """

        literal = "[" + ",".join(repr(float(value)) for value in query_vector) + "]"
        distance = self._adapter.cosine_distance("c.embedding", ":vector")
        states = sorted(state.value for state in lifecycle)
        placeholders = ", ".join(f":life_{index}" for index in range(len(states)))
        sql = (
            f"SELECT c.chunk_id, {distance} AS distance, k.lifecycle "
            "FROM knowledge_chunks c "
            "JOIN knowledge_items k ON k.id = c.knowledge_id "
            "WHERE c.project_id = :project_id "
            "  AND c.embedding IS NOT NULL "
            "  AND c.embedding_version = :embedding_version "
            f"  AND k.lifecycle IN ({placeholders}) "
        )
        params: dict[str, object] = {
            "vector": literal,
            "project_id": str(project_id),
            "embedding_version": embedding_version,
            "limit": limit,
        }
        params.update({f"life_{index}": state for index, state in enumerate(states)})
        if kinds:
            names = [kind.value for kind in kinds]
            kind_placeholders = ", ".join(f":kind_{index}" for index in range(len(names)))
            sql += f"  AND c.knowledge_kind IN ({kind_placeholders}) "
            params.update({f"kind_{index}": name for index, name in enumerate(names)})
        if max_distance is not None:
            sql += f"  AND {distance} <= :max_distance "
            params["max_distance"] = float(max_distance)
        sql += "ORDER BY distance LIMIT :limit"

        hits = self._session.execute(text(sql), params).all()
        results: list[RetrievedChunk] = []
        for chunk_id, distance, lifecycle_value in hits:
            row = self._session.get(KnowledgeChunkRow, chunk_id)
            if row is not None:
                results.append(
                    RetrievedChunk(
                        chunk=_to_domain(row),
                        distance=float(distance),
                        lifecycle=LifecycleState(lifecycle_value),
                    )
                )
        return tuple(results)

    def embeddings_for(
        self,
        project_id: ProjectId,
        knowledge_ids: Sequence[KnowledgeItemId],
        *,
        embedding_version: int = EMBEDDING_VERSION,
    ) -> dict[KnowledgeItemId, tuple[float, ...]]:
        """The stored vector for each item that has one, by first chunk.

        Clustering needs every pair, not a ranked few, so it reads the vectors
        once and does the arithmetic in the domain where it can be tested
        without a database. `semantic_neighbors` stays the right call for *what
        is near this*; this is the right call for *how do all of these relate*.

        An item absent from the result has no vector. The caller must treat that
        as incomparable rather than as distance zero — the two are opposite, and
        one of them merges everything.
        """

        if not knowledge_ids:
            return {}
        wanted = [str(item_id) for item_id in knowledge_ids]
        placeholders = ", ".join(f":item_{index}" for index in range(len(wanted)))
        sql = (
            "SELECT DISTINCT ON (knowledge_id) knowledge_id, embedding "
            "FROM knowledge_chunks "
            "WHERE project_id = :project_id "
            f"  AND knowledge_id IN ({placeholders}) "
            "  AND embedding IS NOT NULL "
            "  AND embedding_version = :embedding_version "
            "ORDER BY knowledge_id, chunk_index"
        )
        params: dict[str, object] = {
            "project_id": str(project_id),
            "embedding_version": embedding_version,
        }
        params.update({f"item_{index}": value for index, value in enumerate(wanted)})
        rows = self._session.execute(text(sql), params).all()
        found: dict[KnowledgeItemId, tuple[float, ...]] = {}
        for knowledge_id, embedding in rows:
            vector = _as_vector(embedding)
            if vector is None:
                continue
            found[KnowledgeItemId(str(knowledge_id))] = vector
        return found

    def statement_space(
        self,
        project_id: ProjectId,
        knowledge_ids: Sequence[KnowledgeItemId],
        *,
        embedding_version: int = EMBEDDING_VERSION,
    ) -> bool:
        """Whether these vectors measure the sentence or the envelope (`D-102`).

        Every stored chunk begins with `Type:`, `Project:`, `Status:` and a blank
        line (`D-75`). Those three lines are identical for every item of one kind
        in one project, so embedding them compresses the space: mean pair
        distance across the golden corpus is **0.144** as stored against
        **0.510** as statements.

        A radius measured in one space and applied to the other is not a tuning
        error, it is a different question. `D-100`'s 0.45 puts all 47 goals in a
        single cluster when read from enveloped vectors — the whole goal model as
        one object.

        So a caller that clusters must ask first. `False` means *these vectors
        cannot answer how far apart two sentences are*, which is a fact about the
        deployment's index rather than about the project.
        """

        if not knowledge_ids:
            return False
        wanted = [str(item_id) for item_id in knowledge_ids]
        placeholders = ", ".join(f":item_{index}" for index in range(len(wanted)))
        sql = (
            "SELECT chunk_text FROM knowledge_chunks "
            "WHERE project_id = :project_id "
            f"  AND knowledge_id IN ({placeholders}) "
            "  AND embedding IS NOT NULL "
            "  AND embedding_version = :embedding_version "
            "LIMIT 1"
        )
        params: dict[str, object] = {
            "project_id": str(project_id),
            "embedding_version": embedding_version,
        }
        params.update({f"item_{index}": value for index, value in enumerate(wanted)})
        row = self._session.execute(text(sql), params).first()
        if row is None:
            return False
        return strip_metadata_prefix(str(row[0])) == str(row[0])

    def semantic_neighbors(
        self,
        project_id: ProjectId,
        knowledge_id: KnowledgeItemId,
        *,
        kind: str | None = None,
        limit: int = 12,
        embedding_version: int = EMBEDDING_VERSION,
        max_distance: float | None = MAX_DISTANCE,
        lifecycle: frozenset[LifecycleState] = RETRIEVABLE,
    ) -> tuple[tuple[KnowledgeItemId, float], ...]:
        """Nearest *items* to one item, by the vectors already stored.

        ## Why this is not ``search``

        ``search`` answers *what is near this question*, and takes a vector the
        caller produced. Reconciliation asks *what is near this statement*, and
        the statement is already embedded — every chunk of the corpus carries
        its vector in this table. Re-embedding the text to ask would call a
        model to recompute a number the database is holding, and would fail on a
        deployment whose model is not running while the corpus is fully indexed
        (`ADR-0006`).

        ## Why item-level, not chunk-level

        A long statement is several chunks, so a chunk ranking returns the same
        neighbour repeatedly and crowds out the others inside ``LIMIT``. The
        distance for an item is its **closest** chunk, aggregated in SQL before
        the limit applies.

        Returns an empty tuple when the focus has no embedding — a real answer
        meaning *this item cannot be compared this way*, which the caller must
        distinguish from *nothing is near it*.
        """

        distance = self._adapter.cosine_distance("c.embedding", "f.embedding")
        states = sorted(state.value for state in lifecycle)
        placeholders = ", ".join(f":life_{index}" for index in range(len(states)))
        sql = (
            "WITH focus AS ("
            "  SELECT embedding FROM knowledge_chunks"
            "  WHERE knowledge_id = :knowledge_id"
            "    AND project_id = :project_id"
            "    AND embedding IS NOT NULL"
            "    AND embedding_version = :embedding_version"
            "  ORDER BY chunk_index LIMIT 1"
            ") "
            f"SELECT c.knowledge_id, MIN({distance}) AS distance "
            "FROM knowledge_chunks c "
            "JOIN knowledge_items k ON k.id = c.knowledge_id "
            "CROSS JOIN focus f "
            "WHERE c.project_id = :project_id "
            "  AND c.knowledge_id <> :knowledge_id "
            "  AND c.embedding IS NOT NULL "
            "  AND c.embedding_version = :embedding_version "
            f"  AND k.lifecycle IN ({placeholders}) "
        )
        params: dict[str, object] = {
            "project_id": str(project_id),
            "knowledge_id": str(knowledge_id),
            "embedding_version": embedding_version,
            "limit": limit,
        }
        params.update({f"life_{index}": state for index, state in enumerate(states)})
        if kind is not None:
            sql += "  AND c.knowledge_kind = :kind "
            params["kind"] = kind
        sql += "GROUP BY c.knowledge_id "
        if max_distance is not None:
            # After the aggregate, so an item qualifies on its closest chunk.
            sql += f"HAVING MIN({distance}) <= :max_distance "
            params["max_distance"] = float(max_distance)
        sql += "ORDER BY distance LIMIT :limit"

        rows = self._session.execute(text(sql), params).all()
        return tuple((KnowledgeItemId(str(item_id)), float(dist)) for item_id, dist in rows)

    def search_lexical(
        self,
        project_id: ProjectId,
        query_terms: Sequence[str],
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
        min_coverage: float = MIN_COVERAGE,
        lifecycle: frozenset[LifecycleState] = RETRIEVABLE,
    ) -> tuple[LexicalChunk, ...]:
        """Return chunks whose text contains the query's word families.

        Two deliberate differences from :meth:`search`. It does not require an
        embedding, because a chunk's words are readable the moment it is stored —
        knowledge is findable while a re-embed is still pending. And it never
        returns a weakly-matched row: coverage below ``min_coverage`` is an
        exclusion, not a low rank, so one incidental shared word cannot carry a
        result into the response.

        The stems narrow candidates in SQL; scoring happens in Python against the
        chunk body so that the metadata prefix cannot match. Ordering is by
        coverage, then by knowledge and chunk index so equal scores are stable.
        """

        if not query_terms:
            return ()

        conditions = " OR ".join(
            f"c.chunk_text ILIKE :term_{index}" for index in range(len(query_terms))
        )
        states = sorted(state.value for state in lifecycle)
        life_placeholders = ", ".join(f":life_{index}" for index in range(len(states)))
        sql = (
            "SELECT c.chunk_id, k.lifecycle FROM knowledge_chunks c "
            "JOIN knowledge_items k ON k.id = c.knowledge_id "
            "WHERE c.project_id = :project_id "
            f"  AND ({conditions}) "
            f"  AND k.lifecycle IN ({life_placeholders}) "
        )
        params: dict[str, object] = {"project_id": str(project_id)}
        params.update({f"term_{index}": f"%{term}%" for index, term in enumerate(query_terms)})
        params.update({f"life_{index}": state for index, state in enumerate(states)})
        if kinds:
            names = [kind.value for kind in kinds]
            kind_placeholders = ", ".join(f":kind_{index}" for index in range(len(names)))
            sql += f"  AND c.knowledge_kind IN ({kind_placeholders}) "
            params.update({f"kind_{index}": name for index, name in enumerate(names)})

        stems = tuple(query_terms)
        scored: list[LexicalChunk] = []
        for chunk_id, lifecycle_value in self._session.execute(text(sql), params).all():
            row = self._session.get(KnowledgeChunkRow, chunk_id)
            if row is None:
                continue
            chunk = _to_domain(row)
            result = match(stems, strip_metadata_prefix(chunk.text))
            if result.matched and result.score >= min_coverage:
                scored.append(
                    LexicalChunk(
                        chunk=chunk,
                        match=result,
                        lifecycle=LifecycleState(lifecycle_value),
                    )
                )

        scored.sort(
            key=lambda hit: (
                -hit.match.score,
                str(hit.chunk.knowledge_id),
                hit.chunk.chunk_index,
            )
        )
        return tuple(scored[:limit])


def _to_domain(row: KnowledgeChunkRow) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=ChunkId(row.chunk_id),
        project_id=ProjectId(row.project_id),
        knowledge_id=KnowledgeItemId(row.knowledge_id),
        knowledge_kind=KnowledgeKind(row.knowledge_kind),
        chunk_index=row.chunk_index,
        text=row.chunk_text,
        created_at=as_aware(row.created_at),
        embedding_version=row.embedding_version,
        state=EmbeddingState(row.embedding_state),
        embedding_model=row.embedding_model,
        embedding_dimensions=row.embedding_dimensions,
        embedded_at=as_aware(row.embedded_at) if row.embedded_at else None,
        hash_value=row.content_hash,
    )
