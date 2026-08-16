"""Document ingestion — one large file becomes many bounded extractions.

Extraction reads one message and returns at most ``max_items`` candidates. A
forty-page requirements document submitted whole would therefore yield a handful
of statements drawn from wherever the model happened to look, with no way to
tell what it skipped. Splitting first makes each extraction small enough to be
thorough and each result attributable to the span it came from.

Fan-out **enqueues**; it does not execute. Runs land as ``pending`` and workers
claim them, so the caller returns as soon as the work is durable and throughput
is a property of how many workers are running rather than of who submitted the
document (ADR-0007).

Nothing here is silently bounded. Every limit that changes what gets read is
reported back, because a truncated ingestion that looks complete is worse than
one that refuses.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.chunks import MAX_TOKENS, TARGET_TOKENS, estimate_tokens, split_text
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import AgentRunId, MessageId, ProjectId, SessionId
from kae_memory.domain.models import KnowledgeSourceType
from kae_memory.domain.workspace import ActorType, MessageType, SessionType
from kae_memory.persistence.transactions import RetryPolicy

from .memory_service import MemoryService

DEFAULT_MAX_CHUNKS = 50
"""How many chunks one document may become.

The extent dial. Fifty chunks at the default target is roughly 25,000 tokens of
source — enough for a substantial specification, small enough that a mistaken
paste does not enqueue a thousand model calls. Raise it for real ingestion, drop
it for a demo; either way what it excludes is reported.
"""

DEFAULT_MAX_ITEMS_PER_CHUNK = 20
"""How many candidates one chunk may yield.

The breadth dial, and a quality control rather than a cost one: a chunk that
produces forty statements is usually being over-read, and ADR-0006's prompt
already asks for fewer, well-grounded items over broad coverage.
"""


@dataclass(frozen=True, slots=True)
class IngestionPolicy:
    """Depth, extent, and breadth limits for one ingestion.

    Depth is chunk size: smaller chunks mean more extractions over less text
    each, which reads a document more closely and costs more runs. Extent is how
    much of the document is read at all. Breadth is how much one chunk may say.

    Throughput is deliberately absent. Fan-out enqueues pending runs and workers
    drain them, so the rate is set by how many workers run and how fast they
    poll — see ``KAE_WORKER_POLL_SECONDS`` and the worker count. Pretending to
    control it from here would mean holding work in the submitting process,
    which is exactly what ADR-0007 moved away from.
    """

    target_tokens: int = TARGET_TOKENS
    max_tokens: int = MAX_TOKENS
    max_chunks: int = DEFAULT_MAX_CHUNKS
    max_items_per_chunk: int = DEFAULT_MAX_ITEMS_PER_CHUNK

    def __post_init__(self) -> None:
        if self.target_tokens < 1 or self.max_tokens < 1:
            raise ValueError("chunk sizes must be positive")
        if self.target_tokens > self.max_tokens:
            raise ValueError("target_tokens must not exceed max_tokens")
        if self.max_chunks < 1:
            raise ValueError("max_chunks must be at least 1")
        if self.max_items_per_chunk < 1:
            raise ValueError("max_items_per_chunk must be at least 1")


@dataclass(frozen=True, slots=True)
class IngestedChunk:
    """One span of the document, and the run that will read it."""

    index: int
    message_id: MessageId
    run_id: AgentRunId
    estimated_tokens: int


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """What one ingestion recorded, including what it left out."""

    document: str
    session_id: SessionId
    chunks: tuple[IngestedChunk, ...]
    policy: IngestionPolicy
    chunks_available: int = 0
    truncated_chunks: int = 0
    replayed: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def complete(self) -> bool:
        """Whether the whole document was enqueued for reading."""

        return self.truncated_chunks == 0


class IngestionService:
    """Turns a document into per-chunk messages and the runs that read them."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        memory: MemoryService | None = None,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._memory = memory or MemoryService(session_factory, policy)
        self._clock = clock

    def ingest_document(
        self,
        project_id: ProjectId,
        document: str,
        text: str,
        policy: IngestionPolicy | None = None,
        session_id: SessionId | None = None,
        actor_id: str | None = None,
        source_type: KnowledgeSourceType = KnowledgeSourceType.IMPORTED_DOCUMENT,
    ) -> IngestionResult:
        """Split ``text``, record each span verbatim, and enqueue a run per span.

        Chunks are recorded as messages rather than kept in run context: the
        stored message is the verbatim evidence a statement traces back to, and
        extraction from a copy passed through an API would break the provenance
        chain this product exists to show.

        ``source_type`` is carried on every run this creates, because the caller
        is the last place that knows whether the text is a repository file or a
        specification somebody pasted. By the time a run reads it the two are
        indistinguishable, and ADR-0008 makes readiness depend on the difference.

        Idempotent per ``(document, chunk index, content)``. Re-submitting the
        same document re-uses the messages and runs it already created instead
        of reading it twice.
        """

        settings = policy or IngestionPolicy()
        if not document.strip():
            raise ValueError("document name is required")
        if not text.strip():
            raise ValueError("document text is required")

        bodies = split_text(text, settings.target_tokens, settings.max_tokens)
        available = len(bodies)
        kept = bodies[: settings.max_chunks]
        truncated = available - len(kept)

        warnings: list[str] = []
        if truncated:
            warnings.append(
                f"{truncated} of {available} chunks were not ingested: max_chunks is "
                f"{settings.max_chunks}. Raise it, or split the document, before "
                "treating this project's knowledge as covering the whole file."
            )

        working_session = (
            session_id or self._memory.open_session(project_id, SessionType.DISCOVERY).id
        )

        chunks: list[IngestedChunk] = []
        replayed = True
        for index, body in enumerate(kept):
            key = _chunk_key(document, index, body)
            record = self._memory.record_message(
                project_id,
                working_session,
                content=body,
                actor_type=ActorType.USER,
                message_type=MessageType.INPUT,
                actor_id=actor_id,
                idempotency_key=key,
            )
            replayed = replayed and record.replayed
            run = self._memory.enqueue_run(
                project_id,
                AgentRole.REQUIREMENTS,
                idempotency_key=f"extract:{key}",
                session_id=working_session,
                input_context={
                    "message_id": str(record.message.id),
                    "document": document,
                    "source_type": source_type.value,
                    "chunk_index": index,
                    "chunk_count": len(kept),
                    "max_items": settings.max_items_per_chunk,
                    # Carried on the first chunk only, and read back by
                    # `extraction_coverage`.
                    #
                    # Truncated chunks never become runs, so coverage — which
                    # counts runs — reported `complete: true` for a document
                    # cut off at `max_chunks`. The disclosure built to make
                    # readiness honest had a blind spot exactly where the
                    # largest documents are (AUD-024).
                    #
                    # On chunk zero rather than on all of them so a reader can
                    # sum without double-counting a document.
                    **({"chunks_not_ingested": truncated} if index == 0 and truncated else {}),
                },
            )
            chunks.append(
                IngestedChunk(
                    index=index,
                    message_id=record.message.id,
                    run_id=run.id,
                    estimated_tokens=estimate_tokens(body),
                )
            )

        return IngestionResult(
            document=document,
            session_id=working_session,
            chunks=tuple(chunks),
            policy=settings,
            chunks_available=available,
            truncated_chunks=truncated,
            replayed=bool(chunks) and replayed,
            warnings=tuple(warnings),
        )

    def enqueue_review(
        self,
        project_id: ProjectId,
        idempotency_key: str,
        session_id: SessionId | None = None,
    ) -> AgentRunId:
        """Enqueue the single review pass that follows an ingestion.

        Kept separate from :meth:`ingest_document` on purpose. Review is a
        cross-chunk operation — chunk 7 and chunk 31 may conflict and neither
        run can see the other — so it is only meaningful once the extraction
        runs have finished. There is no run-dependency mechanism here, so
        enqueuing it alongside them would let a worker claim it first and review
        an empty project.
        """

        run = self._memory.enqueue_run(
            project_id, AgentRole.REVIEW, idempotency_key, session_id=session_id
        )
        return run.id

    def outstanding_runs(self, project_id: ProjectId) -> int:
        """Return how many enqueued runs have not reached a terminal state.

        The signal a caller needs to know when review is worth enqueuing.
        """

        return sum(1 for run in self._memory.runs_for_project(project_id) if not run.is_terminal)


