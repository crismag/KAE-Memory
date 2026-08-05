"""Chunking, embedding, and semantic retrieval.

Embedding never blocks knowledge persistence. A knowledge item and its chunks may
exist with a pending or failed embedding and be retried without recreating the
authoritative item — memory is the product, retrieval is an index over it
(ADR-0008).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.agents.embedding import EmbeddingError, EmbeddingPort
from kae_memory.agents.provider import ranks_by_meaning
from kae_memory.domain.chunks import (
    EMBEDDING_VERSION,
    MAX_DISTANCE,
    KnowledgeChunk,
    metadata_prefix,
    split_text,
)
from kae_memory.domain.identifiers import ChunkId, KnowledgeItemId, ProjectId
from kae_memory.domain.lexical import terms
from kae_memory.domain.lifecycle import RETRIEVABLE, LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind
from kae_memory.persistence.chunk_repository import (
    ChunkRepository,
    LexicalChunk,
    RetrievedChunk,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction


@dataclass(frozen=True, slots=True)
class IndexingStatus:
    """How much of a project's knowledge is reachable by search."""

    knowledge_items: int
    chunks: int
    embedded_chunks: int

    @property
    def lexically_searchable(self) -> bool:
        """Whether any knowledge can be found by term matching."""

        return self.chunks > 0

    @property
    def unindexed(self) -> bool:
        """Whether the project holds knowledge that no search can reach."""

        return self.knowledge_items > 0 and self.chunks == 0

    @property
    def embedding_pending(self) -> int:
        """Chunks awaiting a vector. Lexical works; semantic does not yet."""

        return self.chunks - self.embedded_chunks


