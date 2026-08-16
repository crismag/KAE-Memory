"""Repositories for projects, sessions, messages, agent runs, and provenance."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import (
    DEFAULT_LEASE_SECONDS,
    AgentRole,
    AgentRun,
    Lease,
    RunStatus,
)
from kae_memory.domain.identifiers import (
    AgentRunId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    ProvenanceLinkId,
    SessionId,
)
from kae_memory.domain.models import (
    PRODUCING_LINK_TYPES,
    KnowledgeSourceType,
    Project,
    ProvenanceLink,
    ProvenanceLinkType,
)
from kae_memory.domain.workspace import (
    ActorType,
    Message,
    MessagePurpose,
    MessageType,
    ProjectStatus,
    Session,
    SessionStatus,
    SessionType,
)

from .tables import AgentRunRow, MessageRow, ProjectRow, ProvenanceLinkRow, SessionRow
from .timestamps import as_aware


class ProjectRepository:
    """Persistence boundary for durable projects."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, project: Project, moment: datetime) -> None:
        """Persist a new project."""

        self._session.add(
            ProjectRow(
                project_id=str(project.id),
                project_key=project.key or str(project.id),
                name=project.name,
                description=project.description,
                status=project.status.value,
                created_at=moment,
                updated_at=moment,
            )
        )

    def find_by_key(self, key: str) -> Project | None:
        """Return a project by its human-facing key, or ``None`` if unknown.

        The key is unique, which is what lets creation be idempotent: a second
        request naming a project that already exists resolves to it rather than
        colliding on the constraint.
        """

        row = self._session.scalars(select(ProjectRow).where(ProjectRow.project_key == key)).first()
        return None if row is None else _project_to_domain(row)

    def get(self, project_id: ProjectId) -> Project | None:
        """Return a project by identifier, or ``None`` if unknown."""

        row = self._session.get(ProjectRow, str(project_id))
        return None if row is None else _project_to_domain(row)

    def list_all(self) -> tuple[Project, ...]:
        """Return every project, newest first."""

        rows = self._session.scalars(
            select(ProjectRow).order_by(ProjectRow.created_at.desc())
        ).all()
        return tuple(
            Project(
                id=ProjectId(row.project_id),
                name=row.name,
                key=row.project_key,
                description=row.description,
                status=ProjectStatus(row.status),
                knowledge_revision=row.knowledge_revision,
            )
            for row in rows
        )

    def get_by_key(self, project_key: str) -> Project | None:
        """Return a project by its human-readable key."""

        row = self._session.scalars(
            select(ProjectRow).where(ProjectRow.project_key == project_key)
        ).one_or_none()
        if row is None:
            return None
        return self.get(ProjectId(row.project_id))


class SessionRepository:
    """Persistence boundary for working sessions."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, working_session: Session, moment: datetime) -> None:
        """Persist a new session."""

        self._session.add(
            SessionRow(
                session_id=str(working_session.id),
                project_id=str(working_session.project_id),
                session_type=working_session.type.value,
                status=working_session.status.value,
                started_at=working_session.started_at,
                ended_at=working_session.ended_at,
                created_at=moment,
            )
        )

    def get(self, session_id: SessionId) -> Session | None:
        """Return a session by identifier, or ``None`` if unknown."""

        row = self._session.get(SessionRow, str(session_id))
        if row is None:
            return None
        return _session_to_domain(row)

    def close(self, session_id: SessionId, moment: datetime) -> Session:
        """Close a session, leaving its messages and runs intact."""

        row = self._session.get(SessionRow, str(session_id))
        if row is None:
            raise LookupError(f"unknown session: {session_id}")
        row.status = SessionStatus.CLOSED.value
        row.ended_at = moment
        return _session_to_domain(row)

    def list_for_project(self, project_id: ProjectId) -> tuple[Session, ...]:
        """Return the project's sessions, most recently started first."""

        rows = self._session.scalars(
            select(SessionRow)
            .where(SessionRow.project_id == str(project_id))
            .order_by(SessionRow.started_at.desc())
        ).all()
        return tuple(_session_to_domain(row) for row in rows)