def _chunk_key(document: str, index: int, body: str) -> str:
    """Return the idempotency key for one chunk of one document.

    Content is part of the key. A document re-submitted with an edited middle
    replays the spans that did not change and ingests the ones that did, rather
    than either duplicating everything or silently skipping the edit.
    """

    digest = sha256(body.encode("utf-8")).hexdigest()[:16]
    return f"doc:{document}:{index}:{digest}"


def policy_from_environment(
    environ: dict[str, str], base: IngestionPolicy | None = None
) -> IngestionPolicy:
    """Return an ingestion policy with ``KAE_INGEST_*`` overrides applied.

    Overrides are read where the application is wired rather than inside the
    service, so a caller can still pass an explicit policy per request — a demo
    dialling extent down for one document must not have to change deployment
    configuration.
    """

    settings = base or IngestionPolicy()
    mapping = (
        ("KAE_INGEST_TARGET_TOKENS", "target_tokens"),
        ("KAE_INGEST_MAX_TOKENS", "max_tokens"),
        ("KAE_INGEST_MAX_CHUNKS", "max_chunks"),
        ("KAE_INGEST_MAX_ITEMS", "max_items_per_chunk"),
    )
    changes: dict[str, int] = {}
    for name, attribute in mapping:
        raw = environ.get(name, "").strip()
        if raw:
            changes[attribute] = int(raw)
    return replace(settings, **changes) if changes else settings


__all__ = [
    "DEFAULT_MAX_CHUNKS",
    "DEFAULT_MAX_ITEMS_PER_CHUNK",
    "IngestedChunk",
    "IngestionPolicy",
    "IngestionResult",
    "IngestionService",
    "policy_from_environment",
]
