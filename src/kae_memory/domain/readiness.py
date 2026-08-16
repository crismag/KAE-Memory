"""Blueprint readiness: coverage of confirmed discovery knowledge.

Readiness answers one question — does this project hold enough *confirmed*
knowledge to generate a useful blueprint? It is deliberately not implementation
progress, success probability, or model confidence, and it is not how much
conversation has happened (ADR-0012).

The percentage is computed here from persisted facts and nothing else. AI may
propose which area a piece of knowledge serves; it never decides whether an area
is covered. That separation is the point: a system that raises its own score by
generating more text is worse than having no score at all.

"Confirmed" is the existing :class:`~kae_memory.domain.lifecycle.LifecycleState`
``VALIDATED``. ADR-0012 used the word "confirmed"; no new state was added for it,
because two words for one state is how vocabularies drift.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import (
    AgentRunId,
    AreaLinkId,
    BlockerId,
    KnowledgeItemId,
    ProjectId,
    SnapshotId,
)
from .models import KnowledgeKind


class AreaState(StrEnum):
    """The one authoritative coverage state of a discovery area.

    `ADR-0008`'s progression, discrete throughout — `ADR-0003` still rules that
    there is no percentage inside an area::

        missing → partial → evidenced → interpreted → sufficient

    `PARTIAL` is the tier the ADR names and had nowhere to put: an area holding
    only KAE's own candidates, which it calls *"proposal — not evidence"*.
    `EVIDENCED` requires a source outside KAE; `INTERPRETED` adds KAE's derived
    reading on top of one.

    **`SUFFICIENT` keeps its name deliberately.** It is the ADR's `confirmed`,
    and renaming it would be the shape of `D-27`, where a covered area rendered
    as *missing* for the life of a deployment because Studio compared against a
    literal Memory had stopped sending. Which vocabulary finally governs is
    `AREA-STATES`/`D-31`, still open, and it has to land in both repositories at
    once.

    `conflicted` is **not** a member. `ADR-0008` makes it an orthogonal
    condition and `AreaResult.contradicted` already carries it; flattening the
    two into one ladder would lose which of them is true.
    """

    MISSING = "missing"
    PARTIAL = "partial"
    EVIDENCED = "evidenced"
    INTERPRETED = "interpreted"
    SUFFICIENT = "sufficient"
    NOT_APPLICABLE = "not_applicable"


_CREDIT: dict[AreaState, float] = {
    AreaState.MISSING: 0.0,
    AreaState.PARTIAL: 0.5,
    # Deliberately identical to PARTIAL, and this is the whole of `D-107`.
    # `ADR-0008` puts weights out of scope because "changing the semantics and
    # the calibration at once would make the result unattributable to either",
    # and credit-per-state is calibration. So no project's percentage moves;
    # what improves is what an area *says*. Calibrating these is a later
    # decision, taken once real projects have been observed distributing across
    # the states.
    AreaState.EVIDENCED: 0.5,
    AreaState.INTERPRETED: 0.5,
    AreaState.SUFFICIENT: 1.0,
    AreaState.NOT_APPLICABLE: 0.0,
}


def credit_for(state: AreaState) -> float:
    """Return the credit an area in ``state`` contributes.

    ``NOT_APPLICABLE`` returns zero, but it is also excluded from the
    denominator, so it neither helps nor penalises.
    """

    return _CREDIT[state]


#: Source kinds that ground a statement outside KAE (`ADR-0008`).
#:
#: The ADR's provenance table rather than a policy of the calculator: an area
#: may reach `EVIDENCED` on one of these and on nothing else, which is what
#: stops a project raising its own readiness by generating statements.
GROUNDING_SOURCE_TYPES = frozenset({"repository", "user_statement", "imported_document"})

#: What KAE derived with no supporting source. A proposal, never evidence.
INFERENCE_SOURCE_TYPE = "kae_inference"

#: An area somebody still has work to do in.
#:
#: Written as a set rather than repeated as `in (MISSING, PARTIAL)` at each
#: call site, because that form is what a new tier silently drops out of: an
#: `EVIDENCED` area is better grounded than a `PARTIAL` one and is still not
#: finished, and a project should not stop being told so because the ladder
#: grew a rung.
UNFINISHED_STATES = frozenset(
    {AreaState.MISSING, AreaState.PARTIAL, AreaState.EVIDENCED, AreaState.INTERPRETED}
)


class ReadinessStatus(StrEnum):
    """Semantic project state, which is not the same thing as the percentage."""

    NOT_STARTED = "not_started"
    DISCOVERING = "discovering"
    DRAFT_READY = "draft_ready"
    BLOCKED = "blocked"
    BLUEPRINT_READY = "blueprint_ready"
    STALE = "stale"


class BlockerSeverity(StrEnum):
    """How much a blocker matters. Only ``CRITICAL`` gates generation."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class BlockerStatus(StrEnum):
    """Whether a blocker still stands."""

    OPEN = "open"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class Blocker:
    """Something that prevents a project from being blueprint-ready.

    A blocker is deliberately *not* a :class:`KnowledgeKind`. An ``unknown``
    knowledge item is a gap in what we know; a blocker is a gap someone owns and
    must close. It carries severity, an owner, and a resolved state, none of
    which the knowledge lifecycle expresses — ``REJECTED`` means "this was wrong",
    not "this was dealt with". Modelling blockers as knowledge would also put them
    in the extraction vocabulary and in the readiness denominator, where neither
    belongs.

    ADR-0012 recorded this choice as outstanding; this is M9 making it.
    """

    id: BlockerId
    project_id: ProjectId
    summary: str
    severity: BlockerSeverity
    created_at: datetime
    area_key: str | None = None
    owner: str | None = None
    status: BlockerStatus = BlockerStatus.OPEN
    resolved_at: datetime | None = None
    resolution_note: str | None = None

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise DomainInvariantError("blocker summary must not be empty")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("blocker created_at must be timezone-aware")
        resolved = self.status is BlockerStatus.RESOLVED
        if resolved and self.resolved_at is None:
            raise DomainInvariantError("a resolved blocker must record when it was resolved")
        if not resolved and self.resolved_at is not None:
            raise DomainInvariantError("an open blocker must not record a resolution time")

    def resolve(self, moment: datetime, note: str | None = None) -> "Blocker":
        """Return a resolved copy of this blocker."""

        if self.status is BlockerStatus.RESOLVED:
            raise DomainInvariantError("blocker is already resolved")
        return Blocker(
            id=self.id,
            project_id=self.project_id,
            summary=self.summary,
            severity=self.severity,
            created_at=self.created_at,
            area_key=self.area_key,
            owner=self.owner,
            status=BlockerStatus.RESOLVED,
            resolved_at=moment,
            resolution_note=note,
        )


