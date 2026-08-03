"""Clarification — turning a gap into a question, and an answer into candidates.

Readiness already knows what is missing and the review service already says what
to do about it. What did not exist was the loop that closes: asking a person,
recording what they said verbatim, and feeding it back through the same
extraction path everything else uses.

Two rules shape the design.

**Findings have no identity.** They are derived from current state and recomputed
on every read, so a question cannot reference one by key — the finding it was
asked about may not exist by the time it is answered, which is exactly what
happens when the answer resolves it. A question therefore records its *subject*:
the area, the kind of gap, the knowledge it concerned. That survives
recalculation, and it is what lets a later reader see which questions a finding
already provoked.

**An answer is evidence, not knowledge.** It is stored verbatim and handed to the
requirements agent like any other input, so what it produces is a candidate a
human still confirms. Nothing here writes knowledge directly; a clarification
loop that confirmed its own answers would be a way to launder a guess into the
record.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import AgentRunId, MessageId, ProjectId, SessionId
from kae_memory.domain.workspace import ActorType, Message, MessageType, SessionType
from kae_memory.persistence.transactions import RetryPolicy

from .memory_service import MemoryService
from .review_service import Finding, ReviewService, Severity

ASKS_ABOUT = "asks_about"
"""Metadata key naming what a question concerns."""

ANSWERS = "answers_message_id"
"""Metadata key linking an answer back to its question."""


@dataclass(frozen=True, slots=True)
class Clarification:
    """One question worth asking, derived from a finding."""

    question: str
    finding_kind: str
    severity: str
    area_key: str | None = None
    knowledge_ids: tuple[str, ...] = ()

    @property
    def subject(self) -> dict[str, object]:
        """Return the durable description of what this question is about."""

        return {
            "finding_kind": self.finding_kind,
            "severity": self.severity,
            "area_key": self.area_key,
            "knowledge_ids": list(self.knowledge_ids),
        }


@dataclass(frozen=True, slots=True)
class AnsweredClarification:
    """An answer, and the run that will read it."""

    question: Message
    answer: Message
    run_id: AgentRunId


class ClarificationService:
    """Derives questions from findings and routes answers back into extraction."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        memory: MemoryService | None = None,
        review: ReviewService | None = None,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._memory = memory or MemoryService(session_factory, policy)
        self._review = review or ReviewService(session_factory, policy)
        self._clock = clock

    def pending(self, project_id: ProjectId) -> tuple[Clarification, ...]:
        """Return the questions this project's current findings justify asking.

        Most severe first, following the review service's own ordering. A
        finding whose recommended action is not a question — "confirm or reject
        each candidate" is work, not an unknown — is excluded, because asking a
        person something they cannot answer wastes the one resource this loop
        exists to spend carefully.
        """

        return tuple(
            _as_clarification(finding)
            for finding in self._review.findings(project_id)
            if _is_askable(finding)
        )

    def ask(
        self,
        project_id: ProjectId,
        clarification: Clarification,
        session_id: SessionId | None = None,
        idempotency_key: str | None = None,
    ) -> Message:
        """Record a question, with what it is about held apart from its text.

        The subject lives in metadata rather than in the content so the content
        stays exactly what a person will read and answer.
        """

        working_session = (
            session_id or self._memory.open_session(project_id, SessionType.DISCOVERY).id
        )
        record = self._memory.record_message(
            project_id,
            working_session,
            content=clarification.question,
            # SYSTEM, not AGENT: an agent message must name the run that
            # produced it, and this question was derived from findings by
            # deterministic application logic with no run behind it.
            actor_type=ActorType.SYSTEM,
            message_type=MessageType.QUESTION,
            idempotency_key=idempotency_key or _question_key(clarification),
            metadata={ASKS_ABOUT: clarification.subject},
        )
        return record.message

    def answer(
        self,
        project_id: ProjectId,
        question_id: MessageId,
        text: str,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AnsweredClarification:
        """Record an answer verbatim and enqueue extraction over it.

        The answer goes through the requirements agent like any other input, so
        what it yields is a candidate a human confirms. Routing it anywhere else
        would let this loop write knowledge on a person's behalf.
        """

        question = self._memory.get_message(question_id)
        if question is None:
            raise LookupError(f"unknown question: {question_id}")
        if question.message_type is not MessageType.QUESTION:
            raise ValueError(f"message {question_id} is not a question")
        if not text.strip():
            raise ValueError("an answer must not be empty")

        key = idempotency_key or f"answer:{question_id}"
        record = self._memory.record_message(
            project_id,
            question.session_id,
            content=text,
            actor_type=ActorType.USER,
            message_type=MessageType.ANSWER,
            actor_id=actor_id,
            idempotency_key=key,
            metadata={
                ANSWERS: str(question_id),
                # Carried forward so the subject survives on the answer even
                # once the finding that prompted it has been resolved away.
                ASKS_ABOUT: dict(question.metadata.get(ASKS_ABOUT, {})),
            },
        )
        run = self._memory.enqueue_run(
            project_id,
            AgentRole.REQUIREMENTS,
            idempotency_key=f"extract:{key}",
            session_id=question.session_id,
            input_context={
                "message_id": str(record.message.id),
                "answers_question": str(question_id),
            },
        )
        return AnsweredClarification(question=question, answer=record.message, run_id=run.id)

    def asked(self, project_id: ProjectId, session_id: SessionId) -> tuple[Message, ...]:
        """Return the questions asked in a session, oldest first."""

        return tuple(
            message
            for message in self._memory.messages_for_session(session_id)
            if message.message_type is MessageType.QUESTION
        )

    def unanswered(self, project_id: ProjectId, session_id: SessionId) -> tuple[Message, ...]:
        """Return questions with no answer recorded against them."""

        messages = self._memory.messages_for_session(session_id)
        answered = {
            str(message.metadata.get(ANSWERS))
            for message in messages
            if message.message_type is MessageType.ANSWER
        }
        return tuple(
            message
            for message in messages
            if message.message_type is MessageType.QUESTION and str(message.id) not in answered
        )


_ASKABLE = {"missing_area", "partial_area", "open_question", "open_blocker"}
"""Finding kinds that describe something a person can answer.

Excluded on purpose: ``unconfirmed_knowledge`` and ``unclassified_knowledge``
are queues of work, and ``duplicate_knowledge`` and
``unresolved_contradiction`` are choices between statements already recorded.
None of them is a gap in what the project knows.
"""


def _is_askable(finding: Finding) -> bool:
    return finding.kind.value in _ASKABLE


def _as_clarification(finding: Finding) -> Clarification:
    return Clarification(
        question=finding.recommended_action,
        finding_kind=finding.kind.value,
        severity=finding.severity.value
        if isinstance(finding.severity, Severity)
        else str(finding.severity),
        area_key=finding.area_key,
        knowledge_ids=tuple(str(item) for item in finding.knowledge_item_ids),
    )


def _question_key(clarification: Clarification) -> str:
    """Return a stable key so re-deriving the same question does not re-ask it.

    Keyed on the subject rather than the wording: rephrasing a prompt should not
    make a project ask the same person the same thing twice.
    """

    parts = [
        "question",
        clarification.finding_kind,
        clarification.area_key or "-",
        ",".join(sorted(clarification.knowledge_ids)) or "-",
    ]
    return ":".join(parts)


def questions_for(findings: Sequence[Finding]) -> tuple[Clarification, ...]:
    """Return the askable subset of ``findings`` as clarifications."""

    return tuple(_as_clarification(f) for f in findings if _is_askable(f))


__all__ = [
    "ANSWERS",
    "ASKS_ABOUT",
    "AnsweredClarification",
    "Clarification",
    "ClarificationService",
    "questions_for",
]
