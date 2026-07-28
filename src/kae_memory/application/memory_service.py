"""Application contracts for the persistent-memory slice.

Every domain write passes through this service. Agents never hold raw database
credentials and never issue SQL against domain tables (ADR-0004), because the
invariants that make the audit trail trustworthy live here and in the domain
layer, not in the schema.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import (
    AgentId,
    AgentRunId,
    ExecutionId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    ProvenanceLinkId,
    SessionId,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import (
    KnowledgeItem,
    KnowledgeVersion,
    Project,
    Provenance,
    ProvenanceLink,
    ProvenanceLinkType,
)
from kae_memory.domain.workspace import (
    ActorType,
    Message,
    MessageType,
    Session,
    SessionType,
)
from kae_memory.persistence.readiness_repositories import bump_knowledge_revision
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction
from kae_memory.persistence.workspace_repositories import (
    AgentRunRepository,
    MessageRepository,
    ProjectRepository,
    ProvenanceLinkRepository,
    SessionRepository,
)


def _new_id() -> str:
    """Return an application-generated identifier.

    Identifiers are generated here rather than by the database: sequential keys
    create range hotspots in a distributed cluster (ADR-0005).
    """

    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


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
        """Create a durable project."""

        project = Project(
            id=ProjectId(_new_id()),
            name=name,
            key=key or f"project-{_new_id()[:8]}",
            description=description,
        )
        moment = self._clock()

        def operation(session: DbSession) -> Project:
            ProjectRepository(session).add(project, moment)
            return project

        return self._run(operation)

    def get_project(self, project_id: ProjectId) -> Project | None:
        """Return a project by identifier."""

        return self._run(lambda session: ProjectRepository(session).get(project_id))

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

    def record_message(
        self,
        project_id: ProjectId,
        session_id: SessionId,
        content: str,
        actor_type: ActorType = ActorType.USER,
        message_type: MessageType = MessageType.INPUT,
        actor_id: str | None = None,
        agent_run_id: AgentRunId | None = None,
    ) -> Message:
        """Persist a submission verbatim as source evidence.

        The stored text is never rewritten by extraction.
        """

        moment = self._clock()

        def operation(db_session: DbSession) -> Message:
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
            )
            repository.add(message)
            return message

        return self._run(operation)

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
            written: list[KnowledgeItem] = []

            for request in requests:
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

            if written:
                # Writing knowledge is an authoritative change, so any readiness
                # snapshot taken before this transaction is now stale (ADR-0012).
                bump_knowledge_revision(db_session, run.project_id)

            if complete_run:
                runs.save(run.succeed(moment, output_summary), moment)

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
