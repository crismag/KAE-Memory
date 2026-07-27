"""Chunk persistence and semantic retrieval.

Cosine distance over a single vector index, always scoped to one project. There
are no cross-project reads: a project is the durable boundary that owns
everything derived within it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session as DbSession

from kae_memory.domain.chunks import EMBEDDING_VERSION, EmbeddingState, KnowledgeChunk
from kae_memory.domain.identifiers import ChunkId, KnowledgeItemId, ProjectId
from kae_memory.domain.models import KnowledgeKind

from .tables import KnowledgeChunkRow
from .timestamps import as_aware


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One semantic hit, with everything needed to explain why it was returned."""

    chunk: KnowledgeChunk
    distance: float

    @property
    def similarity(self) -> float:
        """Cosine similarity, for reporting. Lower distance means more similar."""

        return 1.0 - self.distance


class ChunkRepository:
    """Persistence boundary for knowledge chunks and their embeddings."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

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

    def list_needing_embedding(
        self, project_id: ProjectId, limit: int = 100
    ) -> tuple[KnowledgeChunk, ...]:
        """Return chunks awaiting an embedding, oldest first.

        Includes failed chunks: an unembedded chunk costs recall, never
        correctness, so retrying is always safe.
        """

        rows = self._session.scalars(
            select(KnowledgeChunkRow)
            .where(
                KnowledgeChunkRow.project_id == str(project_id),
                KnowledgeChunkRow.embedding_state.in_(
                    [
                        EmbeddingState.PENDING.value,
                        EmbeddingState.STALE.value,
                        EmbeddingState.FAILED.value,
                    ]
                ),
            )
            .order_by(KnowledgeChunkRow.created_at)
            .limit(limit)
        ).all()
        return tuple(_to_domain(row) for row in rows)

    def store_embedding(
        self,
        chunk_id: ChunkId,
        vector: Sequence[float],
        model: str,
        dimensions: int,
        moment: datetime,
    ) -> None:
        """Attach a vector to a chunk and mark it embedded."""

        self._session.execute(
            update(KnowledgeChunkRow)
            .where(KnowledgeChunkRow.chunk_id == str(chunk_id))
            .values(
                embedding=list(vector),
                embedding_state=EmbeddingState.EMBEDDED.value,
                embedding_model=model,
                embedding_dimensions=dimensions,
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
    ) -> tuple[RetrievedChunk, ...]:
        """Return the nearest chunks by cosine distance.

        Scoped to one project, and to one embedding version: vectors produced by
        different models occupy different spaces, so mixing them in a single
        ranking would return confident nonsense.
        """

        literal = "[" + ",".join(repr(float(value)) for value in query_vector) + "]"
        sql = (
            "SELECT chunk_id, embedding <=> :vector AS distance "
            "FROM knowledge_chunks "
            "WHERE project_id = :project_id "
            "  AND embedding IS NOT NULL "
            "  AND embedding_version = :embedding_version "
        )
        params: dict[str, object] = {
            "vector": literal,
            "project_id": str(project_id),
            "embedding_version": embedding_version,
            "limit": limit,
        }
        if kinds:
            names = [kind.value for kind in kinds]
            placeholders = ", ".join(f":kind_{index}" for index in range(len(names)))
            sql += f"  AND knowledge_kind IN ({placeholders}) "
            params.update({f"kind_{index}": name for index, name in enumerate(names)})
        sql += "ORDER BY distance LIMIT :limit"

        hits = self._session.execute(text(sql), params).all()
        results: list[RetrievedChunk] = []
        for chunk_id, distance in hits:
            row = self._session.get(KnowledgeChunkRow, chunk_id)
            if row is not None:
                results.append(RetrievedChunk(chunk=_to_domain(row), distance=float(distance)))
        return tuple(results)


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
