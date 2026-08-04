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
from enum import StrEnum

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.errors import AlreadyAnsweredError, IdempotencyConflictError
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import AgentRunId, MessageId, ProjectId, SessionId
from kae_memory.domain.lifecycle import LifecycleState
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


class ClarificationState(StrEnum):
    """Where one clarification has reached in the loop.

    Derived from the records themselves — the question, the answer, the run,
    and what the run produced — rather than tracked in a column beside them. A
    stored state would be a second source of truth able to disagree with the
    first, and the disagreement would be invisible.

    The states exist because a caller must not have to infer progress from
    unrelated fields, and because each transition is a real thing that has or
    has not happened yet.
    """

    WAITING_FOR_ANSWER = "waiting_for_answer"
    WAITING_FOR_EXTRACTION = "waiting_for_extraction"
    EXTRACTING = "extracting"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    EXTRACTION_FAILED = "extraction_failed"
    """Terminal for now: the answer stands, and nothing was extracted from it."""


@dataclass(frozen=True, slots=True)
class ClarificationProgress:
    """One clarification's position in the loop, and what it has produced."""

    question_id: MessageId
    state: ClarificationState
    answer_id: MessageId | None = None
    extraction_run_id: AgentRunId | None = None
    run_status: str | None = None
    proposed_knowledge_ids: tuple[str, ...] = ()
    validated_knowledge_ids: tuple[str, ...] = ()

    @property
    def knowledge_changed(self) -> bool:
        """Whether anything a person confirmed came out of this."""

        return bool(self.validated_knowledge_ids)


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    """A materialised question a person can actually answer.

    Distinct from :class:`Clarification`, which is derived from a finding and
    has no identity. A caller cannot answer something with no id, so this pairs
    the derived subject with the durable message that carries it.
    """

    id: MessageId
    question: str
    finding_kind: str
    severity: str
    asked_at: datetime
    area_key: str | None = None
    knowledge_ids: tuple[str, ...] = ()
    newly_asked: bool = False
    """Whether this call created the question rather than finding it already asked."""


