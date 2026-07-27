"""Session and message contracts.

Sessions group user-facing work within a project. Messages are immutable
interaction evidence: a correction creates a new message and possibly a new
knowledge version, and never edits history.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import AgentRunId, MessageId, ProjectId, SessionId


class ProjectStatus(StrEnum):
    """Durable project lifecycle."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class SessionType(StrEnum):
    """The kind of work a session represents."""

    DISCOVERY = "discovery"
    ARCHITECTURE = "architecture"
    REVIEW = "review"


class SessionStatus(StrEnum):
    """Whether a session is still accepting work."""

    OPEN = "open"
    CLOSED = "closed"


class ActorType(StrEnum):
    """Who produced a message."""

    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class MessageType(StrEnum):
    """What kind of interaction a message records."""

    INPUT = "input"
    QUESTION = "question"
    ANSWER = "answer"
    PROPOSAL = "proposal"
    CONFIRMATION = "confirmation"
    REVIEW_FINDING = "review_finding"


@dataclass(frozen=True, slots=True)
class Session:
    """A bounded period of work belonging to one project."""

    id: SessionId
    project_id: ProjectId
    type: SessionType
    started_at: datetime
    status: SessionStatus = SessionStatus.OPEN
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            raise DomainInvariantError("session started_at must be timezone-aware")
        if self.ended_at is not None:
            if self.ended_at.tzinfo is None:
                raise DomainInvariantError("session ended_at must be timezone-aware")
            if self.ended_at < self.started_at:
                raise DomainInvariantError("session cannot end before it started")


@dataclass(frozen=True, slots=True)
class Message:
    """Immutable interaction evidence.

    ``content`` is stored verbatim. Extraction never rewrites it, so the original
    wording remains available as the source of any knowledge derived from it.
    """

    id: MessageId
    project_id: ProjectId
    session_id: SessionId
    sequence_number: int
    actor_type: ActorType
    message_type: MessageType
    content: str
    created_at: datetime
    actor_id: str | None = None
    agent_run_id: AgentRunId | None = None

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise DomainInvariantError("message sequence number must be positive")
        if not self.content.strip():
            raise DomainInvariantError("message content must not be empty")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("message created_at must be timezone-aware")
        if self.actor_type is ActorType.AGENT and self.agent_run_id is None:
            raise DomainInvariantError("agent messages must reference the run that produced them")