class MessageRepository:
    """Persistence boundary for immutable interaction evidence."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, message: Message, fingerprint: str | None = None) -> None:
        """Persist a message. Messages are never updated once written."""

        self._session.add(
            MessageRow(
                message_id=str(message.id),
                project_id=str(message.project_id),
                session_id=str(message.session_id),
                agent_run_id=str(message.agent_run_id) if message.agent_run_id else None,
                sequence_number=message.sequence_number,
                actor_type=message.actor_type.value,
                actor_id=message.actor_id,
                message_type=message.message_type.value,
                content=message.content,
                message_metadata=dict(message.metadata),
                created_at=message.created_at,
                idempotency_key=message.idempotency_key,
                payload_fingerprint=fingerprint,
                purpose=message.purpose.value,
            )
        )

    def get(self, message_id: MessageId) -> Message | None:
        """Return a message by identifier."""

        row = self._session.get(MessageRow, str(message_id))
        return None if row is None else _message_to_domain(row)

    def find_by_idempotency_key(
        self, project_id: ProjectId, idempotency_key: str
    ) -> tuple[Message, str | None] | None:
        """Return the message previously recorded under this key, with its fingerprint.

        Used to resolve a unique-violation after the fact, not to avoid one:
        checking first and inserting second is exactly the race the constraint
        exists to close.
        """

        row = self._session.scalars(
            select(MessageRow).where(
                MessageRow.project_id == str(project_id),
                MessageRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        return None if row is None else (_message_to_domain(row), row.payload_fingerprint)

    def next_sequence_number(self, session_id: SessionId) -> int:
        """Return the next sequence number for a session."""

        highest = self._session.scalar(
            select(func.max(MessageRow.sequence_number)).where(
                MessageRow.session_id == str(session_id)
            )
        )
        return int(highest or 0) + 1

    def list_for_session(self, session_id: SessionId) -> tuple[Message, ...]:
        """Return a session's messages in submission order."""

        rows = self._session.scalars(
            select(MessageRow)
            .where(MessageRow.session_id == str(session_id))
            .order_by(MessageRow.sequence_number)
        ).all()
        return tuple(_message_to_domain(row) for row in rows)


