"""What a submitted observation was, and where it may go (T24).

> Preserve the submission exactly. Derive beside it, never over it.

An observation is evidence. Classification creates records *alongside* it,
each pointing back at a real span of the stored text with a classifier version
and a confidence. The observation itself is never rewritten, and no
classification here confirms anything: confidence describes the classifier's
certainty about the **type** of a statement, never the truth of it (FR-005).

This taxonomy is deliberately separate from `KnowledgeKind`. That enum says
what a *confirmed statement is* and feeds the readiness denominator; this one
says what a *submitted span was*. Merging them would put `personal_commentary`
into the extraction vocabulary and let a greeting count toward how well a
project is understood.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import DomainInvariantError


class RetentionTier(StrEnum):
    """How long a class of statement matters, and who may settle it.

    The tiers differ in authority as much as in content. Durable knowledge
    needs a person. Operational state may transition on authoritative
    evidence. Evidence needs no confirmation at all, because it is not a claim
    about the project.
    """

    DURABLE = "durable"
    OPERATIONAL = "operational"
    EVIDENCE = "evidence"


class ObservationClass(StrEnum):
    """The classes a span may be assigned.

    Small on purpose. A first implementation with forty overlapping labels is
    a first implementation nobody can review.
    """

    # Durable — a claim about what the project is
    REQUIREMENT = "requirement"
    DECISION = "decision"
    OPEN_QUESTION = "open_question"
    ASSUMPTION = "assumption"
    CONSTRAINT = "constraint"
    SCOPE = "scope"
    QUALITY_ATTRIBUTE = "quality_attribute"
    DOMAIN_FACT = "domain_fact"
    ACCEPTANCE_CRITERION = "acceptance_criterion"
    INTEGRATION = "integration"

    # Operational — a claim about where the work currently stands
    TASK = "task"
    MILESTONE_STATUS = "milestone_status"
    CHECK_IN = "check_in"
    DEADLINE = "deadline"
    BLOCKER = "blocker"
    TEST_RESULT = "test_result"
    DEFECT = "defect"
    RISK = "risk"
    PROGRESS_UPDATE = "progress_update"
    OWNERSHIP_UPDATE = "ownership_update"

    # Evidence — kept, never promoted
    SESSION_NOTE = "session_note"
    PERSONAL_COMMENTARY = "personal_commentary"
    TEMPORARY_NOTE = "temporary_note"
    EXPLORATORY_STATEMENT = "exploratory_statement"
    NOISE = "noise"
    UNCLASSIFIED = "unclassified"


TIER_OF: dict[ObservationClass, RetentionTier] = {
    ObservationClass.REQUIREMENT: RetentionTier.DURABLE,
    ObservationClass.DECISION: RetentionTier.DURABLE,
    ObservationClass.OPEN_QUESTION: RetentionTier.DURABLE,
    ObservationClass.ASSUMPTION: RetentionTier.DURABLE,
    ObservationClass.CONSTRAINT: RetentionTier.DURABLE,
    ObservationClass.SCOPE: RetentionTier.DURABLE,
    ObservationClass.QUALITY_ATTRIBUTE: RetentionTier.DURABLE,
    ObservationClass.DOMAIN_FACT: RetentionTier.DURABLE,
    ObservationClass.ACCEPTANCE_CRITERION: RetentionTier.DURABLE,
    ObservationClass.INTEGRATION: RetentionTier.DURABLE,
    ObservationClass.TASK: RetentionTier.OPERATIONAL,
    ObservationClass.MILESTONE_STATUS: RetentionTier.OPERATIONAL,
    ObservationClass.CHECK_IN: RetentionTier.OPERATIONAL,
    ObservationClass.DEADLINE: RetentionTier.OPERATIONAL,
    ObservationClass.BLOCKER: RetentionTier.OPERATIONAL,
    ObservationClass.TEST_RESULT: RetentionTier.OPERATIONAL,
    ObservationClass.DEFECT: RetentionTier.OPERATIONAL,
    ObservationClass.RISK: RetentionTier.OPERATIONAL,
    ObservationClass.PROGRESS_UPDATE: RetentionTier.OPERATIONAL,
    ObservationClass.OWNERSHIP_UPDATE: RetentionTier.OPERATIONAL,
    ObservationClass.SESSION_NOTE: RetentionTier.EVIDENCE,
    ObservationClass.PERSONAL_COMMENTARY: RetentionTier.EVIDENCE,
    ObservationClass.TEMPORARY_NOTE: RetentionTier.EVIDENCE,
    ObservationClass.EXPLORATORY_STATEMENT: RetentionTier.EVIDENCE,
    ObservationClass.NOISE: RetentionTier.EVIDENCE,
    ObservationClass.UNCLASSIFIED: RetentionTier.EVIDENCE,
}
"""Which tier each class belongs to.

