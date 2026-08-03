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


RETRIEVABLE: frozenset[LifecycleState] = frozenset(
    {LifecycleState.PROPOSED, LifecycleState.VALIDATED}
)
"""What normal search may return.

Searchable and authoritative are different questions. Proposed knowledge is
evidence a person has not ruled on: it is findable, and it is labelled, because
hiding it until confirmation would make review impossible — a reviewer cannot
accept what they cannot see. Rejected and superseded knowledge is excluded, not
ranked low: it was ruled out, and a result set is not the place to relitigate
that.
"""

AUTHORITATIVE: frozenset[LifecycleState] = frozenset({LifecycleState.VALIDATED})
"""What may be treated as established fact.

Used where output is generated from knowledge rather than shown for review. The
distinction from :data:`RETRIEVABLE` is the whole point: a caller building a
blueprint must not silently include statements nobody confirmed.
"""

HISTORICAL: frozenset[LifecycleState] = frozenset(LifecycleState)
"""Everything, including what was ruled out. Diagnostics and audit only."""
