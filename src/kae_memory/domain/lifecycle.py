"""Knowledge lifecycle states and transition rules."""

from enum import StrEnum

from .errors import InvalidLifecycleTransitionError


class LifecycleState(StrEnum):
    """Explicit validation and lifecycle state for durable knowledge."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


_ALLOWED_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.PROPOSED: frozenset({LifecycleState.VALIDATED, LifecycleState.REJECTED}),
    LifecycleState.VALIDATED: frozenset({LifecycleState.SUPERSEDED}),
    LifecycleState.REJECTED: frozenset(),
    LifecycleState.SUPERSEDED: frozenset(),
}


def ensure_transition(current: LifecycleState, target: LifecycleState) -> None:
    """Validate a requested lifecycle transition."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(
            f"cannot transition knowledge from {current.value} to {target.value}"
        )
