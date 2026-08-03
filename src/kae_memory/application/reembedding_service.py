"""Moving a corpus from one embedding space to another, restartably.

Changing the model means every existing vector belongs to a space the current
search no longer queries. Re-embedding is therefore a migration, not a retry
loop, and it has to survive interruption: a corpus large enough to matter is
large enough that something will fail partway.

Four properties shape the implementation.

**Nothing is destroyed before a replacement exists.** The provider is called
first; the old vector stays in place until a successful response can replace it
in one statement. A failed request costs recall for one chunk and loses nothing.

**No transaction spans the provider call.** Claiming, embedding, and storing are
three separate units of work (ADR-0004). That rules out row locks for mutual
exclusion, which is why claiming is a compare-and-set.

**One failure does not end the run.** A chunk that fails is marked and left
retryable, and the run continues. A migration that aborts on the first bad chunk
is a migration nobody can finish.

**Rerunning is safe and does less work.** Selection is by current state, so a
second run sees only what the first did not complete.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.agents.embedding import EmbeddingError, EmbeddingPort
from kae_memory.domain.chunks import EMBEDDING_VERSION, KnowledgeChunk
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.chunk_repository import ChunkRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction

LOGGER = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50
"""Chunks selected per pass.

Bounded because selection and progress reporting both happen per batch: a run
over a large corpus should show movement rather than appearing hung, and a
crash should lose at most one batch of claims.
"""


@dataclass(frozen=True, slots=True)
class ChunkFailure:
    """One chunk that could not be embedded, and why."""

    chunk_id: str
    project_id: str
    error_code: str
    detail: str


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """What one migration run did.

    ``remaining`` is counted after the run, so a bounded run reports honestly
    that it did not finish rather than implying the corpus is done.
    """

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    remaining: int = 0
    target_version: int = EMBEDDING_VERSION
    model: str | None = None
    failures: tuple[ChunkFailure, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        """Whether anything is still outstanding."""

        return self.remaining == 0 and self.failed == 0


class ReembeddingService:
    """Re-embeds chunks that do not belong to the current embedding space."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        embedder: EmbeddingPort,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        embedding_version: int = EMBEDDING_VERSION,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._policy = policy or RetryPolicy()
        self._clock = clock
        self._version = embedding_version

    def _run[ResultT](self, operation: Callable[[DbSession], ResultT]) -> ResultT:
        return run_transaction(self._session_factory, operation, self._policy)

    def outstanding(self, project_id: ProjectId | None = None) -> int:
        """Return how many chunks still need the current embedding space."""

        return self._run(
            lambda session: len(
                ChunkRepository(session).list_needing_embedding(
                    project_id, limit=1_000_000, embedding_version=self._version
                )
            )
        )

    def release_claims(self, project_id: ProjectId | None = None) -> int:
        """Return chunks stranded by a dead runner to pending."""

        return self._run(lambda session: ChunkRepository(session).release_claims(project_id))

    def migrate(
        self,
        project_id: ProjectId | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_chunks: int | None = None,
        progress: Callable[[MigrationReport], None] | None = None,
    ) -> MigrationReport:
        """Re-embed outstanding chunks, batch by batch, until none remain.

        ``max_chunks`` bounds one invocation without ending the migration; the
        next run resumes from whatever is still outstanding.
        """

        attempted = succeeded = failed = skipped = 0
        failures: list[ChunkFailure] = []
        model: str | None = None

        for chunk in self._batches(project_id, batch_size, max_chunks):
            if not self._claim(chunk):
                # Another runner took it between selection and here. Not an
                # error: exactly one of us proceeds, which is the point.
                skipped += 1
                continue

            attempted += 1
            try:
                result = self._embedder.embed([chunk.text])
            except EmbeddingError as error:
                # The old vector is untouched. Marking failed leaves the chunk
                # selectable by a later run.
                self._mark_failed(chunk)
                failed += 1
                failures.append(
                    ChunkFailure(
                        chunk_id=str(chunk.id),
                        project_id=str(chunk.project_id),
                        error_code=error.error_code,
                        detail=str(error)[:200],
                    )
                )
                LOGGER.warning("chunk %s failed to embed: %s", chunk.id, error.error_code)
                continue

            model = result.model
            self._store(chunk, result.vectors[0], result.model, result.dimensions)
            succeeded += 1

            if progress and attempted % batch_size == 0:
                progress(
                    MigrationReport(
                        attempted=attempted,
                        succeeded=succeeded,
                        failed=failed,
                        skipped=skipped,
                        remaining=self.outstanding(project_id),
                        target_version=self._version,
                        model=model,
                    )
                )

        return MigrationReport(
            attempted=attempted,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            remaining=self.outstanding(project_id),
            target_version=self._version,
            model=model,
            failures=tuple(failures),
        )

    def _batches(
        self, project_id: ProjectId | None, batch_size: int, max_chunks: int | None
    ) -> Iterator[KnowledgeChunk]:
        """Yield outstanding chunks, re-selecting as work completes.

        Re-selects rather than paginating. A chunk finished in the previous
        batch is no longer outstanding, so an offset would step over work; asking
        again for "the next batch that still needs doing" is what makes a resumed
        run continue rather than restart.

        Stops when a pass yields nothing new, which is also how a corpus of only
        claimed-or-failed chunks terminates instead of spinning.
        """

        seen: set[str] = set()
        produced = 0
        while True:
            size = batch_size
            if max_chunks is not None:
                remaining_budget = max_chunks - produced
                if remaining_budget <= 0:
                    return
                size = min(batch_size, remaining_budget)

            def select(session: DbSession, size: int = size) -> tuple[KnowledgeChunk, ...]:
                return ChunkRepository(session).list_needing_embedding(
                    project_id, limit=size, embedding_version=self._version
                )

            batch = self._run(select)
            fresh = [chunk for chunk in batch if str(chunk.id) not in seen]
            if not fresh:
                return
            for chunk in fresh:
                seen.add(str(chunk.id))
                produced += 1
                yield chunk

    def _claim(self, chunk: KnowledgeChunk) -> bool:
        return self._run(lambda session: ChunkRepository(session).claim(chunk.id, chunk.state))

    def _store(
        self, chunk: KnowledgeChunk, vector: tuple[float, ...], model: str, dimensions: int
    ) -> None:
        moment = self._clock()

        def operation(session: DbSession) -> None:
            ChunkRepository(session).store_embedding(
                chunk.id, vector, model, dimensions, moment, embedding_version=self._version
            )

        self._run(operation)

    def _mark_failed(self, chunk: KnowledgeChunk) -> None:
        self._run(lambda session: ChunkRepository(session).mark_failed(chunk.id))


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "ChunkFailure",
    "MigrationReport",
    "ReembeddingService",
]