class AgentRunRepository:
    """Persistence boundary for agent executions."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, run: AgentRun, moment: datetime) -> None:
        """Persist a new run. A run that is not recorded did not happen."""

        self._session.add(
            AgentRunRow(
                agent_run_id=str(run.id),
                project_id=str(run.project_id),
                session_id=str(run.session_id) if run.session_id else None,
                agent_role=run.role.value,
                status=run.status.value,
                idempotency_key=run.idempotency_key,
                attempt_number=run.attempt_number,
                input_context=run.input_context or {},
                output_summary=run.output_summary or {},
                continuation_state=run.continuation_state or {},
                started_at=run.started_at,
                completed_at=run.completed_at,
                failed_at=run.failed_at,
                error_code=run.error_code,
                error_message=run.error_message,
                created_at=moment,
                updated_at=moment,
                lease_owner=run.lease.owner if run.lease else None,
                lease_token=run.lease.token if run.lease else 0,
                lease_acquired_at=run.lease.acquired_at if run.lease else None,
                lease_expires_at=run.lease.expires_at if run.lease else None,
                heartbeat_at=run.lease.heartbeat_at if run.lease else None,
                next_attempt_at=run.next_attempt_at or moment,
            )
        )

    def save(self, run: AgentRun, moment: datetime) -> None:
        """Persist a status change for an existing run."""

        row = self._session.get(AgentRunRow, str(run.id))
        if row is None:
            raise LookupError(f"unknown agent run: {run.id}")
        row.status = run.status.value
        row.attempt_number = run.attempt_number
        row.input_context = run.input_context or {}
        row.output_summary = run.output_summary or {}
        row.continuation_state = run.continuation_state or {}
        row.started_at = run.started_at
        row.completed_at = run.completed_at
        row.failed_at = run.failed_at
        row.error_code = run.error_code
        row.error_message = run.error_message
        row.updated_at = moment

    def get(self, run_id: AgentRunId) -> AgentRun | None:
        """Return a run by identifier, or ``None`` if unknown."""

        row = self._session.get(AgentRunRow, str(run_id))
        return None if row is None else _run_to_domain(row)

    def find_by_idempotency_key(self, project_id: ProjectId, key: str) -> AgentRun | None:
        """Return the latest attempt for an idempotency key, if one exists.

        Re-submitting the same key returns the existing run rather than creating a
        second one.
        """

        row = self._session.scalars(
            select(AgentRunRow)
            .where(
                AgentRunRow.project_id == str(project_id),
                AgentRunRow.idempotency_key == key,
            )
            .order_by(AgentRunRow.attempt_number.desc())
        ).first()
        return None if row is None else _run_to_domain(row)

    def list_for_project(
        self, project_id: ProjectId, status: RunStatus | None = None
    ) -> tuple[AgentRun, ...]:
        """Return the project's runs, most recent first, optionally by status."""

        statement = select(AgentRunRow).where(AgentRunRow.project_id == str(project_id))
        if status is not None:
            statement = statement.where(AgentRunRow.status == status.value)
        rows = self._session.scalars(statement.order_by(AgentRunRow.created_at.desc())).all()
        return tuple(_run_to_domain(row) for row in rows)

    def claim_next(
        self,
        worker_id: str,
        moment: datetime,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        project_id: ProjectId | None = None,
    ) -> AgentRun | None:
        """Atomically claim one runnable or reclaimable run, or return ``None``.

        Claiming is a compare-and-swap on ``lease_token`` rather than a held
        ``SELECT ... FOR UPDATE``. Two workers may read the same candidate, but
        only the one whose update still matches the observed token wins; the other
        updates zero rows and looks again. This is portable across engines and is
        the same guarantee a row lock would give, without holding a transaction
        open across external work — which CockroachDB could not do anyway, since
        its row locks end with the transaction.

        The caller commits. This method performs no external work of its own, so
        the claim transaction stays short.
        """

        expires_at = moment + timedelta(seconds=lease_seconds)
        statement = select(AgentRunRow).where(
            AgentRunRow.next_attempt_at <= moment,
            AgentRunRow.status.in_(
                [RunStatus.PENDING.value, RunStatus.RUNNING.value, RunStatus.FAILED.value]
            ),
        )
        if project_id is not None:
            statement = statement.where(AgentRunRow.project_id == str(project_id))

        for row in self._session.scalars(statement.order_by(AgentRunRow.created_at)).all():
            running = row.status == RunStatus.RUNNING.value
            if running and (
                row.lease_expires_at is None or as_aware(row.lease_expires_at) > moment
            ):
                continue  # still owned by a live worker

            observed_token = row.lease_token
            claimed = _affected(
                self._session,
                update(AgentRunRow)
                .where(
                    AgentRunRow.agent_run_id == row.agent_run_id,
                    AgentRunRow.lease_token == observed_token,
                )
                .values(
                    status=RunStatus.RUNNING.value,
                    lease_owner=worker_id,
                    lease_token=observed_token + 1,
                    lease_acquired_at=moment,
                    lease_expires_at=expires_at,
                    heartbeat_at=moment,
                    attempt_number=row.attempt_number + 1,
                    started_at=moment,
                    updated_at=moment,
                ),
            )
            if claimed == 1:
                self._session.expire(row)
                reloaded = self._session.get(AgentRunRow, row.agent_run_id)
                assert reloaded is not None
                return _run_to_domain(reloaded)
        return None

    def heartbeat(self, run: AgentRun, moment: datetime, lease_seconds: int) -> bool:
        """Extend the lease, or return ``False`` if this worker no longer owns it.

        A ``False`` here means another worker has reclaimed the run. The caller
        must stop working immediately rather than finishing the step, because
        anything it writes afterwards would be rejected by fencing anyway.
        """

        if run.lease is None:
            return False
        return (
            _affected(
                self._session,
                _fenced(run).values(
                    heartbeat_at=moment,
                    lease_expires_at=moment + timedelta(seconds=lease_seconds),
                    updated_at=moment,
                ),
            )
            == 1
        )

    def save_fenced(self, run: AgentRun, moment: datetime) -> bool:
        """Persist a run mutation only if this worker still owns the lease.

        Returns ``False`` rather than raising: losing a lease is an expected
        outcome of the protocol, not an error condition.
        """

        if run.lease is None:
            return False
        return (
            _affected(
                self._session,
                _fenced(run).values(
                    status=run.status.value,
                    attempt_number=run.attempt_number,
                    input_context=run.input_context or {},
                    output_summary=run.output_summary or {},
                    continuation_state=run.continuation_state or {},
                    started_at=run.started_at,
                    completed_at=run.completed_at,
                    failed_at=run.failed_at,
                    error_code=run.error_code,
                    error_message=run.error_message,
                    next_attempt_at=run.next_attempt_at or moment,
                    updated_at=moment,
                ),
            )
            == 1
        )

    def release(self, run: AgentRun, moment: datetime) -> bool:
        """Give up the lease without changing the run's outcome.

        Graceful shutdown: the run becomes immediately claimable rather than
        waiting out its expiry.
        """

        if run.lease is None:
            return False
        return (
            _affected(
                self._session,
                _fenced(run).values(
                    lease_expires_at=moment, heartbeat_at=moment, updated_at=moment
                ),
            )
            == 1
        )

    def list_resumable(self, project_id: ProjectId) -> tuple[AgentRun, ...]:
        """Return runs another worker may continue."""

        rows = self._session.scalars(
            select(AgentRunRow)
            .where(
                AgentRunRow.project_id == str(project_id),
                AgentRunRow.status.in_([RunStatus.INTERRUPTED.value, RunStatus.FAILED.value]),
            )
            .order_by(AgentRunRow.created_at)
        ).all()
        return tuple(_run_to_domain(row) for row in rows)


