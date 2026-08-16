"""Requirement synthesis — a requirement-shaped sentence is not a requirement.

`06-REQUIREMENTS.md` opens on a list that *"mixes platform requirements, product
principles, positioning, governance, broad capabilities, and duplicates"* and
states the principle this module implements:

    A requirement-like sentence extracted from evidence is not automatically an
    authoritative or implementation-ready requirement.

Two words there are separate claims, and they are kept separate here.

## Authoritative comes from acceptance, never from wording

*Must* and *shall* are the grammar of the sentence somebody wrote down. They are
not evidence that the project agreed to it — the reading `D-125` gave *"we
decided to use PostgreSQL"*, applied to the other half of the same failure. So
``accepted`` is an input.

## Implementation-ready is derived, and KAE does not write the criteria

A requirement is ready when it **is** a requirement, when it says something
observable, and when it carries at least one acceptance criterion. That is a
property computed from the three, not a stored field (`D-125`).

Doc 06's own example turns *"Original source notes must be preserved"* into
criteria covering retrievability, source links, non-destructive updates and
retention. Nothing lexical produces those, and a rule that manufactured them
would make every requirement ready by the act of synthesising it — `ADR-0008`'s
objection exactly. **Criteria arrive as evidence; their absence is the
finding.**

## The mixed list is separated, not filtered

A principle is not a bad requirement, it is not a requirement. Classified out
and reported by name: deleting it loses a real statement, leaving it in is the
pathology doc 06 describes.

## A compound is split, not rejected

*"The product shall support web now and mobile later"* should allow *web MVP,
mobile later*, and doc 06 says in those words that this must not be forced into
binary Confirm/Reject. A compound yields a proposal naming both halves and
applies nothing — `D-126`'s shape.

Everything here is pure. Storage, the run and any surface live above.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kae_memory.domain.area_classification import areas_named_by


class StatementKind(StrEnum):
    """What a requirement-like sentence actually is.

    Only ``REQUIREMENT`` is one. The rest are doc 06's mixed list, named so a
    reader can see what was separated out rather than wondering where it went.
    """

    REQUIREMENT = "requirement"
    PRINCIPLE = "principle"
    POSITIONING = "positioning"
    GOVERNANCE = "governance"
    CAPABILITY_AREA = "capability_area"


class Verifiability(StrEnum):
    """Doc 06's testability analysis, as three outcomes.

    ``COMPOUND`` is not a failure — it is the *Web and mobile* case, and it
    produces a split proposal rather than a verdict.
    """

    OBSERVABLE = "observable"
    COMPOUND = "compound"
    VAGUE = "vague"


#: A sentence about how the product should be, rather than what it must do.
#: Doc 06 lists principles first among the things wrongly in the list.
_PRINCIPLE: Final = re.compile(
    r"\b(principle|philosophy|we believe|should always|by default|"
    r"first[- ]class|never merely|at heart|ethos|values?)\b",
    re.IGNORECASE,
)

#: What the product *is* relative to others. A claim about the market.
_POSITIONING: Final = re.compile(
    r"\b(unlike|competitor\w*|market|positioning|differentiat\w*|"
    r"category|best[- ]in[- ]class|industry[- ]leading|alternative to)\b",
    re.IGNORECASE,
)

#: How the project is run, not what it builds.
_GOVERNANCE: Final = re.compile(
    r"\b(approval|approve[sd]?|sign[- ]?off|governance|policy|process|"
    r"review board|escalat\w*|authority|compliance regime|owner must)\b",
    re.IGNORECASE,
)

#: A heading, not an ask. Doc 06's *broad capabilities* — the level the
#: hierarchy groups **by**, so a statement at that level is a group name.
_CAPABILITY_AREA: Final = re.compile(
    r"^\s*(support for|management of|the \w+ (?:module|area|capability)|"
    r"\w+ management|\w+ support)\s*$",
    re.IGNORECASE,
)

#: Ordered most specific first, for `constraints.py`'s reason: these overlap by
#: construction and the order states which reading governs.
_KIND_ORDER: Final = (
    (_CAPABILITY_AREA, StatementKind.CAPABILITY_AREA),
    (_POSITIONING, StatementKind.POSITIONING),
    (_PRINCIPLE, StatementKind.PRINCIPLE),
    (_GOVERNANCE, StatementKind.GOVERNANCE),
)

#: Something a test could watch happen: an actor doing a thing, or an obligation
#: with an object. Deliberately narrow — `VAGUE` is a reportable state and not
#: an accusation, so a false *vague* costs a sentence in a report and a false
#: *observable* costs a requirement that cannot be built to.
_OBSERVABLE: Final = re.compile(
    r"\b(a user can|users? can|the system (?:must|shall|will)|"
    r"must (?:be|not|never)|shall|becomes?|remains?|returns?|"
    r"is (?:marked|recorded|stored|preserved|shown|reported)|"
    r"are (?:marked|recorded|stored|preserved|shown|reported)|"
    r"propagates?|explains?|summarises|summarizes)\b",
    re.IGNORECASE,
)

#: Two asks in one sentence, over different scopes or subjects. Doc 06's
#: *web now and mobile later* is the canonical one; *X and Y* alone is not,
#: because *preserved and retrievable* is one ask about one thing.
_COMPOUND: Final = re.compile(
    r"\b(\w+)\s+now\s+and\s+(\w+)\s+later\b|"
    r"\b(\w+)\s+first\s*,?\s*(?:then|and then)\s+(\w+)\b",
    re.IGNORECASE,
)


def kind_of(statement: str) -> StatementKind:
    """Which of doc 06's categories the wording carries.

    Defaults to ``REQUIREMENT``: the input is already requirement-like evidence,
    so the job is to name what is *not* one, and an unrecognised sentence is
    left where it was found.
    """

    for pattern, kind in _KIND_ORDER:
        if pattern.search(statement):
            return kind
    return StatementKind.REQUIREMENT


def verifiability_of(statement: str) -> Verifiability:
    """Whether a test could watch this happen."""

    if _COMPOUND.search(statement):
        return Verifiability.COMPOUND
    if _OBSERVABLE.search(statement):
        return Verifiability.OBSERVABLE
    return Verifiability.VAGUE


def _halves(statement: str) -> tuple[str, str] | None:
    match = _COMPOUND.search(statement)
    if match is None:
        return None
    groups = [group for group in match.groups() if group]
    return (groups[0], groups[1]) if len(groups) == 2 else None


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One criterion, as evidence rather than as something KAE wrote.

    See the module docstring: generating these is what would make every
    requirement ready by the act of synthesising it.
    """

    requirement_key: str
    statement: str


