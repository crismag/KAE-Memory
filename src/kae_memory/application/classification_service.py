"""Classifying a submitted observation and routing what it found (T24).

> Preserve the submission exactly. Derive beside it, never over it.

The observation stays in `messages` as it was submitted. Everything here is a
record *alongside* it, pointing back with a real span, a classifier version,
and a confidence.

Three rules run through the whole module:

**Classification is not confirmation.** A `requirement` at 0.99 is a proposal.
Confidence describes certainty about the *type* of a statement, never the truth
of it (FR-005).

**A milestone is never completed because a sentence said so.** A reported
completion creates a proposed transition carrying what was claimed, what is
current, and who claimed it. Only authoritative execution evidence settles one.

**Failure never blocks submission.** If classification cannot run, the
observation persists and the response says classification did not happen.
Evidence capture must not depend on anything being reachable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from hashlib import sha256

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.agents.observation_classifier import (
    DeterministicObservationClassifier,
    ObservationClassifier,
)
from kae_memory.domain.identifiers import MessageId, ProjectId
from kae_memory.domain.observation import (
    ACTIVE_STATES,
    ClassifiedSpan,
    ObservationClass,
    OperationalState,
    RetentionTier,
    Route,
    TransitionAuthority,
    is_verified_result,
)
from kae_memory.persistence.classification_repository import (
    ClassificationRepository,
    OperationalUpdateRepository,
)
from kae_memory.persistence.transactions import run_transaction

OPERATIONAL_KIND: dict[ObservationClass, str] = {
    ObservationClass.MILESTONE_STATUS: "milestone_transition",
    ObservationClass.TASK: "task",
    ObservationClass.CHECK_IN: "check_in",
    ObservationClass.DEADLINE: "deadline",
    ObservationClass.BLOCKER: "blocker",
    ObservationClass.TEST_RESULT: "test_result",
    ObservationClass.DEFECT: "defect",
    ObservationClass.RISK: "risk",
    ObservationClass.PROGRESS_UPDATE: "progress_update",
    ObservationClass.OWNERSHIP_UPDATE: "ownership_update",
}
"""Which operational record each class produces. A class absent from here
produces none, which is why durable and evidence classes are absent."""


@dataclass(frozen=True, slots=True)
class ClassificationOutcome:
    """What classifying one observation produced.

    ``failed`` is a first-class outcome rather than an exception, because a
    caller has to be able to tell "nothing was found" from "nothing ran". The
    two look identical in an empty list and mean opposite things.
    """

    message_id: str
    classifier: str
    classifier_version: str
    semantic: bool
    spans: tuple[ClassifiedSpan, ...] = ()
    operational_ids: tuple[str, ...] = ()
    replayed: bool = False
    failed: bool = False
    failure_reason: str | None = None
    hint: str | None = None
    hint_agreed: bool | None = None

    @property
    def unclassified_spans(self) -> tuple[ClassifiedSpan, ...]:
        return tuple(
            span for span in self.spans if span.classification is ObservationClass.UNCLASSIFIED
        )

    def by_tier(self, tier: RetentionTier) -> tuple[ClassifiedSpan, ...]:
        return tuple(span for span in self.spans if span.tier is tier)


@dataclass(frozen=True, slots=True)
class OperationalRecord:
    """One operational fact, as read back for a briefing."""

    operational_update_id: str
    kind: str
    subject: str | None
    reported_status: str | None
    current_status: str | None
    transition_type: str | None
    authority: str
    state: str
    verification: str | None
    effective_date: str | None
    date_role: str | None
    detail: dict[str, object] = field(default_factory=dict)


class ClassificationService:
    """Classify observations and route what classification found."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        classifier: ObservationClassifier | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._classifier = classifier or DeterministicObservationClassifier()

    @property
    def classifier_name(self) -> str:
        return self._classifier.name

    @property
    def classifier_version(self) -> str:
        return self._classifier.version

    @property
    def semantic(self) -> bool:
        return self._classifier.semantic

    def classify(
        self,
        project_id: ProjectId,
        message_id: MessageId,
        text: str,
        hint: str | None = None,
    ) -> ClassificationOutcome:
        """Classify one observation, recording spans and operational records.

        Idempotent by observation, classifier, version, and span — enforced by
        the unique index rather than by a lookup first, because a lookup
        before an insert races.
        """

        try:
            spans = self._classifier.classify(text)
        except Exception as error:
            return ClassificationOutcome(
                message_id=str(message_id),
                classifier=self._classifier.name,
                classifier_version=self._classifier.version,
                semantic=self._classifier.semantic,
                failed=True,
                failure_reason=type(error).__name__,
                hint=hint,
            )

        existing = self._existing(message_id)
        if existing:
            return ClassificationOutcome(
                message_id=str(message_id),
                classifier=self._classifier.name,
                classifier_version=self._classifier.version,
                semantic=self._classifier.semantic,
                spans=spans,
                replayed=True,
                hint=hint,
                hint_agreed=_hint_agreed(hint, spans),
            )

        operational_ids = self._persist(project_id, message_id, spans)
        return ClassificationOutcome(
            message_id=str(message_id),
            classifier=self._classifier.name,
            classifier_version=self._classifier.version,
            semantic=self._classifier.semantic,
            spans=spans,
            operational_ids=operational_ids,
            hint=hint,
            hint_agreed=_hint_agreed(hint, spans),
        )

    def _existing(self, message_id: MessageId) -> bool:
        def operation(session: DbSession) -> bool:
            rows = ClassificationRepository(session).for_message(
                message_id, self._classifier.version
            )
            return bool(rows)

        return run_transaction(self._session_factory, operation)

    def _persist(
        self, project_id: ProjectId, message_id: MessageId, spans: Sequence[ClassifiedSpan]
    ) -> tuple[str, ...]:
        def operation(session: DbSession) -> tuple[str, ...]:
            classifications = ClassificationRepository(session)
            produced: list[str] = []

            for span in spans:
                row = classifications.add_span(
                    project_id,
                    message_id,
                    span,
                    self._classifier.name,
                    self._classifier.version,
                    self._classifier.semantic,
                )
                if span.route is not Route.OPERATIONAL_UPDATE:
                    continue
                session.flush()
                record = self._operational_record(
                    session, project_id, message_id, span, row.classification_id
                )
                if record is not None:
                    produced.append(record)
            return tuple(produced)

        return run_transaction(self._session_factory, operation)

    def _operational_record(
        self,
        session: DbSession,
        project_id: ProjectId,
        message_id: MessageId,
        span: ClassifiedSpan,
        classification_id: str,
    ) -> str | None:
        """Write the operational record a routed span implies."""

        kind = OPERATIONAL_KIND.get(span.classification)
        if kind is None:
            return None

        repository = OperationalUpdateRepository(session)
        subject = _subject(span)
        fields = span.fields
        reported = _reported_status(span)

        current = repository.latest_status(project_id, subject) if subject else None
        transition_type = _transition_type(current, reported)

        # Deterministic, so a replay of the same span produces the same key and
        # the unique index — not a lookup — is what stops the second write.
        digest = sha256(
            f"{message_id}|{classification_id}|{span.span.start}|{span.span.end}".encode()
        ).hexdigest()[:32]

        verification = (
            is_verified_result(False)
            if span.classification is ObservationClass.TEST_RESULT
            else None
        )

        row = repository.add(
            project_id=project_id,
            message_id=message_id,
            kind=kind,
            # A sentence is a report. Nothing an observation carries is
            # execution evidence, so nothing submitted here can auto-confirm.
            authority=TransitionAuthority.AGENT_REPORTED.value,
            state=OperationalState.PROPOSED.value,
            idempotency_key=f"classified-{digest}",
            classification_id=classification_id,
            subject=subject,
            reported_status=reported,
            current_status=current,
            transition_type=transition_type,
            verification=verification,
            effective_date=(fields.get("dates") or [None])[0],
            date_role=fields.get("date_role"),
            detail={"text": span.normalized_text, "confidence": span.confidence},
        )
        return str(row.operational_update_id)

    def operational_state(
        self, project_id: ProjectId, states: Sequence[str] | None = None
    ) -> tuple[OperationalRecord, ...]:
        """Return what a briefing may show as the current state of the work."""

        wanted = list(states or [state.value for state in ACTIVE_STATES])

        def operation(session: DbSession) -> tuple[OperationalRecord, ...]:
            rows = OperationalUpdateRepository(session).active(project_id, wanted)
            return tuple(
                OperationalRecord(
                    operational_update_id=str(row.operational_update_id),
                    kind=row.kind,
                    subject=row.subject,
                    reported_status=row.reported_status,
                    current_status=row.current_status,
                    transition_type=row.transition_type,
                    authority=row.authority,
                    state=row.state,
                    verification=row.verification,
                    effective_date=row.effective_date,
                    date_role=row.date_role,
                    detail=dict(row.detail or {}),
                )
                for row in rows
            )

        return run_transaction(self._session_factory, operation)

    def classifications(
        self, project_id: ProjectId, tiers: Sequence[RetentionTier] | None = None
    ) -> tuple[dict[str, object], ...]:
        """Return a project's classified spans, newest first."""

        def operation(session: DbSession) -> tuple[dict[str, object], ...]:
            rows = ClassificationRepository(session).for_project(project_id, tiers)
            return tuple(
                {
                    "classification_id": str(row.classification_id),
                    "message_id": str(row.message_id),
                    "classification": row.classification,
                    "retention_tier": row.retention_tier,
                    "route": row.route,
                    "confidence": row.confidence,
                    "review_required": row.review_required,
                    "span": {"start": row.span_start, "end": row.span_end},
                    "normalized_text": row.normalized_text,
                    "fields": dict(row.extracted_fields or {}),
                }
                for row in rows
            )

        return run_transaction(self._session_factory, operation)


