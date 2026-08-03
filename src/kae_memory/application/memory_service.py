"""Application contracts for the persistent-memory slice.

Every domain write passes through this service. Agents never hold raw database
credentials and never issue SQL against domain tables (ADR-0004), because the
invariants that make the audit trail trustworthy live here and in the domain
layer, not in the schema.
"""

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.chunks import KnowledgeChunk, metadata_prefix, split_text
from kae_memory.domain.errors import DomainInvariantError, IdempotencyConflictError
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import (
    AgentId,
    AgentRunId,
    ChunkId,
    ExecutionId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    ProvenanceLinkId,
    RelationshipId,
    SessionId,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import (
    KnowledgeItem,
    KnowledgeKind,
    KnowledgeVersion,
    Project,
    Provenance,
    ProvenanceLink,
    ProvenanceLinkType,
    Relationship,
    RelationshipType,
)
from kae_memory.domain.workspace import (
    ActorType,
    Message,
    MessageType,
    Session,
    SessionType,
)
from kae_memory.persistence.chunk_repository import ChunkRepository
from kae_memory.persistence.readiness_repositories import (
    RelationshipRepository,
    bump_knowledge_revision,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction
from kae_memory.persistence.workspace_repositories import (
    AgentRunRepository,
    MessageRepository,
    ProjectRepository,
    ProvenanceLinkRepository,
    SessionRepository,
)

_KEY_SEPARATORS = re.compile(r"[^a-z0-9]+")

_KEY_ATTEMPTS = 5
"""How many readable keys to try before falling back to a generated suffix.

Bounded because the loop resolves a race by retrying: two callers deriving the
same key can both lose, and an unbounded retry would spin rather than fail.
"""


def project_key_from_name(name: str) -> str:
    """Return a readable key derived from a project name.

    "KAE-Memory" becomes "kae-memory". A generated key is what a person types
    and reads in a URL, so deriving it from the name they chose beats a random
    suffix — `project-a8c38ed7` tells nobody which project it is.

    Falls back to a generated key only when a name has no usable characters,
    which a non-Latin name can produce.
    """

    slug = _KEY_SEPARATORS.sub("-", name.strip().casefold()).strip("-")
    return slug[:120] or f"project-{_new_id()[:8]}"


def _chunks_for(
    item: KnowledgeItem, project_name: str, moment: datetime
) -> tuple[KnowledgeChunk, ...]:
    """Return the searchable chunks one knowledge item should have.

    The same split and metadata prefix the retrieval service applies, so a
    chunk written here is indistinguishable from one written by the indexing
    path that already existed.
    """

    kind = KnowledgeKind(item.kind)
    prefix = metadata_prefix(project_name, kind, None, item.lifecycle.value)
    return tuple(
        KnowledgeChunk(
            id=ChunkId(_new_id()),
            project_id=item.project_id,
            knowledge_id=item.id,
            knowledge_kind=kind,
            chunk_index=index,
            text=f"{prefix}\n\n{body}",
            created_at=moment,
        )
        for index, body in enumerate(split_text(item.current_version.content))
    )


def _reindex(db_session: DbSession, item: KnowledgeItem, moment: datetime) -> None:
    """Bring an item's chunks back in line with its current text.

    Where a chunk still exists at the same index its text is superseded rather
    than replaced, so the stale vector keeps serving semantic hits until a
    re-embed lands (ADR-0008). Surplus chunks are removed, because a chunk the
    item no longer produces would go on matching text it no longer says.
    """

    chunks = ChunkRepository(db_session)
    project = ProjectRepository(db_session).get(item.project_id)
    fresh = _chunks_for(item, project.name if project else "", moment)
    current = chunks.list_for_knowledge(item.id)

    for index, replacement in enumerate(fresh):
        if index < len(current):
            chunks.supersede(current[index].superseded_by(replacement.text))
        else:
            chunks.add(replacement)

    for surplus in current[len(fresh) :]:
        chunks.delete(surplus.id)


HUMAN_EXECUTION = "human"
"""Execution identifier for a change a person made directly.

Every knowledge version records the execution that produced it, and a human
correction has no agent run behind it. A named sentinel keeps that visible;
borrowing a real run identifier would make a person's edit indistinguishable
from a model's output in the audit trail.
"""


def _new_id() -> str:
    """Return an application-generated identifier.

    Identifiers are generated here rather than by the database: sequential keys
    create range hotspots in a distributed cluster (ADR-0005).
    """

    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def _collapse_key(kind: str, content: str) -> tuple[str, str]:
    """Return the identity two statements share when they are the same fact.

    Whitespace and case are not meaning, so they are normalised away. Nothing
    further: this key exists to collapse statements that are *identical*, and
    deciding that two differently-worded statements mean the same thing is a
    judgement, not a lookup. Near-duplicates are reported as findings for a
    human to resolve instead.
    """

    return kind, " ".join(content.split()).casefold()


def _payload_fingerprint(
    content: str,
    actor_type: ActorType,
    message_type: MessageType,
    actor_id: str | None,
) -> str:
    """Return a stable fingerprint of a message payload.

    Content is normalised for whitespace so that a reformatted resubmission of
    the same statement is recognised as a replay rather than reported as a
    conflict. Actor and type are included because the same words from a
    different actor are a different submission.
    """

    normalised = " ".join(content.split())
    material = "\x1f".join([normalised, actor_type.value, message_type.value, actor_id or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _resolve_replay(
    db_session: DbSession,
    project_id: ProjectId,
    idempotency_key: str,
    fingerprint: str | None,
) -> "MessageRecord":
    """Resolve a unique-key violation into a replay or a conflict."""

    existing = MessageRepository(db_session).find_by_idempotency_key(project_id, idempotency_key)
    if existing is None:  # pragma: no cover - the constraint fired, so a row exists
        raise IdempotencyConflictError(
            f"idempotency key {idempotency_key!r} conflicted but no record was found"
        )
    message, stored_fingerprint = existing
    if stored_fingerprint != fingerprint:
        raise IdempotencyConflictError(
            f"idempotency key {idempotency_key!r} was already used with a different payload"
        )
    return MessageRecord(message=message, replayed=True)


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """A recorded message and whether this call created it.

    ``replayed`` lets a caller distinguish "your submission was accepted" from
    "this was already recorded" without comparing timestamps or guessing.
    """

    message: Message
    replayed: bool


@dataclass(frozen=True, slots=True)
class WriteKnowledgeRequest:
    """One knowledge item a run wants to record."""

    kind: str
    content: str
    source: str
    from_message_id: MessageId | None = None


class MemoryService:
    """Application entry point for durable engineering memory.

    Each method is a complete unit of work. Knowledge writes and the agent-run
    status change that accompanies them commit in a single transaction, so there is
    no state in which knowledge exists without an accountable run, or a run reports
    success without its outputs.
    """

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy or RetryPolicy()
        self._clock = clock

    def _run[ResultT](self, operation: Callable[[DbSession], ResultT]) -> ResultT:
        return run_transaction(self._session_factory, operation, self._policy)

    def create_project(
        self, name: str, key: str | None = None, description: str | None = None
    ) -> Project:
        """Create a durable project.

        An omitted key is derived from the name rather than generated, so a
        project is identifiable by the key alone.

        The two cases differ on collision, deliberately. An **explicit** key is
        a request for that exact key, so a clash raises — silently returning
        something else would break :meth:`ensure_project`, which relies on the
        clash to resolve a repeat. A **derived** key is a convenience, so a
        clash is disambiguated and creation still succeeds: naming two projects
        the same is allowed, and this method has always returned a new project.
        """

        moment = self._clock()

        def insert(candidate: str) -> Project:
            project = Project(
                id=ProjectId(_new_id()),
                name=name,
                key=candidate,
                description=description,
            )

            def operation(session: DbSession) -> Project:
                ProjectRepository(session).add(project, moment)
                return project

            return self._run(operation)

        if key:
            return insert(key)

        derived = project_key_from_name(name)
        for attempt in range(1, _KEY_ATTEMPTS + 1):
            candidate = derived if attempt == 1 else f"{derived}-{attempt}"
            try:
                return insert(candidate)
            except IntegrityError:
                continue
        # Every readable candidate was taken. A generated key is worse to read
        # and better than refusing to create the project.
        return insert(f"{derived}-{_new_id()[:8]}")

    def find_project_by_key(self, key: str) -> Project | None:
        """Return a project by its human-facing key."""

        return self._run(lambda session: ProjectRepository(session).find_by_key(key))

    def ensure_project(
        self, name: str, key: str | None = None, description: str | None = None
    ) -> tuple[Project, bool]:
        """Return the project with this key, creating it if absent.

        Returns ``(project, created)``. Idempotent by key, so a retried request
        resolves to the project it already made rather than failing on the
        unique constraint — the same guarantee :meth:`enqueue_run` gives, and
        the reason a caller can retry a create without checking first.

        The race is resolved by the constraint, not by the lookup: two callers
        can both see nothing and both insert, and exactly one wins.
        """

        resolved = key or project_key_from_name(name)
        existing = self.find_project_by_key(resolved)
        if existing is not None:
            return existing, False
        try:
            return self.create_project(name, resolved, description), True
        except IntegrityError:
            winner = self.find_project_by_key(resolved)
            if winner is None:  # pragma: no cover - the constraint fired, so a row exists
                raise
            return winner, False

    def get_project(self, project_id: ProjectId) -> Project | None:
        """Return a project by identifier."""

        return self._run(lambda session: ProjectRepository(session).get(project_id))

    def list_projects(self) -> tuple[Project, ...]:
        """Return every project, newest first."""

        return self._run(lambda session: ProjectRepository(session).list_all())

    def open_session(self, project_id: ProjectId, session_type: SessionType) -> Session:
        """Open a working session within a project."""

        moment = self._clock()
        working_session = Session(
            id=SessionId(_new_id()),
            project_id=project_id,
            type=session_type,
            started_at=moment,
        )

        def operation(session: DbSession) -> Session:
            SessionRepository(session).add(working_session, moment)
            return working_session

        return self._run(operation)

    def close_session(self, session_id: SessionId) -> Session:
        """Close a session, leaving its messages and runs intact."""

        moment = self._clock()

        def operation(db_session: DbSession) -> Session:
            return SessionRepository(db_session).close(session_id, moment)

        return self._run(operation)

    def get_session(self, session_id: SessionId) -> Session | None:
        """Return a session by identifier."""

        return self._run(lambda db_session: SessionRepository(db_session).get(session_id))

    def sessions_for_project(self, project_id: ProjectId) -> tuple[Session, ...]:
        """Return a project's sessions."""

        return self._run(lambda session: SessionRepository(session).list_for_project(project_id))

    def record_message(
        self,
        project_id: ProjectId,
        session_id: SessionId,
        content: str,
        actor_type: ActorType = ActorType.USER,
        message_type: MessageType = MessageType.INPUT,
        actor_id: str | None = None,
        agent_run_id: AgentRunId | None = None,
        idempotency_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MessageRecord:
        """Persist a submission verbatim as source evidence.

        The stored text is never rewritten by extraction.

        With an ``idempotency_key``, a retry is safe (ADR-0018). The guarantee
        is the unique constraint, not a prior lookup: checking first and
        inserting second races, and two concurrent retries would both find
        nothing. The insert is attempted, and a violation is resolved by
        reading the record that won.

        Sameness is decided by a payload fingerprint. Replaying the same
        payload returns the original; reusing the key for different content
        raises :class:`IdempotencyConflictError`, because returning the
        original would silently discard the caller's new content and writing a
        second record would break the guarantee the key exists to provide.
        """

        moment = self._clock()
        fingerprint = (
            _payload_fingerprint(content, actor_type, message_type, actor_id)
            if idempotency_key is not None
            else None
        )

        def operation(db_session: DbSession) -> MessageRecord:
            repository = MessageRepository(db_session)
            message = Message(
                id=MessageId(_new_id()),
                project_id=project_id,
                session_id=session_id,
                sequence_number=repository.next_sequence_number(session_id),
                actor_type=actor_type,
                message_type=message_type,
                content=content,
                created_at=moment,
                actor_id=actor_id,
                agent_run_id=agent_run_id,
                idempotency_key=idempotency_key,
                metadata=dict(metadata or {}),
            )
            repository.add(message, fingerprint)
            db_session.flush()
            return MessageRecord(message=message, replayed=False)

        if idempotency_key is None:
            return self._run(operation)

        try:
            return self._run(operation)
        except IntegrityError:
            return self._run(
                lambda db_session: _resolve_replay(
                    db_session, project_id, idempotency_key, fingerprint
                )
            )

    def get_message(self, message_id: MessageId) -> Message | None:
        """Return a message by identifier."""

        return self._run(lambda db_session: MessageRepository(db_session).get(message_id))

    def messages_for_session(self, session_id: SessionId) -> tuple[Message, ...]:
        """Return a session's messages in submission order."""

        return self._run(lambda session: MessageRepository(session).list_for_session(session_id))

    def start_run(
        self,
        project_id: ProjectId,
        role: AgentRole,
        idempotency_key: str,
        session_id: SessionId | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Record a run durably, then mark it running.

        Submitting the same idempotency key returns the existing run rather than
        creating a second one.
        """

        moment = self._clock()

        def operation(db_session: DbSession) -> AgentRun:
            repository = AgentRunRepository(db_session)
            existing = repository.find_by_idempotency_key(project_id, idempotency_key)
            if existing is not None:
                return existing
            run = AgentRun(
                id=AgentRunId(_new_id()),
                project_id=project_id,
                role=role,
                idempotency_key=idempotency_key,
                session_id=session_id,
                input_context=input_context or {},
            ).start(moment)
            repository.add(run, moment)
            return run

        return self._run(operation)

    def enqueue_run(
        self,
        project_id: ProjectId,
        role: AgentRole,
        idempotency_key: str,
        session_id: SessionId | None = None,
        input_context: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Record a run for a worker to claim, without starting it here.

        The counterpart to :meth:`start_run`, which begins executing immediately
        in this process. An enqueued run stays ``pending`` until a worker claims
        it, so the caller returns as soon as the run is durable — the browser, or
        any other client, never owns the execution (ADR-0007).
        """

        moment = self._clock()

        def operation(db_session: DbSession) -> AgentRun:
            repository = AgentRunRepository(db_session)
            existing = repository.find_by_idempotency_key(project_id, idempotency_key)
            if existing is not None:
                return existing
            run = AgentRun(
                id=AgentRunId(_new_id()),
                project_id=project_id,
                role=role,
                idempotency_key=idempotency_key,
                session_id=session_id,
                input_context=input_context or {},
                next_attempt_at=moment,
            )
            repository.add(run, moment)
            return run

        return self._run(operation)

    def get_run(self, run_id: AgentRunId) -> AgentRun | None:
        """Return a run by identifier."""

        return self._run(lambda session: AgentRunRepository(session).get(run_id))

    def resume_run(self, run_id: AgentRunId) -> AgentRun:
        """Continue an interrupted or failed run on this worker.

        Resumption uses only durable state. Nothing is reconstructed from the
        previous process.
        """

        moment = self._clock()

        def operation(db_session: DbSession) -> AgentRun:
            repository = AgentRunRepository(db_session)
            run = repository.get(run_id)
            if run is None:
                raise LookupError(f"unknown agent run: {run_id}")
            resumed = run.start(moment)
            repository.save(resumed, moment)
            return resumed

        return self._run(operation)

    def interrupt_run(
        self, run_id: AgentRunId, continuation_state: dict[str, Any] | None = None
    ) -> AgentRun:
        """Mark a run interrupted so another worker may continue it."""

        moment = self._clock()

        def operation(db_session: DbSession) -> AgentRun:
            repository = AgentRunRepository(db_session)
            run = repository.get(run_id)
            if run is None:
                raise LookupError(f"unknown agent run: {run_id}")
            interrupted = run.interrupt(continuation_state)
            repository.save(interrupted, moment)
            return interrupted

        return self._run(operation)

    def complete_run(
        self, run_id: AgentRunId, output_summary: dict[str, Any] | None = None
    ) -> AgentRun:
        """Mark a run succeeded."""

        moment = self._clock()

        def operation(db_session: DbSession) -> AgentRun:
            repository = AgentRunRepository(db_session)
            run = repository.get(run_id)
            if run is None:
                raise LookupError(f"unknown agent run: {run_id}")
            completed = run.succeed(moment, output_summary)
            repository.save(completed, moment)
            return completed

        return self._run(operation)

    def fail_run(self, run_id: AgentRunId, error_code: str, error_message: str) -> AgentRun:
        """Mark a run failed with typed failure information."""

        moment = self._clock()

        def operation(db_session: DbSession) -> AgentRun:
            repository = AgentRunRepository(db_session)
            run = repository.get(run_id)
            if run is None:
                raise LookupError(f"unknown agent run: {run_id}")
            failed = run.fail(moment, error_code, error_message)
            repository.save(failed, moment)
            return failed

        return self._run(operation)

    def write_knowledge(
        self,
        run_id: AgentRunId,
        requests: Sequence[WriteKnowledgeRequest],
        complete_run: bool = True,
        output_summary: dict[str, Any] | None = None,
    ) -> tuple[KnowledgeItem, ...]:
        """Write knowledge and update the producing run in one transaction.

        Either both land or neither does. There is no state in which knowledge
        exists without an accountable run.
        """

        moment = self._clock()

        def operation(db_session: DbSession) -> tuple[KnowledgeItem, ...]:
            runs = AgentRunRepository(db_session)
            run = runs.get(run_id)
            if run is None:
                raise LookupError(f"unknown agent run: {run_id}")

            knowledge = SqlAlchemyKnowledgeRepository(db_session)
            links = ProvenanceLinkRepository(db_session)
            chunks = ChunkRepository(db_session)
            project = ProjectRepository(db_session).get(run.project_id)
            project_name = project.name if project else ""
            written: list[KnowledgeItem] = []
            pending_chunks: list[KnowledgeChunk] = []

            # Collapse targets: statements the project already holds that a
            # human has not ruled out. Rejected and superseded items are
            # excluded deliberately — attaching a new run's provenance to
            # something a person discarded would quietly revive their decision.
            existing = {
                _collapse_key(item.kind, item.current_version.content): item
                for item in knowledge.list_for_project(run.project_id, None)
                if item.lifecycle in {LifecycleState.PROPOSED, LifecycleState.VALIDATED}
            }
            collapsed: list[KnowledgeItemId] = []

            for request in requests:
                # The same sentence reaching two runs is one fact with two
                # sources, not two facts. Without this, splitting a document
                # into chunks inflates every area it touches.
                twin = existing.get(_collapse_key(request.kind, request.content))
                if twin is not None:
                    links.add(
                        ProvenanceLink(
                            id=ProvenanceLinkId(_new_id()),
                            project_id=run.project_id,
                            knowledge_item_id=twin.id,
                            link_type=ProvenanceLinkType.PRODUCED_BY,
                            created_at=moment,
                            knowledge_version_number=twin.current_version.number,
                            agent_run_id=run.id,
                        )
                    )
                    if request.from_message_id is not None:
                        links.add(
                            ProvenanceLink(
                                id=ProvenanceLinkId(_new_id()),
                                project_id=run.project_id,
                                knowledge_item_id=twin.id,
                                link_type=ProvenanceLinkType.DERIVED_FROM_MESSAGE,
                                created_at=moment,
                                knowledge_version_number=twin.current_version.number,
                                message_id=request.from_message_id,
                            )
                        )
                    collapsed.append(twin.id)
                    written.append(twin)
                    continue

                item = KnowledgeItem(
                    id=KnowledgeItemId(_new_id()),
                    project_id=run.project_id,
                    kind=request.kind,
                    versions=(
                        KnowledgeVersion(
                            number=1,
                            content=request.content,
                            provenance=Provenance(
                                source=request.source,
                                actor_id=AgentId(run.role.value),
                                execution_id=ExecutionId(str(run.id)),
                                recorded_at=moment,
                            ),
                            created_at=moment,
                        ),
                    ),
                )
                knowledge.add(item)
                pending_chunks.extend(_chunks_for(item, project_name, moment))
                existing[_collapse_key(item.kind, request.content)] = item
                links.add(
                    ProvenanceLink(
                        id=ProvenanceLinkId(_new_id()),
                        project_id=run.project_id,
                        knowledge_item_id=item.id,
                        link_type=ProvenanceLinkType.PRODUCED_BY,
                        created_at=moment,
                        knowledge_version_number=1,
                        agent_run_id=run.id,
                    )
                )
                if request.from_message_id is not None:
                    links.add(
                        ProvenanceLink(
                            id=ProvenanceLinkId(_new_id()),
                            project_id=run.project_id,
                            knowledge_item_id=item.id,
                            link_type=ProvenanceLinkType.DERIVED_FROM_MESSAGE,
                            created_at=moment,
                            knowledge_version_number=1,
                            message_id=request.from_message_id,
                        )
                    )
                written.append(item)

            if pending_chunks:
                # Flushed before the chunks that reference them: a chunk carries
                # a foreign key to its item, so relying on the unit of work to
                # order two independent `add` calls leaves the dependency
                # implicit and, on this schema, wrong.
                db_session.flush()
                # Indexed in the same transaction as the item it describes.
                # Knowledge that commits without chunks is invisible to every
                # search path, and a caller cannot tell that from having asked
                # about something the project does not know.
                for chunk in pending_chunks:
                    chunks.add(chunk)

            if len(written) > len(collapsed):
                # Writing knowledge is an authoritative change, so any readiness
                # snapshot taken before this transaction is now stale (ADR-0012).
                # A run that only collapsed into existing items changed no
                # statement, so it must not invalidate a valid snapshot.
                bump_knowledge_revision(db_session, run.project_id)

            if complete_run:
                summary = dict(output_summary or {})
                if collapsed:
                    summary["collapsed_duplicates"] = len(collapsed)
                runs.save(run.succeed(moment, summary or None), moment)

            return tuple(written)

        return self._run(operation)

    def confirm_knowledge(self, item_id: KnowledgeItemId) -> KnowledgeItem:
        """Confirm a candidate. Confirmation is a human act; no agent performs it."""

        def operation(db_session: DbSession) -> KnowledgeItem:
            repository = SqlAlchemyKnowledgeRepository(db_session)
            item = repository.get(item_id)
            if item is None:
                raise LookupError(f"unknown knowledge item: {item_id}")
            confirmed = item.transition_to(LifecycleState.VALIDATED)
            repository.save(confirmed)
            bump_knowledge_revision(db_session, item.project_id)
            return confirmed

        return self._run(operation)

    def reject_knowledge(self, item_id: KnowledgeItemId, note: str | None = None) -> KnowledgeItem:
        """Reject a candidate. The counterpart to confirmation, and also human.

        Rejection is not deletion. The item stays, its versions stay, and its
        provenance stays — what changes is that it stops counting toward
        readiness and stops being offered as a collapse target. A record of what
        was considered and turned down is part of the audit trail, not clutter.
        """

        def operation(db_session: DbSession) -> KnowledgeItem:
            repository = SqlAlchemyKnowledgeRepository(db_session)
            item = repository.get(item_id)
            if item is None:
                raise LookupError(f"unknown knowledge item: {item_id}")
            rejected = item.transition_to(LifecycleState.REJECTED)
            repository.save(rejected)
            bump_knowledge_revision(db_session, item.project_id)
            return rejected

        return self._run(operation)

    def correct_knowledge(
        self,
        item_id: KnowledgeItemId,
        content: str,
        source: str,
        actor_id: str | None = None,
        from_message_id: MessageId | None = None,
    ) -> KnowledgeItem:
        """Record a corrected wording as a new version of the same statement.

        Versions are append-only: the prior wording is retained and remains the
        provenance of anything derived from it while it stood. Editing in place
        would rewrite history that other records point at.

        A corrected item returns to ``PROPOSED``. It was confirmed on the old
        wording, and treating that confirmation as covering text a person has
        not read would be the single easiest way to slip an unreviewed claim
        into the confirmed set.
        """

        if not content.strip():
            raise ValueError("a correction must not be empty")

        moment = self._clock()

        def operation(db_session: DbSession) -> KnowledgeItem:
            repository = SqlAlchemyKnowledgeRepository(db_session)
            item = repository.get(item_id)
            if item is None:
                raise LookupError(f"unknown knowledge item: {item_id}")
            if item.lifecycle in {LifecycleState.REJECTED, LifecycleState.SUPERSEDED}:
                raise DomainInvariantError(
                    f"cannot correct {item.lifecycle.value} knowledge; record a new statement"
                )
            corrected = item.append_version(
                content,
                Provenance(
                    source=source,
                    actor_id=AgentId(actor_id or "human"),
                    # No agent run produced this. A synthetic identifier is
                    # clearer than borrowing one that would make a person's
                    # correction look like a model's output.
                    execution_id=ExecutionId(HUMAN_EXECUTION),
                    recorded_at=moment,
                ),
                moment,
            )
            repository.save(corrected)
            _reindex(db_session, corrected, moment)
            links = ProvenanceLinkRepository(db_session)
            if from_message_id is not None:
                links.add(
                    ProvenanceLink(
                        id=ProvenanceLinkId(_new_id()),
                        project_id=item.project_id,
                        knowledge_item_id=item.id,
                        link_type=ProvenanceLinkType.DERIVED_FROM_MESSAGE,
                        created_at=moment,
                        knowledge_version_number=corrected.current_version.number,
                        message_id=from_message_id,
                    )
                )
            bump_knowledge_revision(db_session, item.project_id)
            return corrected

        return self._run(operation)

    def supersede_knowledge(
        self, superseded_id: KnowledgeItemId, superseding_id: KnowledgeItemId
    ) -> KnowledgeItem:
        """Retire one statement in favour of another, keeping both readable.

        For when a correction is a different statement rather than better
        wording of the same one. The retired item stops counting toward
        readiness; the edge records what replaced it, so a reader who follows an
        old reference arrives somewhere rather than nowhere.
        """

        if superseded_id == superseding_id:
            raise ValueError("a statement cannot supersede itself")

        moment = self._clock()

        def operation(db_session: DbSession) -> KnowledgeItem:
            repository = SqlAlchemyKnowledgeRepository(db_session)
            old = repository.get(superseded_id)
            new = repository.get(superseding_id)
            if old is None:
                raise LookupError(f"unknown knowledge item: {superseded_id}")
            if new is None:
                raise LookupError(f"unknown knowledge item: {superseding_id}")
            if old.project_id != new.project_id:
                raise DomainInvariantError("supersession cannot cross projects")

            retired = old.transition_to(LifecycleState.SUPERSEDED)
            repository.save(retired)
            RelationshipRepository(db_session).add(
                Relationship(
                    id=RelationshipId(_new_id()),
                    project_id=old.project_id,
                    source_id=superseding_id,
                    target_id=superseded_id,
                    type=RelationshipType.SUPERSEDES,
                ),
                moment,
                None,
            )
            bump_knowledge_revision(db_session, old.project_id)
            return retired

        return self._run(operation)

    def retrieve_knowledge(
        self,
        project_id: ProjectId,
        lifecycle: LifecycleState | None = LifecycleState.VALIDATED,
        used_by_run_id: AgentRunId | None = None,
    ) -> tuple[KnowledgeItem, ...]:
        """Retrieve a project's knowledge, recording consumption when asked.

        Passing ``used_by_run_id`` records that the run consumed this knowledge, so
        "which run used this?" is answerable relationally rather than by parsing an
        execution's stored context.
        """

        moment = self._clock()

        def operation(db_session: DbSession) -> tuple[KnowledgeItem, ...]:
            items = SqlAlchemyKnowledgeRepository(db_session).list_for_project(
                project_id, lifecycle
            )
            if used_by_run_id is not None:
                links = ProvenanceLinkRepository(db_session)
                for item in items:
                    links.add(
                        ProvenanceLink(
                            id=ProvenanceLinkId(_new_id()),
                            project_id=project_id,
                            knowledge_item_id=item.id,
                            link_type=ProvenanceLinkType.USED_BY,
                            created_at=moment,
                            knowledge_version_number=item.current_version.number,
                            agent_run_id=used_by_run_id,
                        )
                    )
            return items

        return self._run(operation)

    def runs_for_project(
        self, project_id: ProjectId, status: RunStatus | None = None
    ) -> tuple[AgentRun, ...]:
        """Return the project's execution history, most recent first."""

        return self._run(
            lambda session: AgentRunRepository(session).list_for_project(project_id, status)
        )

    def resumable_runs(self, project_id: ProjectId) -> tuple[AgentRun, ...]:
        """Return runs another worker may continue."""

        return self._run(lambda session: AgentRunRepository(session).list_resumable(project_id))

    def knowledge_produced_by(self, run_id: AgentRunId) -> tuple[KnowledgeItem, ...]:
        """Return the knowledge a run produced.

        Replaying a completed run returns its original output rather than
        producing a second set: the guarantee is one run, one result.
        """

        def operation(db_session: DbSession) -> tuple[KnowledgeItem, ...]:
            item_ids = ProvenanceLinkRepository(db_session).items_produced_by(run_id)
            knowledge = SqlAlchemyKnowledgeRepository(db_session)
            found = [knowledge.get(item_id) for item_id in item_ids]
            return tuple(item for item in found if item is not None)

        return self._run(operation)

    def provenance_for_item(self, item_id: KnowledgeItemId) -> tuple[ProvenanceLink, ...]:
        """Return every provenance link recorded for a knowledge item."""

        return self._run(lambda session: ProvenanceLinkRepository(session).list_for_item(item_id))
