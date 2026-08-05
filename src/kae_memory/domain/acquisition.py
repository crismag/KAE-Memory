"""Progressive acquisition, and readiness per capability (N34).

> Incomplete, uncertain, or minimal project knowledge is a normal project
> condition — not a failure, and not by itself a reason to stop generation.

The readiness percentage stays. What changes is what it is allowed to mean: an
indicator of how well understood a project is, never a permission to act. A
project at 42% can be interviewed, ingested, assembled, recorded, and rendered.
What it cannot do is *claim* to be production-ready, and that is a statement
about the output rather than a gate on producing it.

So readiness is reported per capability. "Not ready" is not an answer, because
it does not say which operation is unavailable, why, or what to do — and a
caller who cannot tell "you need to authorise GitHub" from "your requirements
are thin" will treat both as the same wall.

**A blocker must not spread.** Missing GitHub authorisation blocks GitHub
publication. It does not block generation, recording, local publication, or
acquisition, and a readiness model that let it would be describing a product
nobody wants to use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .errors import DomainInvariantError


class AcquisitionState(StrEnum):
    """How far a project has got in taking information in.

    Deliberately not a completion percentage. "Awaiting important input" and
    "awaiting optional input" are different situations with different remedies,
    and a single number cannot tell them apart.
    """

    NOT_STARTED = "not_started"
    RECEIVING = "receiving_input"
    ORGANISING = "organising"
    AWAITING_OPTIONAL = "awaiting_optional_input"
    AWAITING_IMPORTANT = "awaiting_important_input"
    SUFFICIENT_FOR_REQUEST = "sufficient_for_requested_generation"


class CapabilityState(StrEnum):
    """Whether one operation can be performed, and if not, what kind of no.

    The distinctions carry different remedies, which is the entire reason they
    are separate values. `needs_authorization` is answered by granting
    permission; `blocked_by_provider` by fixing an integration;
    `blocked_by_integrity` by generating something new rather than republishing
    something old. Collapsing them into "unavailable" would leave every one of
    those callers with the same unhelpful answer.
    """

    AVAILABLE = "available"
    AVAILABLE_WITH_ASSUMPTIONS = "available_with_assumptions"
    AVAILABLE_WITH_WARNINGS = "available_with_warnings"
    DEGRADED = "degraded"
    NEEDS_CHOICE = "needs_choice"
    NEEDS_AUTHORIZATION = "needs_authorization"
    BLOCKED_BY_INTEGRITY = "blocked_by_integrity"
    BLOCKED_BY_PROVIDER = "blocked_by_provider"
    UNSUPPORTED = "unsupported"


PERMITTED: frozenset[CapabilityState] = frozenset(
    {
        CapabilityState.AVAILABLE,
        CapabilityState.AVAILABLE_WITH_ASSUMPTIONS,
        CapabilityState.AVAILABLE_WITH_WARNINGS,
        CapabilityState.DEGRADED,
    }
)
"""States in which the operation may proceed.

`degraded` is here on purpose. Degraded means the result will be poorer, and a
poorer result the user asked for with their eyes open is still the result they
asked for. Quality is a reason to warn, not a reason to refuse.
"""


BLOCKING: frozenset[CapabilityState] = frozenset(
    {
        CapabilityState.NEEDS_CHOICE,
        CapabilityState.NEEDS_AUTHORIZATION,
        CapabilityState.BLOCKED_BY_INTEGRITY,
        CapabilityState.BLOCKED_BY_PROVIDER,
        CapabilityState.UNSUPPORTED,
    }
)
"""States in which the operation genuinely cannot proceed.