def _subject(span: ClassifiedSpan) -> str | None:
    """What an operational record is about.

    A milestone id if one was found, then a target id. Without either there is
    no subject, and a record with no subject is still worth keeping — it just
    cannot be compared against a previous status.
    """

    for key in ("milestones", "targets"):
        values = span.fields.get(key)
        if values:
            return str(values[0])
    return None


def _reported_status(span: ClassifiedSpan) -> str | None:
    statuses = span.fields.get("statuses")
    return str(statuses[0]) if statuses else None


def _transition_type(current: str | None, reported: str | None) -> str | None:
    """Tell an ordinary transition from a contradiction.

    Not every change is a conflict. `in_progress -> complete` is the expected
    shape of work finishing; `complete -> in_progress` is someone disagreeing
    with a record, and only the second belongs anywhere near the contradiction
    machinery that gates readiness.
    """

    if reported is None:
        return None
    if current is None:
        return "initial"
    if current == reported:
        return "restatement"
    if current == "complete" and reported != "complete":
        return "regression"
    return "progression"


def _hint_agreed(hint: str | None, spans: Sequence[ClassifiedSpan]) -> bool | None:
    """Whether a caller's `classification_hint` matched what was found (T24.5).

    The hint is recorded and compared, never obeyed. A caller asserting
    "requirement" over a greeting would otherwise route the greeting, and a
    parameter that can override the classifier is a parameter that turns the
    taxonomy into a suggestion.
    """

    if not hint:
        return None
    normalised = hint.strip().lower()
    return any(span.classification.value == normalised for span in spans)
