"""Assumptions as durable records (N35).

When information is missing, KAE may proceed — but only by saying so. An
assumption is what "saying so" looks like when it has to survive the response
that made it.

Until now `StatementLabel.ASSUMPTION` was a label applied to an assembled
statement. A label cannot be pinned, disclosed, accepted, revisited, or
reversed; it exists for as long as the payload that carried it. So a package
generated from thin knowledge disclosed its assumptions once, to whoever read
that response, and then forgot them.

The rule everything here protects:

    a material assumption is never silently promoted to a confirmed requirement.

FR-005 already says a person confirms what becomes project knowledge. An
assumption that could quietly become one would be a way around that rule rather
than an exception to it — and the way around would look like helpfulness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import Identifier, ProjectId


@dataclass(frozen=True, slots=True)
class AssumptionId(Identifier):
    """Stable assumption identifier, so a deliverable can pin one."""


class AssumptionOrigin(StrEnum):
    """Who made the assumption, which decides how much weight it carries.

    A user stating something provisionally and KAE picking a default under time
    pressure are both assumptions and are not equally answerable. Collapsing
    them would make "the user said so" and "we guessed" the same evidence.
    """

    USER_STATED = "user_stated"
    KAE_INFERRED = "kae_inferred"
    KAE_RECOMMENDED_ACCEPTED = "kae_recommended_accepted"
    KAE_TEMPORARY = "kae_temporary"
    IMPORTED = "imported"
    TEMPLATE_INHERITED = "template_inherited"
    UNRESOLVED_ALTERNATIVE = "unresolved_alternative"


class AssumptionState(StrEnum):
    """Where an assumption stands.

    `accepted` means a person took responsibility for it. It does **not** mean
    the statement became knowledge — that path runs through confirmation, and
    keeping the two apart is the point.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


_ALLOWED: dict[AssumptionState, frozenset[AssumptionState]] = {
    AssumptionState.PROPOSED: frozenset(
        {AssumptionState.ACCEPTED, AssumptionState.REJECTED, AssumptionState.SUPERSEDED}
    ),
    # An accepted assumption can still be retired when the gap it covered is
    # answered — that is the normal, healthy end, not a reversal.
    AssumptionState.ACCEPTED: frozenset(
        {AssumptionState.RETIRED, AssumptionState.SUPERSEDED, AssumptionState.REJECTED}
    ),
    AssumptionState.REJECTED: frozenset(),
    AssumptionState.SUPERSEDED: frozenset(),
    AssumptionState.RETIRED: frozenset(),
}


class InvalidAssumptionTransitionError(DomainInvariantError):
    """An assumption state change the domain does not permit."""


def ensure_assumption_transition(current: AssumptionState, target: AssumptionState) -> None:
    """Validate a requested assumption state change."""

    if target not in _ALLOWED[current]:
        allowed = sorted(state.value for state in _ALLOWED[current])
        raise InvalidAssumptionTransitionError(
            f"cannot move an assumption from {current.value} to {target.value}; "
            f"permitted: {', '.join(allowed) or 'none, this state is terminal'}"
        )


class Consequence(StrEnum):
    """What it costs if the assumption turns out wrong.

    Recorded because "we assumed PostgreSQL" and "we assumed single-tenant" are
    not the same risk, and a list that treated them alike would bury the second
    among the first.
    """

    COSMETIC = "cosmetic"
    REWORK = "rework"
    ARCHITECTURAL = "architectural"
    UNSAFE = "unsafe"


MATERIAL: frozenset[Consequence] = frozenset({Consequence.ARCHITECTURAL, Consequence.UNSAFE})
"""Consequences that make an assumption material.

A material assumption must be disclosed wherever the output it shaped is
disclosed. Everything else may be summarised.
"""


class RevisitTrigger(StrEnum):
    """When this assumption should be looked at again.

    Absent would mean "never", which is how a prototype default becomes a
    production commitment nobody remembers making.
    """

    NEVER = "never"
    ON_REQUEST = "on_request"
    BEFORE_BUILD = "before_build"
    BEFORE_PRODUCTION = "before_production"
    ON_CONFLICTING_EVIDENCE = "on_conflicting_evidence"


@dataclass(frozen=True, slots=True)
class Assumption:
    """One interpretation used in place of information that is missing."""

    id: AssumptionId
    project_id: ProjectId
    subject: str
    assumed_value: str
    reason: str
    origin: AssumptionOrigin
    consequence: Consequence = Consequence.REWORK
    confidence: float = 0.5
    state: AssumptionState = AssumptionState.PROPOSED
    reversible: bool = True
    scope: str = "project"
    revisit: RevisitTrigger = RevisitTrigger.ON_REQUEST
    evidence: tuple[str, ...] = ()
    accepted_by: str | None = None
    delegated: bool = False
    supersedes: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise DomainInvariantError("an assumption must name the gap it covers")
        if not self.assumed_value.strip():
            raise DomainInvariantError("an assumption must state what it assumed")
        if not self.reason.strip():
            raise DomainInvariantError(
                "an assumption must say why it was made. Without a reason a reader "
                "cannot judge it, and an unjudgeable assumption is a guess with a "
                "record attached"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise DomainInvariantError(f"confidence {self.confidence} is not a probability")
        if self.state is AssumptionState.ACCEPTED and not self.accepted_by:
            raise DomainInvariantError(
                "an accepted assumption names who accepted it: acceptance is a person "
                "taking responsibility, and responsibility nobody is named for is none"
            )
        if self.material and self.revisit is RevisitTrigger.NEVER:
            raise DomainInvariantError(
                f"{self.subject!r} is a {self.consequence.value} assumption and cannot be "
                f"marked never-revisit. That is how a prototype default becomes a "
                f"production commitment nobody remembers making."
            )

    @property
    def material(self) -> bool:
        """Whether this must be disclosed wherever the output it shaped is."""

        return self.consequence in MATERIAL or not self.reversible

    @property
    def is_active(self) -> bool:
        return self.state in {AssumptionState.PROPOSED, AssumptionState.ACCEPTED}


def disclosure(assumption: Assumption) -> str:
    """Render one assumption as a line a reader can act on.

    Deliberately includes the consequence. "We assumed single-tenant" invites a
    nod; "we assumed single-tenant, and multi-tenancy would be architectural
    rework" invites a decision.
    """

    accepted = f", accepted by {assumption.accepted_by}" if assumption.accepted_by else ""
    return (
        f"{assumption.subject}: assumed {assumption.assumed_value} "
        f"({assumption.origin.value}{accepted}). {assumption.reason} "
        f"If wrong: {assumption.consequence.value}."
    )