@dataclass(frozen=True, slots=True)
class AreaDefinition:
    """One weighted discovery area and what it takes to cover it.

    ``kinds`` guards which knowledge may count, and ``minimum_confirmed`` is the
    explicit criterion for sufficiency. Both are configuration: the existence of
    text, messages, or model output is never evidence of readiness.

    Kinds alone cannot resolve an area — "functional requirements" and "quality
    attributes" are both ``requirement`` — so coverage additionally requires an
    explicit area link on the knowledge item. That is why M9 keeps the existing
    eight :class:`KnowledgeKind` values rather than extending them, which would
    have changed the extraction vocabulary in ADR-0006.
    """

    key: str
    name: str
    weight: float
    kinds: tuple[KnowledgeKind, ...]
    minimum_confirmed: int = 1
    mandatory: bool = True
    #: The separately-establishable things inside this area, when it has more
    #: than one. Empty means the area is a single claim and behaves as it always
    #: has — which is nine of the ten.
    claims: tuple["Claim", ...] = ()

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise DomainInvariantError("readiness area key must not be empty")
        if self.weight <= 0:
            raise DomainInvariantError("readiness area weight must be positive")
        if self.minimum_confirmed < 1:
            raise DomainInvariantError("readiness area must require at least one confirmed item")
        if not self.kinds:
            raise DomainInvariantError("readiness area must accept at least one knowledge kind")
        keys = [claim.key for claim in self.claims]
        if len(keys) != len(set(keys)):
            raise DomainInvariantError(f"area {self.key} has duplicate claim keys")

    @property
    def is_divided(self) -> bool:
        """Whether this area asks for more than one distinguishable thing."""

        return bool(self.claims)


