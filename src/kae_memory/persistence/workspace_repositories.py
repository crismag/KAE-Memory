"""Repositories for projects, sessions, messages, agent runs, and provenance."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import (
    AgentRunId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    ProvenanceLinkId,
    SessionId,
)
from kae_memory.domain.models import Project, ProvenanceLink, ProvenanceLinkType
from kae_memory.domain.workspace import (
    ActorType,
    Message,
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

    def get(self, project_id: ProjectId) -> Project | None:
        """Return a project by identifier, or ``None`` if unknown."""

        row = self._session.get(ProjectRow, str(project_id))
        if row is None:
            return None
        return Project(
            id=ProjectId(row.project_id),
            name=row.name,
            key=row.project_key,
            description=row.description,
            status=ProjectStatus(row.status),
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

    def add(self, message: Message) -> None:
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
                message_metadata={},
                created_at=message.created_at,
            )
        )

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
        """Persist a provenance link."""

        self._session.add(
            ProvenanceLinkRow(
                provenance_link_id=str(link.id),
                project_id=str(link.project_id),
                knowledge_item_id=str(link.knowledge_item_id),
                knowledge_version_number=link.knowledge_version_number,
                agent_run_id=str(link.agent_run_id) if link.agent_run_id else None,
                message_id=str(link.message_id) if link.message_id else None,
                link_type=link.link_type.value,
                source_type=link.source_type,
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
    )


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
        source_type=row.source_type,
        source_reference=row.source_reference,
    )


__all__: Sequence[str] = [
    "AgentRunRepository",
    "MessageRepository",
    "ProjectRepository",
    "ProvenanceLinkRepository",
    "SessionRepository",
]
