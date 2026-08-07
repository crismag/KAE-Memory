"""Session and message contracts.

Sessions group user-facing work within a project. Messages are immutable
interaction evidence: a correction creates a new message and possibly a new
knowledge version, and never edits history.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

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


class MessagePurpose(StrEnum):
    """What the caller says a message is *for*, declared before interpretation.

    Distinct from `ObservationClass`, which is what a span turns out to *be*
    once classified. This is an input and that is an outcome, and conflating
    them would mean asking a model whether a connectivity check was a
    connectivity check.

    The problem it solves: recording a message enqueues discovery extraction,
    unconditionally. A browser suite proving the round trip works therefore
    wrote twelve copies of one test sentence into a project's candidate
    knowledge, and nothing in the system could have known not to. There was no
    way to say "store this, do not interpret it".

    **Deliberately three.** More values would need someone to choose between
    them correctly under time pressure, and the only distinction that changes
    behaviour is whether this is the project speaking.
    """

    PROJECT_INPUT = "project_input"
    """Somebody talking about the project. Interpreted. **The default**, because
    any other default silently stops interpreting real conversations — a failure
    that looks like extraction being broken."""

    DIAGNOSTIC = "diagnostic"
    """A health check, a round-trip proof, a deployment smoke test. Stored,
    attributed, and never interpreted."""

    CONVERSATION_CONTROL = "conversation_control"
    """Steering rather than content — "start over", "go back to the last
    question". Real to the transcript, not a claim about the project."""


#: Purposes whose messages reach extraction. One entry, and that is the point:
#: a reader can see at a glance what is interpreted, rather than reconstructing
#: it from a chain of negations.
INTERPRETED_PURPOSES: frozenset[MessagePurpose] = frozenset({MessagePurpose.PROJECT_INPUT})


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

    ``metadata`` carries structure *about* the message — which finding a question
    concerns, which question an answer replies to — and never anything that
    belongs in the content. Keeping the two apart is what lets the verbatim text
    stay verbatim while a clarification still knows what it is about.
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
    idempotency_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    purpose: MessagePurpose = MessagePurpose.PROJECT_INPUT
    """Why this was recorded. See `MessagePurpose`.

    Defaulted rather than required, unlike most fields here, because every
    message written before this existed was project input and saying so is
    accurate rather than convenient.
    """

    @property
    def is_interpreted(self) -> bool:
        """Whether extraction should read this message.

        A property rather than a check at each call site: there are three
        callers today and the answer must not be able to differ between them.
        """

        return self.purpose in INTERPRETED_PURPOSES

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise DomainInvariantError("message sequence number must be positive")
        if not self.content.strip():
            raise DomainInvariantError("message content must not be empty")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("message created_at must be timezone-aware")
        if self.actor_type is ActorType.AGENT and not (self.agent_run_id or self.actor_id):
            # An agent's output must be attributable to something. Usually that
            # is the run that produced it; for an agent working through MCP the
            # run happened outside this system, so the named actor carries the
            # accountability instead. What is refused is an agent message that
            # names neither — the alternative to which was labelling it USER and
            # putting model output under the actor type reserved for a person.
            raise DomainInvariantError(
                "agent messages must name the run that produced them, or the external actor"
            )
