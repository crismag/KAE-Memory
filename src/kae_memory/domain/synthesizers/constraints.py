"""Constraint synthesis — a boundary is worth having for what it settles.

`07-CONSTRAINTS.md`: constraints *"are useful because of the consequences they
impose, not because they are sentences to Confirm/Reject."* So the spine of this
module is not the family taxonomy. It is the relation:

    Constraint  ×  Open item  →  Effect

Doc 07's own example is the acceptance case: *"team collaboration is outside
MVP"* should resolve or narrow related unknowns and assumptions about MVP
collaboration, rather than sit beside them as one more sentence.

## Only an accepted constraint propagates

Doc 07: *"Accepted constraints must influence the rest of the model."* The
converse is the part that matters here — an extracted sentence that nobody has
accepted must not narrow anybody's open questions, because being wrong about a
boundary silently closes a question the project still has. An unaccepted
constraint's effects are still computed, and reported as what would follow.

## An effect never closes anything

`Effect` carries no lifecycle and no status. It says a constraint bears on an
item and why; what a resolved unknown becomes is the attention model's, and
doc 07 lists *Add exception* and *Change scope* beside *Accept* precisely
because a boundary can be revised.

## The relation is lexical, and that is its floor (`D-124`)

Shared subject terms reach doc 07's own example and stop well short of the
corpus's tagged set: *"Will more than one person confirm decisions in the first
release?"* is a question about collaboration in MVP that shares no term with the
constraint that answers it. That gap is `SYN-3a`'s vector neighbourhood, not a
wider word list — a lexicon tuned until the tagged rows pass is `D-16`.

Everything here is pure. Storage, the run and the attention items live above.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ConstraintFamily(StrEnum):
    """Doc 07's eight families, plus the honest absence of one."""

    SCOPE_RELEASE = "scope_release"
    TECHNICAL = "technical"
    ARCHITECTURAL = "architectural"
    ORGANIZATIONAL = "organizational"
    UX_WORKFLOW = "ux_workflow"
    DATA_INTEGRITY = "data_integrity"
    SECURITY_REGULATORY = "security_regulatory"
    OPERATIONAL = "operational"
    UNCLASSIFIED = "unclassified"


class EffectKind(StrEnum):
    """What a constraint does to an open item.

    ``RESOLVES`` where the constraint speaks about everything the item asks
    about; ``NARROWS`` where it speaks about part of it. Neither closes the
    item — see the module docstring.
    """

    RESOLVES = "resolves"
    NARROWS = "narrows"


#: Wordings that make a statement a boundary rather than a description.
#:
#: A constraint that excludes, forbids or defers is the kind that bears on an
#: open question. *"The system uses PostgreSQL"* restricts nothing by itself.
_BOUNDARY: Final = re.compile(
    r"\b(outside|out of scope|not in scope|excluded|exclude[sd]?|must not|"
    r"may not|cannot|can't|never|no longer|without|beyond|limited to|"
    r"only|at most|until after|after mvp|wait until|deferred|postponed)\b",
    re.IGNORECASE,
)

_SECURITY: Final = re.compile(
    r"\b(security|secure|auth|authentication|authorisation|authorization|"
    r"credential|credentials|secret|secrets|token|tokens|encrypt\w*|"
    r"regulator\w*|complian\w*|gdpr|privacy|personal data|audit)\b",
    re.IGNORECASE,
)
_DATA: Final = re.compile(
    r"\b(data|content|record|records|retention|retain\w*|delete\w*|"
    r"integrity|provenance|altered|alter|immutable|backup|backups|archive)\b",
    re.IGNORECASE,
)
_ARCHITECTURAL: Final = re.compile(
    r"\b(architecture|architectural|component|components|module|modules|"
    r"boundary|boundaries|layer|layers|coupling|dependency|dependencies|"
    r"protocol|interface|contract)\b",
    re.IGNORECASE,
)
_TECHNICAL: Final = re.compile(
    r"\b(platform|browser|browsers|language|runtime|database|postgres\w*|"
    r"python|typescript|version|versions|library|framework|hardware|memory|"
    r"model|models|offline|local[- ]first)\b",
    re.IGNORECASE,
)
_OPERATIONAL: Final = re.compile(
    r"\b(deploy\w*|host\w*|uptime|availability|monitor\w*|operat\w*|"
    r"backup window|maintenance|rollout|environment)\b",
    re.IGNORECASE,
)
_ORGANIZATIONAL: Final = re.compile(
    r"\b(team|teams|budget|cost|costs|resource|resources|headcount|"
    r"staff|contractor|contractors|licence|license|vendor)\b",
    re.IGNORECASE,
)
_UX_WORKFLOW: Final = re.compile(
    r"\b(wizard|progression|navigation|step|steps|flow|onboarding|"
    r"rigid|sequence|screen|screens|form|forms|interaction)\b",
    re.IGNORECASE,
)
_SCOPE_RELEASE: Final = re.compile(
    r"\b(scope|mvp|release|releases|milestone|phase|first version|"
    r"out of scope|later|feature set)\b",
    re.IGNORECASE,
)

#: Ordered most specific first. Doc 07's families overlap by construction — a
#: retention rule is also technical — so the order states which reading governs
#: when two fire, and the specific one does.
_FAMILY_ORDER: Final = (
    (_SECURITY, ConstraintFamily.SECURITY_REGULATORY),
    (_DATA, ConstraintFamily.DATA_INTEGRITY),
    (_UX_WORKFLOW, ConstraintFamily.UX_WORKFLOW),
    (_ARCHITECTURAL, ConstraintFamily.ARCHITECTURAL),
    (_OPERATIONAL, ConstraintFamily.OPERATIONAL),
    (_SCOPE_RELEASE, ConstraintFamily.SCOPE_RELEASE),
    (_ORGANIZATIONAL, ConstraintFamily.ORGANIZATIONAL),
    (_TECHNICAL, ConstraintFamily.TECHNICAL),
)