class ProvenanceLinkRepository:
    """Persistence boundary for knowledge provenance links."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, link: ProvenanceLink) -> None:
        """Persist a provenance link.

        A link recording how a statement came to exist must name the kind of
        source it came from: ADR-0008 makes readiness derive from that, and the
        column sat `NULL` for 4,136 rows because nothing refused to write one
        without it (`D-105`).

        Enforced here rather than in the domain invariant on purpose. Databases
        written before this rule hold `NULL`, and a read-side invariant would
        turn an unfed column into a failure to open a knowledge item.
        """

        if link.link_type in PRODUCING_LINK_TYPES and link.source_type is None:
            raise DomainInvariantError(f"a {link.link_type.value} link must name its source type")
        self._session.add(
            ProvenanceLinkRow(
                provenance_link_id=str(link.id),
                project_id=str(link.project_id),
                knowledge_item_id=str(link.knowledge_item_id),
                knowledge_version_number=link.knowledge_version_number,
                agent_run_id=str(link.agent_run_id) if link.agent_run_id else None,
                message_id=str(link.message_id) if link.message_id else None,
                link_type=link.link_type.value,
                source_type=link.source_type.value if link.source_type else None,
                source_reference=link.source_reference,
                created_at=link.created_at,
            )
        )

    def list_for_item(self, item_id: KnowledgeItemId) -> tuple[ProvenanceLink, ...]:
        """Return every link recorded for a knowledge item."""

        rows = self._session.scalars(
            select(ProvenanceLinkRow)
            .where(ProvenanceLinkRow.knowledge_item_id == str(item_id))
            .order_by(ProvenanceLinkRow.created_at)
        ).all()
        return tuple(_link_to_domain(row) for row in rows)

    def list_for_run(self, run_id: AgentRunId) -> tuple[ProvenanceLink, ...]:
        """Return every link recorded for an agent run."""

        rows = self._session.scalars(
            select(ProvenanceLinkRow)
            .where(ProvenanceLinkRow.agent_run_id == str(run_id))
            .order_by(ProvenanceLinkRow.created_at)
        ).all()
        return tuple(_link_to_domain(row) for row in rows)

    def items_produced_by(self, run_id: AgentRunId) -> tuple[KnowledgeItemId, ...]:
        """Return the knowledge a run produced."""

        return self._items_by_link_type(run_id, ProvenanceLinkType.PRODUCED_BY)

    def items_used_by(self, run_id: AgentRunId) -> tuple[KnowledgeItemId, ...]:
        """Return the knowledge a run consumed."""

        return self._items_by_link_type(run_id, ProvenanceLinkType.USED_BY)

    def _items_by_link_type(
        self, run_id: AgentRunId, link_type: ProvenanceLinkType
    ) -> tuple[KnowledgeItemId, ...]:
        rows = self._session.scalars(
            select(ProvenanceLinkRow.knowledge_item_id)
            .where(
                ProvenanceLinkRow.agent_run_id == str(run_id),
                ProvenanceLinkRow.link_type == link_type.value,
            )
            .order_by(ProvenanceLinkRow.created_at)
        ).all()
        return tuple(KnowledgeItemId(value) for value in rows)


def _affected(session: DbSession, statement: Any) -> int:
    """Execute an UPDATE and return how many rows it changed.

    ``rowcount`` lives on ``CursorResult``; ``Session.execute`` is typed as the
    wider ``Result``. Narrowing once here keeps every fenced call site readable.
    """

    return int(cast("Any", session.execute(statement)).rowcount)


def _fenced(run: AgentRun) -> Any:
    """Return an update fenced on owner, token, and an unexpired lease.

    Every ownership-bearing mutation goes through here. A worker whose token has
    been superseded matches zero rows and therefore cannot overwrite the newer
    owner's work, even if it recovers mid-step.
    """

    assert run.lease is not None
    return update(AgentRunRow).where(
        AgentRunRow.agent_run_id == str(run.id),
        AgentRunRow.lease_owner == run.lease.owner,
        AgentRunRow.lease_token == run.lease.token,
        AgentRunRow.lease_expires_at > run.lease.heartbeat_at,
    )


def _project_to_domain(row: ProjectRow) -> Project:
    return Project(
        id=ProjectId(row.project_id),
        name=row.name,
        key=row.project_key,
        description=row.description,
        status=ProjectStatus(row.status),
        knowledge_revision=row.knowledge_revision,
    )


def _session_to_domain(row: SessionRow) -> Session:
    return Session(
        id=SessionId(row.session_id),
        project_id=ProjectId(row.project_id),
        type=SessionType(row.session_type),
        started_at=as_aware(row.started_at),
        status=SessionStatus(row.status),
        ended_at=as_aware(row.ended_at) if row.ended_at is not None else None,
    )


def _message_to_domain(row: MessageRow) -> Message:
    return Message(
        id=MessageId(row.message_id),
        project_id=ProjectId(row.project_id),
        session_id=SessionId(row.session_id),
        sequence_number=row.sequence_number,
        actor_type=ActorType(row.actor_type),
        message_type=MessageType(row.message_type),
        content=row.content,
        created_at=as_aware(row.created_at),
        actor_id=row.actor_id,
        agent_run_id=AgentRunId(row.agent_run_id) if row.agent_run_id else None,
        idempotency_key=row.idempotency_key,
        metadata=dict(row.message_metadata or {}),
        # NULL means the row predates EM-2, and those messages were project
        # input. An unrecognised value is *not* treated the same way: it means a
        # caller declared something this version does not understand, and
        # guessing "interpret it" would extract from a message somebody
        # deliberately marked.
        purpose=_purpose_of(row.purpose),
    )


def _purpose_of(stored: str | None) -> MessagePurpose:
    if stored is None:
        return MessagePurpose.PROJECT_INPUT
    try:
        return MessagePurpose(stored)
    except ValueError:
        return MessagePurpose.CONVERSATION_CONTROL


def _run_to_domain(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        id=AgentRunId(row.agent_run_id),
        project_id=ProjectId(row.project_id),
        role=AgentRole(row.agent_role),
        idempotency_key=row.idempotency_key,
        status=RunStatus(row.status),
        session_id=SessionId(row.session_id) if row.session_id else None,
        attempt_number=row.attempt_number,
        input_context=dict(row.input_context or {}),
        output_summary=dict(row.output_summary or {}),
        continuation_state=dict(row.continuation_state or {}),
        started_at=as_aware(row.started_at) if row.started_at is not None else None,
        completed_at=as_aware(row.completed_at) if row.completed_at is not None else None,
        failed_at=as_aware(row.failed_at) if row.failed_at is not None else None,
        error_code=row.error_code,
        error_message=row.error_message,
        lease=_lease_to_domain(row),
        next_attempt_at=as_aware(row.next_attempt_at) if row.next_attempt_at else None,
    )


def _lease_to_domain(row: AgentRunRow) -> Lease | None:
    if row.lease_owner is None or row.lease_acquired_at is None or row.lease_expires_at is None:
        return None
    return Lease(
        owner=row.lease_owner,
        token=row.lease_token,
        acquired_at=as_aware(row.lease_acquired_at),
        expires_at=as_aware(row.lease_expires_at),
        heartbeat_at=as_aware(row.heartbeat_at)
        if row.heartbeat_at
        else as_aware(row.lease_acquired_at),
    )


def _link_to_domain(row: ProvenanceLinkRow) -> ProvenanceLink:
    return ProvenanceLink(
        id=ProvenanceLinkId(row.provenance_link_id),
        project_id=ProjectId(row.project_id),
        knowledge_item_id=KnowledgeItemId(row.knowledge_item_id),
        link_type=ProvenanceLinkType(row.link_type),
        created_at=as_aware(row.created_at),
        knowledge_version_number=row.knowledge_version_number,
        agent_run_id=AgentRunId(row.agent_run_id) if row.agent_run_id else None,
        message_id=MessageId(row.message_id) if row.message_id else None,
        source_type=KnowledgeSourceType(row.source_type) if row.source_type else None,
        source_reference=row.source_reference,
    )


__all__: Sequence[str] = [
    "AgentRunRepository",
    "MessageRepository",
    "ProjectRepository",
    "ProvenanceLinkRepository",
    "SessionRepository",
]