class SearchMode(StrEnum):
    """Which retrieval path produced a hit.

    Reported rather than inferred. "Ranked by meaning" and "contains your words"
    are different claims, and a caller that cannot tell them apart will read
    whichever one flatters the result.
    """

    SEMANTIC = "semantic"
    LEXICAL = "lexical"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A retrieval result, with the provenance needed to justify it.

    ``why`` is not decoration: FR-013 requires an explanation of why a result was
    included, and a distance alone does not tell a user anything they can act on.

    ``distance`` is ``None`` for lexical hits. A lexical match consulted no
    vector, so reporting a distance would be inventing one.
    """

    chunk_id: ChunkId
    knowledge_id: KnowledgeItemId
    kind: KnowledgeKind
    text: str
    distance: float | None
    why: str
    mode: SearchMode = SearchMode.SEMANTIC
    matched_terms: tuple[str, ...] = ()
    coverage: float | None = None
    lifecycle: LifecycleState = LifecycleState.PROPOSED
    """Whether a person has ruled on this statement.

    Present on every hit because searchable and authoritative are different
    questions. Proposed knowledge is returned so it can be reviewed; a caller
    that treats it as established fact without reading this is the failure the
    field exists to prevent.
    """

    @property
    def authoritative(self) -> bool:
        """Whether a person confirmed this statement."""

        return self.lifecycle is LifecycleState.VALIDATED


class RetrievalService:
    """Application entry point for semantic memory."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        embedder: EmbeddingPort,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        embedder_name: str = "deterministic",
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        # Named rather than inferred from the object, so a provider added later
        # is non-semantic until it is listed as one. Guessing from a class name
        # would let a new adapter advertise ranking it does not do.
        self._embedder_name = embedder_name
        self._policy = policy or RetryPolicy()
        self._clock = clock

    def _run[ResultT](self, operation: Callable[[DbSession], ResultT]) -> ResultT:
        return run_transaction(self._session_factory, operation, self._policy)

    def chunk_knowledge(
        self, item: KnowledgeItem, project_name: str, title: str | None = None
    ) -> tuple[KnowledgeChunk, ...]:
        """Split a knowledge item into chunks and persist them unembedded.

        The metadata prefix is part of the embedded text: it tells the model that
        "monthly" is a rule inside a reporting project rather than a stray adverb,
        without needing a separate index per knowledge type.

        Idempotent. Knowledge is now chunked by the write that creates it, so
        this is reached either by a backfill over items written before that, or
        by a caller re-running it; both must be safe. An item that already has
        chunks gets them back unchanged rather than a duplicate-key error.
        """

        already = self._run(lambda session: ChunkRepository(session).list_for_knowledge(item.id))
        if already:
            return already

        moment = self._clock()
        kind = KnowledgeKind(item.kind)
        prefix = metadata_prefix(project_name, kind, title, item.lifecycle.value)
        bodies = split_text(item.current_version.content)

        chunks = tuple(
            KnowledgeChunk(
                id=ChunkId(str(uuid4())),
                project_id=item.project_id,
                knowledge_id=item.id,
                knowledge_kind=kind,
                chunk_index=index,
                text=f"{prefix}\n\n{body}",
                created_at=moment,
            )
            for index, body in enumerate(bodies)
        )

        def operation(session: DbSession) -> None:
            repository = ChunkRepository(session)
            for chunk in chunks:
                repository.add(chunk)

        self._run(operation)
        return chunks

    def embed_pending(self, project_id: ProjectId, limit: int = 100) -> int:
        """Embed the chunks awaiting a vector. Returns how many succeeded.

        A provider failure marks the affected chunks failed and leaves the rest
        embedded. Nothing here can damage the knowledge those chunks index.
        """

        pending = self._run(
            lambda session: ChunkRepository(session).list_needing_embedding(project_id, limit)
        )
        if not pending:
            return 0

        try:
            result = self._embedder.embed([chunk.text for chunk in pending])
        except EmbeddingError:

            def mark_all_failed(session: DbSession) -> None:
                repository = ChunkRepository(session)
                for chunk in pending:
                    repository.mark_failed(chunk.id)

            self._run(mark_all_failed)
            raise

        moment = self._clock()

        def store(session: DbSession) -> None:
            repository = ChunkRepository(session)
            for chunk, vector in zip(pending, result.vectors, strict=True):
                repository.store_embedding(
                    chunk.id, vector, result.model, result.dimensions, moment
                )

        self._run(store)
        return len(pending)

    def indexing_status(self, project_id: ProjectId) -> "IndexingStatus":
        """Report whether a project's knowledge can be found at all.

        The signal that separates "nothing matched your query" from "nothing is
        searchable yet". They are the same empty list to a caller who cannot
        tell them apart, and treating the second as the first is how a project
        comes to look emptier than it is.
        """

        def operation(session: DbSession) -> IndexingStatus:
            items = len(SqlAlchemyKnowledgeRepository(session).list_for_project(project_id, None))
            chunks, embedded = ChunkRepository(session).counts_for_project(project_id)
            return IndexingStatus(knowledge_items=items, chunks=chunks, embedded_chunks=embedded)

        return self._run(operation)

    def search(
        self,
        project_id: ProjectId,
        query: str,
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
        max_distance: float | None = MAX_DISTANCE,
        lifecycle: frozenset[LifecycleState] = RETRIEVABLE,
    ) -> tuple[SearchHit, ...]:
        """Find knowledge semantically related to ``query``.

        The query is embedded with the same model and dimensions as the corpus.
        Comparing vectors from different models would return confident nonsense,
        which is why the embedding version is part of the filter.

        Results beyond ``max_distance`` are dropped rather than ranked last. An
        empty result is a real answer here: it means nothing stored is close to
        the query, which a caller needs to be able to distinguish from "here are
        the least-unrelated rows we hold".
        """

        embedded = self._embedder.embed([query])
        vector = embedded.vectors[0]

        hits = self._run(
            lambda session: ChunkRepository(session).search(
                project_id,
                vector,
                limit=limit,
                kinds=kinds,
                max_distance=max_distance,
                lifecycle=lifecycle,
            )
        )
        return tuple(_to_hit(hit, query) for hit in hits)

    def best_effort(
        self,
        project_id: ProjectId,
        query: str,
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
    ) -> tuple[tuple[SearchHit, ...], str]:
        """Search the best way this deployment actually can, and say which way.

        Whether a query should be answered by meaning or by words is a property
        of the configured embedder, not of the transport that asked. It lived in
        the MCP adapter, and an HTTP route that reached straight for `search`
        returned nothing where MCP returned results — the same question, two
        answers, which is the failure ADR-0023 exists to prevent.

        Returning the mode alongside the hits is not optional. A caller that
        cannot tell a lexical answer from a semantic one reads an empty result
        as "the project does not know this" when it may mean "the words did not
        match".
        """

        if ranks_by_meaning(self._embedder_name):
            return self.search(project_id, query, limit=limit, kinds=kinds), "semantic"
        return self.find(project_id, query, limit=limit, kinds=kinds), "lexical"

    @property
    def ranks_by_meaning(self) -> bool:
        """Whether this deployment's embedder orders results by meaning."""

        return ranks_by_meaning(self._embedder_name)

    def find(
        self,
        project_id: ProjectId,
        query: str,
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
        lifecycle: frozenset[LifecycleState] = RETRIEVABLE,
    ) -> tuple[SearchHit, ...]:
        """Find knowledge containing the query's terms, without an embedder.

        The counterpart to :meth:`search`, not a degraded version of it. A query
        naming a term the corpus uses — "approval", "retention", a module name —
        is answered exactly by matching words, and answering it that way needs no
        model, survives an embedding outage, and is reproducible.

        Deliberately no vector fallback when nothing matches. Widening a failed
        exact query into an approximate one produces results the caller did not
        ask for and cannot distinguish from the ones they did.
        """

        query_terms = terms(query)
        if not query_terms:
            return ()

        hits = self._run(
            lambda session: ChunkRepository(session).search_lexical(
                project_id, query_terms, limit=limit, kinds=kinds, lifecycle=lifecycle
            )
        )
        return tuple(_to_lexical_hit(hit, query_terms) for hit in hits)