#: Words that carry no subject, so two statements sharing only these share nothing.
_NOISE: Final = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "in",
        "on",
        "at",
        "of",
        "for",
        "to",
        "from",
        "with",
        "without",
        "by",
        "and",
        "or",
        "but",
        "not",
        "no",
        "it",
        "its",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "we",
        "our",
        "us",
        "you",
        "your",
        "they",
        "their",
        "he",
        "she",
        "his",
        "her",
        "do",
        "does",
        "did",
        "done",
        "will",
        "would",
        "should",
        "shall",
        "may",
        "might",
        "must",
        "can",
        "could",
        "have",
        "has",
        "had",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "how",
        "if",
        "then",
        "than",
        "so",
        "as",
        "up",
        "out",
        "into",
        "over",
        "under",
        "more",
        "most",
        "less",
        "least",
        "one",
        "two",
        "any",
        "all",
        "some",
        "each",
        "every",
        "other",
        "still",
        "yet",
        "also",
        "only",
        "just",
        "about",
        "before",
        "after",
        "until",
        "during",
        "while",
        "outside",
        "inside",
        "within",
    ]
)


_WORD: Final = re.compile(r"[a-z][a-z0-9'-]*")

#: Below this, two statements share a common word rather than a subject.
_SHARED_TERMS_FOR_NARROWING: Final = 2


def family_of(statement: str) -> ConstraintFamily:
    """Which of doc 07's families the wording carries."""

    for pattern, family in _FAMILY_ORDER:
        if pattern.search(statement):
            return family
    return ConstraintFamily.UNCLASSIFIED


def is_boundary(statement: str) -> bool:
    """Whether the statement restricts anything, rather than describing it."""

    return bool(_BOUNDARY.search(statement))


def subject_terms(statement: str) -> frozenset[str]:
    """The content words a statement is about."""

    return frozenset(word for word in _WORD.findall(statement.casefold()) if word not in _NOISE)


@dataclass(frozen=True, slots=True)
class ConstraintCandidate:
    """One cluster of constraint evidence, before anything decides what it is."""

    members: tuple[str, ...]
    """Opaque member keys — the caller's knowledge item ids, as strings."""

    canonical_key: str
    statement: str
    accepted: bool = False
    """Whether a person accepted this boundary.

    Doc 07 propagates *accepted* constraints. An unaccepted one's effects are
    reported as what would follow, and change nothing.
    """


@dataclass(frozen=True, slots=True)
class OpenItem:
    """An unknown or assumption a constraint might bear on."""

    key: str
    statement: str


@dataclass(frozen=True, slots=True)
class Effect:
    """A constraint bearing on one open item, with the reason.

    Carries no status. Doc 07 lists *Add exception* and *Change scope* beside
    *Accept*, so an effect is an argument about an item and never a verdict on
    it.
    """

    constraint_key: str
    item_key: str
    kind: EffectKind
    basis: str


@dataclass(frozen=True, slots=True)
class PlannedConstraint:
    """One constraint as the model would hold it."""

    candidate: ConstraintCandidate
    family: ConstraintFamily
    restricts: bool


@dataclass(frozen=True, slots=True)
class ConstraintModelPlan:
    """What a constraint synthesis run would write, before it writes anything."""

    constraints: tuple[PlannedConstraint, ...]

    effects: tuple[Effect, ...]
    """What accepted boundaries bear on. Doc 07's *design forces*."""

    proposed_effects: tuple[Effect, ...]
    """What would follow if the unaccepted boundaries were accepted.

    Reported rather than applied, and reported rather than hidden: the evidence
    already claims the boundary, and what it would settle is the argument for
    looking at it.
    """


def _effect_between(constraint: ConstraintCandidate, item: OpenItem) -> Effect | None:
    constraint_terms = subject_terms(constraint.statement)
    item_terms = subject_terms(item.statement)
    if not item_terms:
        return None
    shared = constraint_terms & item_terms
    if item_terms <= constraint_terms:
        return Effect(
            constraint_key=constraint.canonical_key,
            item_key=item.key,
            kind=EffectKind.RESOLVES,
            basis=(
                "the constraint speaks about everything this asks about, so it "
                "answers it rather than bounding it"
            ),
        )
    if len(shared) >= _SHARED_TERMS_FOR_NARROWING:
        return Effect(
            constraint_key=constraint.canonical_key,
            item_key=item.key,
            kind=EffectKind.NARROWS,
            basis=f"both are about {', '.join(sorted(shared))}",
        )
    return None


def plan_constraint_model(
    candidates: Sequence[ConstraintCandidate],
    open_items: Sequence[OpenItem] = (),
) -> ConstraintModelPlan:
    """Turn constraint evidence into boundaries and the effects they impose.

    ``open_items`` are the unknowns and assumptions a boundary might bear on.
    Passing none is legitimate and yields a family model with no effects, which
    is doc 07's *isolated duplicate sentence* stated rather than disguised.
    """

    planned: list[PlannedConstraint] = []
    effects: list[Effect] = []
    proposed: list[Effect] = []

    for candidate in candidates:
        restricts = is_boundary(candidate.statement)
        planned.append(
            PlannedConstraint(
                candidate=candidate,
                family=family_of(candidate.statement),
                restricts=restricts,
            )
        )
        if not restricts:
            continue
        for item in open_items:
            effect = _effect_between(candidate, item)
            if effect is None:
                continue
            (effects if candidate.accepted else proposed).append(effect)

    return ConstraintModelPlan(
        constraints=tuple(planned),
        effects=tuple(effects),
        proposed_effects=tuple(proposed),
    )