@dataclass(frozen=True, slots=True)
class RequirementCandidate:
    """One cluster of requirement-like evidence, before anything decides what it is."""

    members: tuple[str, ...]
    """Opaque member keys — the caller's knowledge item ids, as strings."""

    canonical_key: str
    statement: str
    accepted: bool = False
    """Whether a person accepted this. Wording confers no authority (`D-129`)."""


@dataclass(frozen=True, slots=True)
class SplitProposal:
    """A compound requirement, named in halves and applied to nothing.

    Doc 06: *"should allow scope refinement such as web MVP with mobile later
    rather than forcing binary Confirm/Reject."*
    """

    requirement_key: str
    first: str
    second: str
    basis: str


@dataclass(frozen=True, slots=True)
class PlannedRequirement:
    """One requirement as the model would hold it."""

    candidate: RequirementCandidate
    verifiability: Verifiability
    capability_areas: tuple[str, ...]
    criteria: tuple[str, ...]
    """The criteria that arrived with it. Empty is the common case and the finding."""

    @property
    def implementation_ready(self) -> bool:
        """Observable, accepted, and carrying at least one criterion.

        A property rather than a field: a stored copy of a derived state is free
        to disagree with what it was derived from after a rerun (`D-125`).
        """

        return (
            self.verifiability is Verifiability.OBSERVABLE
            and self.candidate.accepted
            and bool(self.criteria)
        )


@dataclass(frozen=True, slots=True)
class Reclassified:
    """A statement that is not a requirement, kept and named.

    Doc 06's mixed list is separated rather than filtered: deleting a principle
    loses a real statement, and leaving it among the requirements is the failure.
    """

    key: str
    statement: str
    kind: StatementKind


@dataclass(frozen=True, slots=True)
class RequirementModelPlan:
    """What a requirement synthesis run would write, before it writes anything."""

    requirements: tuple[PlannedRequirement, ...]
    reclassified: tuple[Reclassified, ...]
    splits: tuple[SplitProposal, ...]

    @property
    def ready(self) -> tuple[PlannedRequirement, ...]:
        return tuple(one for one in self.requirements if one.implementation_ready)

    @property
    def without_criteria(self) -> tuple[PlannedRequirement, ...]:
        """The ones doc 06's pipeline stops at, which is most of them."""

        return tuple(one for one in self.requirements if not one.criteria)


def plan_requirement_model(
    candidates: Sequence[RequirementCandidate],
    criteria: Sequence[AcceptanceCriterion] = (),
) -> RequirementModelPlan:
    """Turn requirement-like evidence into a requirement model.

    ``criteria`` are acceptance criteria somebody supplied. Passing none is the
    ordinary case and yields a model where nothing is implementation-ready —
    which is doc 06's *candidate review dump* measured rather than disguised.
    """

    by_requirement: dict[str, list[str]] = {}
    for criterion in criteria:
        by_requirement.setdefault(criterion.requirement_key, []).append(criterion.statement)

    requirements: list[PlannedRequirement] = []
    reclassified: list[Reclassified] = []
    splits: list[SplitProposal] = []

    for candidate in candidates:
        kind = kind_of(candidate.statement)
        if kind is not StatementKind.REQUIREMENT:
            reclassified.append(
                Reclassified(
                    key=candidate.canonical_key,
                    statement=candidate.statement,
                    kind=kind,
                )
            )
            continue

        testability = verifiability_of(candidate.statement)
        if testability is Verifiability.COMPOUND and (halves := _halves(candidate.statement)):
            splits.append(
                SplitProposal(
                    requirement_key=candidate.canonical_key,
                    first=halves[0],
                    second=halves[1],
                    basis=(
                        f"one sentence asks for {halves[0]} and {halves[1]} at different "
                        "times, so accepting or rejecting it whole decides both"
                    ),
                )
            )

        requirements.append(
            PlannedRequirement(
                candidate=candidate,
                verifiability=testability,
                capability_areas=areas_named_by(candidate.statement),
                criteria=tuple(by_requirement.get(candidate.canonical_key, ())),
            )
        )

    return RequirementModelPlan(
        requirements=tuple(requirements),
        reclassified=tuple(reclassified),
        splits=tuple(splits),
    )