@dataclass(frozen=True, slots=True)
class AnsweredClarification:
    """An answer, and the run that will read it.

    ``run_id`` names work that has been *scheduled*. Nothing has been extracted
    when this is returned, and no knowledge has changed — the answer is
    evidence, and what it yields is a candidate a person still confirms.
    """

    question: Message
    answer: Message
    run_id: AgentRunId
    replayed: bool = False
    """Whether this returns an answer already recorded rather than a new one."""


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

    def _owned_question(self, project_id: ProjectId, question_id: MessageId) -> Message:
        """Return the question, or refuse if it belongs to another project.

        Enforced here rather than in the caller. Without it, answering another
        project's question recorded the answer against *that* project's session
        while claiming this project's id — a cross-project write, not merely a
        read leak.
        """

        question = self._memory.get_message(question_id)
        if question is None or question.project_id != project_id:
            raise LookupError(f"unknown question in this project: {question_id}")
        if question.message_type is not MessageType.QUESTION:
            raise ValueError(f"message {question_id} is not a question")
        return question

    def open_questions(
        self, project_id: ProjectId, session_id: SessionId | None = None, limit: int | None = None
    ) -> tuple[OpenQuestion, ...]:
        """Return answerable questions, materialising any not yet asked.

        This writes, and the name of the MCP tool over it should not hide that.
        Derived clarifications have no identity, so a read that returned them
        would hand back questions nothing could answer; materialising is the
        only way to give a caller something addressable.

        Safe to call repeatedly. Questions are keyed on their subject, so
        re-deriving one already asked returns the existing message rather than
        asking a person the same thing twice.
        """

        already = {
            str(message.metadata.get(ANSWERS))
            for message in self._all_messages(project_id)
            if message.message_type is MessageType.ANSWER
        }

        found: list[OpenQuestion] = []
        for clarification in self.pending(project_id):
            question, created = self._materialise(project_id, clarification, session_id)
            if str(question.id) in already:
                continue
            found.append(
                OpenQuestion(
                    id=question.id,
                    question=question.content,
                    finding_kind=clarification.finding_kind,
                    severity=clarification.severity,
                    asked_at=question.created_at,
                    area_key=clarification.area_key,
                    knowledge_ids=clarification.knowledge_ids,
                    newly_asked=created,
                )
            )
        return tuple(found[:limit] if limit is not None else found)

    def _materialise(
        self,
        project_id: ProjectId,
        clarification: Clarification,
        session_id: SessionId | None,
    ) -> tuple[Message, bool]:
        """Return the durable question for ``clarification``, asking if needed.

        The subject key is stable but the wording is not: a finding's
        recommended action can be rephrased, and the message layer treats a
        different payload under the same key as a conflict. Rephrasing must not
        re-ask, so the already-recorded question wins and the conflict resolves
        to it.
        """

        key = _question_key(clarification)
        existing = self._memory.message_by_idempotency_key(project_id, key)
        if existing is not None:
            return existing, False
        try:
            return self.ask(project_id, clarification, session_id=session_id), True
        except IdempotencyConflictError:
            recorded = self._memory.message_by_idempotency_key(project_id, key)
            if recorded is None:  # pragma: no cover - the key just conflicted
                raise
            return recorded, False

    def _all_messages(self, project_id: ProjectId) -> tuple[Message, ...]:
        """Return every message in a project, across its sessions."""

        return tuple(
            message
            for session in self._memory.sessions_for_project(project_id)
            for message in self._memory.messages_for_session(session.id)
        )

    def progress(self, project_id: ProjectId, question_id: MessageId) -> ClarificationProgress:
        """Return where a clarification has reached, from the records.

        Asks the same sources the workflow writes to, so the answer cannot drift
        from what actually happened. Nothing here advances anything.
        """

        question = self._owned_question(project_id, question_id)
        answer = self._existing_answer(question)
        if answer is None:
            return ClarificationProgress(
                question_id=question_id, state=ClarificationState.WAITING_FOR_ANSWER
            )

        key = answer.idempotency_key or f"answer:{question_id}"
        run_id = self._extraction_run_for(project_id, key)
        run = self._memory.get_run(run_id)
        status = run.status.value if run is not None else None

        produced = self._memory.knowledge_produced_by(run_id)
        proposed = tuple(
            str(item.id) for item in produced if item.lifecycle is LifecycleState.PROPOSED
        )
        validated = tuple(
            str(item.id) for item in produced if item.lifecycle is LifecycleState.VALIDATED
        )

        if run is not None and run.status is RunStatus.FAILED:
            state = ClarificationState.EXTRACTION_FAILED
        elif run is not None and run.status is RunStatus.RUNNING:
            state = ClarificationState.EXTRACTING
        elif not produced:
            # Queued, or finished having found nothing worth proposing. Either
            # way no knowledge exists yet, which is what a caller needs to know.
            state = ClarificationState.WAITING_FOR_EXTRACTION
        elif proposed:
            state = ClarificationState.AWAITING_REVIEW
        else:
            state = ClarificationState.COMPLETED

        return ClarificationProgress(
            question_id=question_id,
            state=state,
            answer_id=answer.id,
            extraction_run_id=run_id,
            run_status=status,
            proposed_knowledge_ids=proposed,
            validated_knowledge_ids=validated,
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

        question = self._owned_question(project_id, question_id)
        if not text.strip():
            raise ValueError("an answer must not be empty")

        key = idempotency_key or f"answer:{question_id}"
        recorded = self._existing_answer(question)
        if recorded is not None:
            if recorded.idempotency_key == key:
                return AnsweredClarification(
                    question=question,
                    answer=recorded,
                    run_id=self._extraction_run_for(project_id, key),
                    replayed=True,
                )
            raise AlreadyAnsweredError(
                f"question {question_id} was already answered. A retry of the same "
                "answer is safe; a different one is not, because nothing "
                "downstream could say which the project believes."
            )
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
        return AnsweredClarification(
            question=question, answer=record.message, run_id=run.id, replayed=record.replayed
        )

    def _existing_answer(self, question: Message) -> Message | None:
        """Return the answer already recorded against ``question``, if any."""

        for message in self._memory.messages_for_session(question.session_id):
            if message.message_type is not MessageType.ANSWER:
                continue
            if str(message.metadata.get(ANSWERS)) == str(question.id):
                return message
        return None

    def _extraction_run_for(self, project_id: ProjectId, key: str) -> AgentRunId:
        """Return the extraction run a previous answer enqueued.

        Re-enqueued rather than looked up: ``enqueue_run`` is idempotent on this
        key, so this returns the original run without creating a second one, and
        without this module needing a query it has no other use for.
        """

        return self._memory.enqueue_run(
            project_id, AgentRole.REQUIREMENTS, idempotency_key=f"extract:{key}"
        ).id

    def asked(self, project_id: ProjectId, session_id: SessionId) -> tuple[Message, ...]:
        """Return the questions asked in a session, oldest first.

        ``project_id`` is a filter, not decoration: it was previously accepted
        and ignored, so a caller naming their own project could read another's
        session by knowing its id.
        """

        return tuple(
            message
            for message in self._memory.messages_for_session(session_id)
            if message.message_type is MessageType.QUESTION and message.project_id == project_id
        )

    def unanswered(self, project_id: ProjectId, session_id: SessionId) -> tuple[Message, ...]:
        """Return questions with no answer recorded against them."""

        messages = tuple(
            message
            for message in self._memory.messages_for_session(session_id)
            if message.project_id == project_id
        )
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
    "ClarificationProgress",
    "ClarificationService",
    "ClarificationState",
    "OpenQuestion",
    "questions_for",
]