@dataclass(frozen=True, slots=True)
class Claim:
    """One distinguishable thing an area must establish.

    **Why an area is not always one question.** `problem_and_value` covers two:
    what hurts, and why solving it is worth doing. They are different claims a
    project must be able to make separately, and nothing inside the area
    distinguishes them — so `value` was reported empty for every project in
    existence, and the Definition page said so for a reason it could not
    explain (`RUN-D14`).

    **The alternative that was rejected**, and why it matters: splitting
    `problem_and_value` into two areas would rebalance every weight and
    silently change the readiness of every project already evaluated.
    `RUN-C1` ruled against redistribution for exactly that reason. A claim
    subdivides an area *without touching its weight*.

    Areas without claims behave exactly as before, so this is additive for the
    other nine.
    """

    key: str
    name: str
    minimum_confirmed: int = 1

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise DomainInvariantError("claim key must not be empty")
        if self.minimum_confirmed < 1:
            raise DomainInvariantError("a claim must require at least one confirmed item")


@dataclass(frozen=True, slots=True)
class KnowledgeAreaLink:
    """A knowledge item's assignment to a discovery area.

    Classification is the one part of readiness that may be agent work — the
    Review Agent, which FR-009 already authorises. It proposes; the calculator
    decides. Recalculation itself is deterministic application logic and never
    becomes a fourth agent role.
    """

    id: AreaLinkId
    project_id: ProjectId
    knowledge_item_id: KnowledgeItemId
    area_key: str
    created_at: datetime
    assigned_by_agent_run_id: AgentRunId | None = None
    #: Which claim inside the area this statement establishes, when the area has
    #: claims and the assignment was specific enough to say.
    #:
    #: `None` still counts toward the area, which is what keeps every existing
    #: link valid: an assignment made before claims existed said "this is about
    #: the problem and value of the project" and that remains true.
    claim_key: str | None = None

    def __post_init__(self) -> None:
        if not self.area_key.strip():
            raise DomainInvariantError("area link must name an area")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("area link created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ReadinessTemplate:
    """A versioned set of weighted areas.

    Versioned because the weights and thresholds below are judgement, not
    measurement. They will be wrong at first, and versioning plus append-only
    snapshots is what makes correcting them safe and observable.
    """

    key: str
    version: int
    areas: tuple[AreaDefinition, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise DomainInvariantError("template version must be positive")
        if not self.areas:
            raise DomainInvariantError("template must define at least one area")
        keys = [area.key for area in self.areas]
        if len(set(keys)) != len(keys):
            raise DomainInvariantError("template area keys must be unique")

    def area(self, key: str) -> AreaDefinition | None:
        """Return an area by key."""

        return next((area for area in self.areas if area.key == key), None)


@dataclass(frozen=True, slots=True)
class AreaResult:
    """One area's contribution, with the counts that produced it."""

    key: str
    name: str
    weight: float
    mandatory: bool
    state: AreaState
    confirmed_count: int
    proposed_count: int
    minimum_confirmed: int
    contradicted: bool = False

    @property
    def credit(self) -> float:
        """Return this area's credit."""

        return credit_for(self.state)


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    """An append-only record of one readiness calculation.

    Snapshots are how readiness is *explained* and how it is shown moving as
    knowledge is confirmed. A single mutable percentage on the project row would
    answer neither question.
    """

    id: SnapshotId
    project_id: ProjectId
    template_key: str
    template_version: int
    calculation_version: int
    knowledge_revision: int
    score: float
    status: ReadinessStatus
    draft_eligible: bool
    implementation_eligible: bool
    areas: tuple[AreaResult, ...]
    open_blocker_count: int
    critical_blocker_count: int
    unresolved_contradiction_count: int
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.calculated_at.tzinfo is None:
            raise DomainInvariantError("snapshot calculated_at must be timezone-aware")
        if not 0.0 <= self.score <= 100.0:
            raise DomainInvariantError("readiness score must fall between 0 and 100")

    @property
    def percentage(self) -> int:
        """Return the score rounded for display."""

        return round(self.score)

    @property
    def missing_mandatory_areas(self) -> tuple[str, ...]:
        """Return the mandatory areas that are not yet sufficient."""

        return tuple(
            area.key for area in self.areas if area.mandatory and area.state in UNFINISHED_STATES
        )

    def is_stale_against(self, current_revision: int) -> bool:
        """Return whether later authoritative knowledge exists.

        Compared against a monotonic per-project counter rather than a timestamp:
        timestamps collide under concurrent writes and leave "did anything
        change?" ambiguous.
        """

        return current_revision > self.knowledge_revision

    def is_behind_template(self, current_version: int) -> bool:
        """Return whether a newer template version exists than this was computed under.

        **A different staleness from the one above, and it had no expression.**
        `is_stale_against` asks whether the project moved; this asks whether the
        *meaning of the number* moved. A project pinned to version 1 after
        version 2 is published is not stale in the first sense — nothing about
        it changed — and every snapshot it holds is nonetheless computed under
        semantics that are no longer current.

        Without this, the pin is invisible: a project sits on an older template
        indefinitely and nothing anywhere says so, which turns a deliberate
        choice into a silent one. Reported, never acted on — moving a project
        forward stays an explicit act.
        """

        return current_version > self.template_version


DRAFT_THRESHOLD = 50.0
"""Minimum score for a draft blueprint.

Judgement, not measurement — see :class:`ReadinessTemplate`.
"""

CALCULATION_VERSION = 1
"""Bumped whenever the scoring logic changes, so old snapshots stay comparable."""


def _area(
    key: str,
    name: str,
    weight: float,
    kinds: tuple[KnowledgeKind, ...],
    minimum: int = 1,
    mandatory: bool = True,
    claims: tuple[Claim, ...] = (),
) -> AreaDefinition:
    return AreaDefinition(
        key=key,
        name=name,
        weight=weight,
        kinds=kinds,
        minimum_confirmed=minimum,
        mandatory=mandatory,
        claims=claims,
    )


#: The default template for software projects.
#:
#: **Do not rebalance these mappings to make the offline classifier cover more
#: ground.** Ruled 2026-08-09 as ecosystem concern `RUN-C1`, and the reasoning
#: is recorded here because this is where the question gets asked again.
#:
#: Only two of the eight knowledge kinds map to exactly one area — ``ACTOR`` to
#: ``users_and_stakeholders`` and ``ASSUMPTION`` to
#: ``constraints_and_assumptions``. Goals, requirements, rules, constraints and
#: decisions each map to between two and five, so a deployment without a review
#: model declines to classify them. Those two areas carry weight 1.0 each of a
#: 12.5 total, which puts the offline ceiling at **16%**, with
#: ``implementation_eligible`` unreachable whatever the corpus.
#:
#: Redistributing kinds so more of them were unambiguous would raise that
#: ceiling and buy nothing real: it would manufacture coverage a person then has
#: to unpick, and it would silently change the readiness of every project
#: already evaluated. ``KAE_REVIEW`` stays mandatory. It may become an
#: optimisation later — but only once an offline classifier has demonstrated
#: comparable quality, not because the mappings were redistributed.
SOFTWARE_TEMPLATE = ReadinessTemplate(
    key="software",
    # **Version 2: `problem_and_value` gained two claims** (`RUN-D14`).
    #
    # The weights are untouched — `RUN-C1` ruled against redistribution — so
    # nothing about any other area changed. What changed is that this area is
    # now sufficient only when a project can state both what hurts and why
    # solving it is worth doing, where before either alone completed it.
    #
    # That is a *stricter* rule, so a project evaluated under v1 could report a
    # lower number under v2. Which is exactly why the version moved: an
    # unversioned change here would have altered historical readiness silently,
    # and "no historical readiness score changes without saying so" is the
    # constraint the whole pin exists to keep.
    version=2,
    areas=(
        _area(
            "problem_and_value",
            "Problem and value proposition",
            weight=1.5,
            kinds=(KnowledgeKind.GOAL, KnowledgeKind.RULE),
            claims=(
                Claim("problem_statement", "What hurts"),
                Claim("value_proposition", "Why solving it is worth doing"),
            ),
        ),
        _area(
            "users_and_stakeholders",
            "Users and stakeholders",
            weight=1.0,
            kinds=(KnowledgeKind.ACTOR,),
        ),
        _area(
            "scope_and_boundaries",
            "Scope and boundaries",
            weight=1.0,
            kinds=(KnowledgeKind.GOAL, KnowledgeKind.CONSTRAINT, KnowledgeKind.DECISION),
        ),
        _area(
            "functional_requirements",
            "Functional requirements",
            weight=2.0,
            kinds=(KnowledgeKind.REQUIREMENT,),
            minimum=3,
        ),
        _area(
            "quality_attributes",
            "Quality attributes",
            weight=1.0,
            kinds=(KnowledgeKind.REQUIREMENT, KnowledgeKind.CONSTRAINT),
        ),
        _area(
            "domain_model_and_data",
            "Domain model and data",
            weight=1.5,
            kinds=(KnowledgeKind.RULE, KnowledgeKind.REQUIREMENT),
        ),
        _area(
            "interfaces_and_integrations",
            "Interfaces and integrations",
            weight=1.0,
            kinds=(KnowledgeKind.REQUIREMENT, KnowledgeKind.CONSTRAINT, KnowledgeKind.DECISION),
            mandatory=False,
        ),
        _area(
            "constraints_and_assumptions",
            "Constraints and assumptions",
            weight=1.0,
            kinds=(KnowledgeKind.CONSTRAINT, KnowledgeKind.ASSUMPTION),
        ),
        _area(
            "acceptance_criteria",
            "Acceptance criteria",
            weight=1.5,
            kinds=(KnowledgeKind.RULE, KnowledgeKind.REQUIREMENT),
        ),
        _area(
            "delivery_and_operations",
            "Delivery and operational context",
            weight=1.0,
            kinds=(KnowledgeKind.CONSTRAINT, KnowledgeKind.DECISION),
            mandatory=False,
        ),
    ),
)
"""The initial software template.

Ships with the application, but readiness logic never hard-codes one project
type: templates are data, addressed by key and version.
"""


__all__ = [
    "CALCULATION_VERSION",
    "DRAFT_THRESHOLD",
    "GROUNDING_SOURCE_TYPES",
    "INFERENCE_SOURCE_TYPE",
    "SOFTWARE_TEMPLATE",
    "UNFINISHED_STATES",
    "AreaDefinition",
    "AreaResult",
    "AreaState",
    "Blocker",
    "BlockerSeverity",
    "BlockerStatus",
    "KnowledgeAreaLink",
    "ReadinessSnapshot",
    "ReadinessStatus",
    "ReadinessTemplate",
    "credit_for",
]