Every one is a technical, authorisation, integrity, or support fact. **None of
them is "the knowledge is thin"** — which is the whole point of the split, and
the invariant a test holds.
"""


@dataclass(frozen=True, slots=True)
class CapabilityReadiness:
    """Whether one named operation can be performed right now.

    Every field except the state exists because "unavailable" alone is useless.
    A caller needs to know what would change it and what to do next; without
    those, the only available response is to guess or to give up.
    """

    capability: str
    state: CapabilityState
    reason: str = ""
    next_action: str = ""
    improves_with: tuple[str, ...] = ()
    assumptions_required: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.capability.strip():
            raise DomainInvariantError("a capability readiness must name its capability")
        if self.state in BLOCKING and not self.reason.strip():
            raise DomainInvariantError(
                f"{self.capability}: a blocked capability must say why. "
                f"'Unavailable' without a reason leaves a caller unable to act."
            )
        if self.state in BLOCKING and not self.next_action.strip():
            raise DomainInvariantError(
                f"{self.capability}: a blocked capability must name the next useful "
                f"action, or it is a dead end rather than a state"
            )
        if (
            self.state is CapabilityState.AVAILABLE_WITH_ASSUMPTIONS
            and not self.assumptions_required
        ):
            raise DomainInvariantError(
                f"{self.capability}: available-with-assumptions must name the "
                f"assumptions, or the caller cannot tell what they are accepting"
            )

    @property
    def permitted(self) -> bool:
        return self.state in PERMITTED


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """What a project can do now, capability by capability.

    The percentage travels with it and is explicitly advisory. Keeping it
    visible is deliberate: it is genuinely useful as an indicator of how well
    understood a project is, and removing it would only push callers toward
    inventing a worse one.
    """

    project_id: str
    acquisition_state: AcquisitionState
    percentage: int
    capabilities: tuple[CapabilityReadiness, ...] = field(default_factory=tuple)

    def for_capability(self, capability: str) -> CapabilityReadiness | None:
        for entry in self.capabilities:
            if entry.capability == capability:
                return entry
        return None

    def permits(self, capability: str) -> bool:
        """Whether one operation may proceed.

        An unregistered capability is permitted, not refused. This report says
        what is *known* to be blocked; treating an unknown name as a refusal
        would turn every gap in the report into a gate, which is the failure
        mode the whole model exists to avoid.
        """

        entry = self.for_capability(capability)
        return entry.permitted if entry else True

    @property
    def blocked(self) -> tuple[CapabilityReadiness, ...]:
        return tuple(entry for entry in self.capabilities if not entry.permitted)

    @property
    def advisory_only(self) -> bool:
        """Whether nothing here is a real block.

        True when every capability is permitted. Named rather than inferred so
        that "this project has warnings" and "this project cannot act" are
        distinguishable at a glance.
        """

        return not self.blocked


GENERATION_CAPABILITIES: tuple[str, ...] = (
    "acquisition.continue",
    "knowledge.assemble",
    "deliverable.record",
    "deliverable.render",
)
"""Operations that knowledge quality must never block.

Listed so a test can assert it. Each is either taking information in or turning
what is already there into something the user asked for — and refusing either
because the information is thin would be refusing the product's reason to
exist.
"""


def quality_never_blocks(report: ReadinessReport) -> None:
    """Raise if a generation capability was blocked for a quality reason.

    The regression this exists to prevent: nothing today gates generation on
    the readiness percentage, and nothing stops that changing. A future
    "helpfully" strict check would look reasonable in review and would break the
    product's central promise.
    """

    for entry in report.capabilities:
        if entry.capability not in GENERATION_CAPABILITIES:
            continue
        if entry.permitted:
            continue
        if entry.state in {CapabilityState.NEEDS_AUTHORIZATION, CapabilityState.UNSUPPORTED}:
            # Authorisation and support are real facts about an operation, not
            # judgements about how well understood a project is.
            continue
        raise DomainInvariantError(
            f"{entry.capability} is blocked as {entry.state.value}: {entry.reason}. "
            f"Sparse or uncertain knowledge must not block acquisition, assembly, "
            f"recording, or rendering — it qualifies the output instead."
        )
