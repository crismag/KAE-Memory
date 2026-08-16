"""What a source is capable of establishing, which is not a ranking of sources.

`EPI-2`, doc 17, `D-148`. Doc 17 is explicit that authority *"must not be reduced
to a universal source ranking"*: source code is strong evidence for what the
system does today and weak evidence for what it should do, and a project owner's
statement is the reverse. So authority attaches to a **claim scope** — five of
them, named in doc 17 — and the same source is authoritative for one and merely
informative for another.

**Nothing here reads a statement.** A claim's scope comes off its
:class:`~kae_memory.domain.models.KnowledgeKind`, the same refusal
:mod:`kae_memory.domain.epistemics` makes in its signature and that `D-129`,
`D-131` and `D-132` each needed a test for. Reading scope off wording would let
the word *must* confer normative authority, which is the failure those three
decisions were each about.
"""

from __future__ import annotations

from enum import StrEnum

from .models import KnowledgeKind, KnowledgeSourceType


class ClaimScope(StrEnum):
    """What a claim is about, which decides who may settle it.

    Doc 17's minimum vocabulary, verbatim in intent: current implementation or
    deployed state, intended or future behaviour, normative policy or legal
    obligation, project decision, external reference or recommendation.
    """

    CURRENT_IMPLEMENTATION = "current_implementation"
    """What the system does or is deployed as today.

    **Unreachable from `KnowledgeKind`, and that is the finding.** No knowledge
    kind says *what the system does now* — a fact read out of a repository is
    extracted as a decision, a constraint or a requirement — so the one row where
    `REPOSITORY` is the authoritative source can never be selected.
    ``test_no_kind_claims_current_implementation`` pins that rather than letting
    the row quietly never fire, the way `EPI-1` pinned its unreachable member.
    """

    INTENDED_BEHAVIOUR = "intended_behaviour"
    """What the project means to do, whether or not anything does it yet."""

    NORMATIVE_POLICY = "normative_policy"
    """A rule or boundary the project is obliged to hold to."""

    PROJECT_DECISION = "project_decision"
    """A choice the project has made, or is being read as having made."""

    EXTERNAL_REFERENCE = "external_reference"
    """Material from outside the project, which is evidence and not intent.

    Also unreachable from `KnowledgeKind`: nothing extracted carries *this came
    from outside*. Retained because doc 17 names it and a vocabulary that omits
    what it cannot express hides the gap instead of reporting it.
    """


class SourceStanding(StrEnum):
    """How much one source type can settle about one scope."""

    AUTHORITATIVE = "authoritative"
    """This source can establish the claim, absent a later one that supersedes it."""

    INFORMATIVE = "informative"
    """Evidence for the claim, and not enough on its own to settle it."""

    NONE = "none"
    """Establishes nothing about the project, whatever the scope.

    Doc 17: *"generated AI text has no independent authority merely because KAE
    generated it."* This agrees with :data:`~kae_memory.domain.epistemics.GROUNDED`
    without copying it — both are read off the source type, and neither stores
    the other's answer.
    """


_SCOPE_BY_KIND: dict[KnowledgeKind, ClaimScope] = {
    KnowledgeKind.DECISION: ClaimScope.PROJECT_DECISION,
    KnowledgeKind.RULE: ClaimScope.NORMATIVE_POLICY,
    KnowledgeKind.CONSTRAINT: ClaimScope.NORMATIVE_POLICY,
    KnowledgeKind.GOAL: ClaimScope.INTENDED_BEHAVIOUR,
    KnowledgeKind.REQUIREMENT: ClaimScope.INTENDED_BEHAVIOUR,
}
"""The kinds that make a claim, and what the claim is about.

`ACTOR` names a participant rather than asserting something the project could be
wrong about; `ASSUMPTION` is provisional by construction, which `EPI-1` already
reads as its epistemic class; `UNKNOWN` is a question and so makes no claim at
all. All three are absent deliberately, and :func:`scope_of` returns ``None`` for
them rather than a scope nobody meant.
"""


_AUTHORITATIVE_FOR: dict[ClaimScope, frozenset[KnowledgeSourceType]] = {
    ClaimScope.CURRENT_IMPLEMENTATION: frozenset({KnowledgeSourceType.REPOSITORY}),
    ClaimScope.INTENDED_BEHAVIOUR: frozenset({KnowledgeSourceType.USER_STATEMENT}),
    ClaimScope.NORMATIVE_POLICY: frozenset({KnowledgeSourceType.USER_STATEMENT}),
    ClaimScope.PROJECT_DECISION: frozenset({KnowledgeSourceType.USER_STATEMENT}),
    ClaimScope.EXTERNAL_REFERENCE: frozenset({KnowledgeSourceType.IMPORTED_DOCUMENT}),
}
"""Which source types can settle which scope. Everything else is informative.

**`IMPORTED_DOCUMENT` settles nothing but external reference, and that is a
measurement rather than caution** (`D-148`). Doc 17's document examples turn on
document *type* — an ADR may settle an architecture decision and a BRD may settle
intended behaviour, while a meeting note settles neither — and
`KnowledgeSourceType` holds **one** member for all three. Sniffing the type off a
filename or the text would be `D-16` in a new place, so the source type is taken
at what it actually distinguishes and the gap is left as a ruling.
"""


def scope_of(kind: str) -> ClaimScope | None:
    """Return what a claim of this kind is about, or ``None`` if it claims nothing.

    Takes the kind as a string because :class:`~kae_memory.domain.models.KnowledgeItem`
    stores it as one, and an unrecognised kind is a claim about nothing rather
    than an error — a vocabulary that raises here would make a new kind an outage
    in the conflict path.
    """

    try:
        known = KnowledgeKind(kind)
    except ValueError:
        return None
    return _SCOPE_BY_KIND.get(known)


def standing(source_type: KnowledgeSourceType, scope: ClaimScope) -> SourceStanding:
    """Return what ``source_type`` can establish about ``scope``."""

    if source_type is KnowledgeSourceType.KAE_INFERENCE:
        return SourceStanding.NONE
    if source_type in _AUTHORITATIVE_FOR[scope]:
        return SourceStanding.AUTHORITATIVE
    return SourceStanding.INFORMATIVE


def best_standing(
    source_types: frozenset[KnowledgeSourceType], scope: ClaimScope
) -> SourceStanding:
    """Return the strongest standing any of a row's sources carries for ``scope``.

    Strongest rather than a consensus: a statement carried by both a repository
    and its owner is established by the owner, and a second weaker source is not
    a reason to doubt the first. A row with no recorded source type stands at
    :attr:`SourceStanding.NONE`, which is `EPI-5b`'s ruling — provenance that
    says nothing grounds nothing — and not a quiet default to informative.
    """

    if not source_types:
        return SourceStanding.NONE
    standings = {standing(source_type, scope) for source_type in source_types}
    if SourceStanding.AUTHORITATIVE in standings:
        return SourceStanding.AUTHORITATIVE
    if SourceStanding.INFORMATIVE in standings:
        return SourceStanding.INFORMATIVE
    return SourceStanding.NONE


def standing_rank(value: SourceStanding) -> int:
    """Order standings so a caller can compare two rows without re-deriving it."""

    return {
        SourceStanding.NONE: 0,
        SourceStanding.INFORMATIVE: 1,
        SourceStanding.AUTHORITATIVE: 2,
    }[value]


__all__ = [
    "ClaimScope",
    "SourceStanding",
    "best_standing",
    "scope_of",
    "standing",
    "standing_rank",
]