def _to_hit(hit: RetrievedChunk, query: str) -> SearchHit:
    chunk = hit.chunk
    return SearchHit(
        chunk_id=chunk.id,
        knowledge_id=chunk.knowledge_id,
        kind=chunk.knowledge_kind,
        text=chunk.text,
        distance=hit.distance,
        lifecycle=hit.lifecycle,
        mode=SearchMode.SEMANTIC,
        why=(
            f"cosine distance {hit.distance:.4f} to {query!r}; "
            f"{chunk.knowledge_kind.value} chunk {chunk.chunk_index} of "
            f"knowledge {chunk.knowledge_id}"
        ),
    )


def _to_lexical_hit(hit: LexicalChunk, query_terms: tuple[str, ...]) -> SearchHit:
    chunk = hit.chunk
    matched = ", ".join(hit.match.matched_terms)
    return SearchHit(
        chunk_id=chunk.id,
        knowledge_id=chunk.knowledge_id,
        kind=chunk.knowledge_kind,
        text=chunk.text,
        distance=None,
        lifecycle=hit.lifecycle,
        mode=SearchMode.LEXICAL,
        matched_terms=hit.match.matched_terms,
        coverage=hit.match.score,
        why=(
            f"contains {len(hit.match.matched_terms)} of {len(query_terms)} query "
            f"terms ({matched}); {chunk.knowledge_kind.value} chunk "
            f"{chunk.chunk_index} of knowledge {chunk.knowledge_id}"
        ),
    )


__all__ = [
    "EMBEDDING_VERSION",
    "MAX_DISTANCE",
    "IndexingStatus",
    "RetrievalService",
    "SearchHit",
    "SearchMode",
]