Exhaustive by construction — a class added without a tier fails the check
below at import, rather than silently routing to whichever branch runs last.
"""

if set(TIER_OF) != set(ObservationClass):  # pragma: no cover - import-time guard
    missing = sorted(set(ObservationClass) - set(TIER_OF))
    raise DomainInvariantError(f"observation classes without a retention tier: {missing}")


class Route(StrEnum):
    """Where a classified span goes.

    Never straight into `knowledge_items`. That table feeds readiness, and
    routing commentary into it would inflate coverage with text nobody
    proposed as a requirement.
    """

    KNOWLEDGE_CANDIDATE = "knowledge_candidate"
    OPERATIONAL_UPDATE = "operational_update"
    EVIDENCE_ONLY = "evidence_only"
    NEEDS_REVIEW = "needs_review"


CONFIDENT = 0.90
"""At or above this, a class is acted on without a review flag."""

UNCERTAIN = 0.65
"""Below this, nothing is routed. The span stays unclassified for a person.

Leaving text unclassified is a worse-looking outcome and a better one. A
low-confidence guess that routes is indistinguishable, downstream, from a
confident one.
"""


@dataclass(frozen=True, slots=True)
class Span:
    """A real range of the stored observation text.

    Real, not approximate: a reviewer has to be able to see precisely which
    words produced which candidate, and a span that does not line up with the
    stored text makes every derived record unverifiable.
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < 0:
            raise DomainInvariantError("a span cannot start or end before the text")
        if self.end <= self.start:
            raise DomainInvariantError(f"span {self.start}:{self.end} covers no text")

    def of(self, text: str) -> str:
        """Return the substring this span names, refusing to run past the end."""

        if self.end > len(text):
            raise DomainInvariantError(
                f"span {self.start}:{self.end} runs past text of length {len(text)}"
            )
        return text[self.start : self.end]


@dataclass(frozen=True, slots=True)
class ClassifiedSpan:
    """One span of an observation, classified.

    ``normalized_text`` is a convenience for a reviewer reading a list. It
    never replaces the original, and nothing downstream reads it as the
    statement of record.
    """

    classification: ObservationClass
    confidence: float
    span: Span
    normalized_text: str
    fields: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise DomainInvariantError(f"confidence {self.confidence} is not a probability")

    @property
    def tier(self) -> RetentionTier:
        return TIER_OF[self.classification]

    @property
    def route(self) -> Route:
        return route_for(self.classification, self.confidence)

    @property
    def review_required(self) -> bool:
        """Whether a person must look before this is acted on.

        Durable knowledge always requires review, at any confidence. A
        classifier certain that a sentence is a requirement has said nothing
        about whether the requirement is true.
        """

        return self.route is Route.NEEDS_REVIEW or self.tier is RetentionTier.DURABLE


def route_for(classification: ObservationClass, confidence: float) -> Route:
    """Return where a span goes, given its class and the classifier's certainty.

    Confidence gates *routing*, never truth. A `requirement` at 0.99 is still a
    proposal; what the confidence buys it is the right to be filed as one
    without a reviewer first agreeing it is a requirement at all.
    """

    if confidence < UNCERTAIN or classification is ObservationClass.UNCLASSIFIED:
        return Route.NEEDS_REVIEW
    tier = TIER_OF[classification]
    if tier is RetentionTier.EVIDENCE:
        return Route.EVIDENCE_ONLY
    if confidence < CONFIDENT:
        return Route.NEEDS_REVIEW
    if tier is RetentionTier.DURABLE:
        return Route.KNOWLEDGE_CANDIDATE
    return Route.OPERATIONAL_UPDATE


class TransitionAuthority(StrEnum):
    """What is claiming that operational state changed.

    A milestone is never completed because a sentence said so. This repository
    has a live example of why: `CURRENT_PROJECT_STATE.md` recorded "M8 is
    complete: knowledge is chunked, embedded, and searchable" while no
    production path created chunks at all. A person wrote that in good faith.
    A classifier accepting the same sentence would have made the false claim
    machine-readable.
    """

    USER_REPORTED = "user_reported"
    AGENT_REPORTED = "agent_reported"
    EXECUTION_EVIDENCE = "execution_evidence"


AUTO_CONFIRMING: frozenset[TransitionAuthority] = frozenset(
    {TransitionAuthority.EXECUTION_EVIDENCE}
)
"""The only authority that may settle a transition without a person.

Passing acceptance tests, a merged release PR, a signed deployment record. A
sentence reporting any of those is not any of those.
"""


class OperationalState(StrEnum):
    """The state an operational record is in."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    REJECTED = "rejected"


ACTIVE_STATES: frozenset[OperationalState] = frozenset(
    {OperationalState.PROPOSED, OperationalState.ACTIVE}
)
"""What a standard briefing may show as current.

Resolved, expired, and rejected records stay readable in history views. What
they must not do is appear in a briefing as though they still described the
project.
"""


def is_verified_result(produced_by_approved_runner: bool) -> str:
    """Return whether a test result is `verified` or merely `reported`.

    A sentence claiming a test passed is a report. Only an approved runner
    produces a verified one, and the distinction has to survive into the
    record or the two become the same claim.
    """

    return "verified" if produced_by_approved_runner else "reported"
