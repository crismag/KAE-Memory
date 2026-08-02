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
from kae_memory.domain.chunks import (
    EMBEDDING_VERSION,
    MAX_DISTANCE,
    KnowledgeChunk,
    metadata_prefix,
    split_text,
)
from kae_memory.domain.identifiers import ChunkId, KnowledgeItemId, ProjectId
from kae_memory.domain.lexical import terms
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind
from kae_memory.persistence.chunk_repository import (
    ChunkRepository,
    LexicalChunk,
    RetrievedChunk,
)
from kae_memory.persistence.transactions import RetryPolicy, run_transaction


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


class RetrievalService:
    """Application entry point for semantic memory."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        embedder: EmbeddingPort,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
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
        """

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

    def search(
        self,
        project_id: ProjectId,
        query: str,
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
        max_distance: float | None = MAX_DISTANCE,
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
                project_id, vector, limit=limit, kinds=kinds, max_distance=max_distance
            )
        )
        return tuple(_to_hit(hit, query) for hit in hits)

    def find(
        self,
        project_id: ProjectId,
        query: str,
        limit: int = 8,
        kinds: Sequence[KnowledgeKind] | None = None,
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
                project_id, query_terms, limit=limit, kinds=kinds
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
    "RetrievalService",
    "SearchHit",
    "SearchMode",
]
