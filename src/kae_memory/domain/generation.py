"""Generation modes and inclusion classes (N37).

A mode declares what the output is *for*. It changes what is included by
default and how the result is qualified — and it is never a gate. There is no
mode from which generation is unavailable, and no threshold a project must
reach to request one.

That is worth stating twice, because the shape of this feature invites the
opposite. "Build mode requires confirmed requirements" reads as prudence and
would reintroduce exactly the readiness gate N34 removed, wearing different
words. A caller asking for a build package from an idea gets one, qualified
honestly as resting on two unconfirmed statements and an assumption.

**Inclusion class is not authority.** `StatementLabel` says where a statement's
authority comes from — grounded in evidence, derived, or assumed — and is
computed from provenance. An inclusion class says what *kind of content* this
is: confirmed, proposed, disputed, deferred. Assembly had been using the
authority label to carry the confirmation state, which made "a statement KAE
inferred" and "a statement nobody has confirmed" the same word.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import DomainInvariantError


class GenerationMode(StrEnum):
    """What the requested output is for.

    Intent, not a stage. A project moves between these freely and repeatedly —
    an exploratory package on Monday and a build package on Tuesday is a normal
    week, not a violation of an order.
    """

    EXPLORE = "explore"
    SHAPE = "shape"
    PLAN = "plan"
    BUILD = "build"
    VALIDATE = "validate"


class InclusionClass(StrEnum):
    """What kind of content a statement is, for the purpose of including it.

    Distinct from `StatementLabel`, which says where authority comes from. A
    statement can be `grounded` in evidence and still be `proposed`, and the
    two answer different questions a reader has.
    """

    CONFIRMED = "confirmed"
    USER_SUPPLIED = "user_supplied"
    PROPOSED = "proposed"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    DEFERRED = "deferred"


DEFAULT_INCLUSIONS: dict[GenerationMode, frozenset[InclusionClass]] = {
    # Exploring is the mode with the least to go on, so it admits the most.
    # Refusing unconfirmed material here would leave nothing to explore.
    GenerationMode.EXPLORE: frozenset(
        {
            InclusionClass.CONFIRMED,
            InclusionClass.USER_SUPPLIED,
            InclusionClass.PROPOSED,
            InclusionClass.INFERRED,
            InclusionClass.ASSUMED,
            InclusionClass.DISPUTED,
        }
    ),
    GenerationMode.SHAPE: frozenset(
        {
            InclusionClass.CONFIRMED,
            InclusionClass.USER_SUPPLIED,
            InclusionClass.PROPOSED,
            InclusionClass.ASSUMED,
            InclusionClass.DISPUTED,
        }
    ),
    GenerationMode.PLAN: frozenset(
        {
            InclusionClass.CONFIRMED,
            InclusionClass.USER_SUPPLIED,
            InclusionClass.PROPOSED,
            InclusionClass.ASSUMED,
        }
    ),
    # Build leans on confirmed material and still admits proposals, because a
    # project that has confirmed nothing may legitimately want an
    # implementation-oriented package — labelled for what it is.
    GenerationMode.BUILD: frozenset(
        {
            InclusionClass.CONFIRMED,
            InclusionClass.USER_SUPPLIED,
            InclusionClass.PROPOSED,
            InclusionClass.ASSUMED,
        }
    ),
    # Validation is the one mode that narrows, and it narrows toward *evidence
    # and disagreement* rather than away from uncertainty: what is settled, and
    # what is contested. An assumption is precisely what a reviewer must see.
    GenerationMode.VALIDATE: frozenset(
        {
            InclusionClass.CONFIRMED,
            InclusionClass.DISPUTED,
            InclusionClass.ASSUMED,
        }
    ),
}
"""What each mode includes when the caller says nothing else.

Defaults, never limits: a caller may ask for more. `rejected` and `superseded`
are in no default, because they are history rather than active
recommendations — asking for them is asking for history, which is a different
request and is allowed.
"""

if set(DEFAULT_INCLUSIONS) != set(GenerationMode):  # pragma: no cover - import guard
    missing = sorted(set(GenerationMode) - set(DEFAULT_INCLUSIONS))
    raise DomainInvariantError(f"generation modes without an inclusion policy: {missing}")

if any(not classes for classes in DEFAULT_INCLUSIONS.values()):  # pragma: no cover
    raise DomainInvariantError(
        "a mode that includes nothing is a mode that cannot generate, which is the "
        "gate this model exists to prevent"
    )


HISTORICAL: frozenset[InclusionClass] = frozenset(
    {InclusionClass.SUPERSEDED, InclusionClass.REJECTED}
)
"""Classes excluded from active recommendations unless asked for by name."""


def inclusions_for(
    mode: GenerationMode, also_include: frozenset[InclusionClass] | None = None
) -> frozenset[InclusionClass]:
    """Return what to include, widening the mode's default if asked.

    Only ever widens. A mode cannot be narrowed into refusing everything, and a
    caller cannot accidentally ask for less than the mode implies — which is
    the shape a gate would need.
    """

    return DEFAULT_INCLUSIONS[mode] | (also_include or frozenset())


def qualifications(mode: GenerationMode, present: frozenset[InclusionClass]) -> tuple[str, ...]:
    """Return the sentences that keep this output honest about its evidence.

    Qualification is what replaces refusal. A build package resting on
    unconfirmed statements is useful and is not a production commitment, and
    saying so plainly is the difference between the two.
    """

    lines: list[str] = []
    if InclusionClass.PROPOSED in present:
        lines.append(
            "Includes statements nobody has confirmed. They are labelled proposed; "
            "treat them as candidates rather than decisions."
        )
    if InclusionClass.ASSUMED in present:
        lines.append(
            "Includes assumptions made in place of missing information. Each names "
            "what was assumed, why, and what it would cost if wrong."
        )
    if InclusionClass.DISPUTED in present:
        lines.append(
            "Includes statements that contradict one another. The contradiction is "
            "preserved rather than resolved; do not choose between them on the "
            "project's behalf."
        )
    if mode is GenerationMode.BUILD and InclusionClass.CONFIRMED not in present:
        lines.append(
            "Nothing in this package is confirmed. It is suitable for prototype "
            "implementation and is not evidence of production readiness."
        )
    if mode is GenerationMode.VALIDATE and InclusionClass.PROPOSED in present:
        lines.append(
            "Validation normally reads confirmed knowledge. Proposed statements were "
            "included by explicit request and are not review evidence."
        )
    return tuple(lines)


def mode_never_blocks(mode: GenerationMode) -> None:
    """Raise if a mode has been configured into refusing to generate.

    The regression this exists to prevent has a plausible shape: someone adds
    "build requires confirmed requirements" and it reads as prudence. It is the
    readiness gate N34 removed, reintroduced in different words, and nothing
    else in the codebase would notice.
    """

    if not DEFAULT_INCLUSIONS[mode]:
        raise DomainInvariantError(
            f"{mode.value} includes nothing, so requesting it would refuse to "
            f"generate. A mode qualifies output; it does not gate it."
        )
