"""Decision synthesis — a proposal and an authoritative choice are not the same row.

`08-DECISIONS.md`: items labelled `Decision` are today *"simultaneously
`proposed, not confirmed` and `to decide`"*. That is one object carrying two
states, and it is why a decision reads as another extracted sentence with a
confirmation flag rather than as a project choice.

## One lifecycle, and it already exists (`D-123`)

Doc 08's five stages map onto `SynthesizedLifecycle` rather than onto a second
enum beside it:

    Proposed / Discussed  →  working          KAE's current reading
    Accepted / Active     →  authoritative    what a person settled
    Superseded / Revoked  →  superseded

A `DecisionLifecycle` holding the five words would be a second state for one
object, which is the pathology. `SynthesizedObject` already refuses
`authoritative` without `Authority.HUMAN`, so the promotion rule is enforced
below this module whatever a plan says.

## Wording never promotes

*"We decided to use Postgres"* is a sentence claiming a decision happened. Only
the evidence's own confirmation — a person's act — plans `authoritative`.
Doc 08's closing sentence read strictly: a decision is *"not merely another
extracted sentence carrying a confirmation flag"*, so the flag is necessary and
the wording is never sufficient.

## Session scope is a field, not a class

Doc 08 lists *temporary/session decision* beside the five subject classes.
Modelled as a class it would erase what the decision is about: *"in this
session, skip architecture"* is a workflow decision made at session scope. So
scope is orthogonal, and it carries doc 08's own invariant — *"temporary
workflow decisions should not silently become permanent project governance"* —
by refusing the promotion outright.

Everything here is pure. Storage, the run and the attention items live above.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..readiness import SOFTWARE_TEMPLATE, ReadinessTemplate
from ..synthesis import Authority, SynthesizedLifecycle


class DecisionClass(StrEnum):
    """What a decision is about — doc 08's classes, with session held separately.

    ``unclassified`` is a real answer. A decision whose wording names no subject
    is still a decision, and guessing a class would file a throwaway choice as
    architecture.
    """

    PRODUCT_SCOPE = "product_scope"
    ARCHITECTURE = "architecture"
    GOVERNANCE = "governance"
    PLANNING = "planning"
    WORKFLOW = "workflow"
    UNCLASSIFIED = "unclassified"


class EffectiveScope(StrEnum):
    """How far a decision reaches — doc 08's *effective scope*."""

    PROJECT = "project"
    SESSION = "session"


#: How we are working right now, rather than what the project is.
#:
#: Checked first, and that ordering is the point: *"in this session, skip
#: architecture and stay on requirements"* names architecture and decides
#: nothing about it. The verb says what kind of decision it is; the noun is what
#: the verb is aimed at.
_WORKFLOW: Final = re.compile(
    r"\b(skip|skipp\w+|stay on|focus on|come back to|park|set aside|defer|"
    r"revisit|confirm|confirms|reject|rejects|triage|queue|workflow|process|"
    r"procedure|step|steps|walk through|work through|order of work)\b",
    re.IGNORECASE,
)

#: How the thing is built and run.
_ARCHITECTURE: Final = re.compile(
    r"\b(architecture|architectural|component|components|module|modules|"
    r"database|storage|schema|stack|framework|library|runtime|environment|"
    r"execution|deployment|deploy|infrastructure|protocol|transport|adapter|"
    r"provider|endpoint|api|local[- ]first|offline|hosted|self[- ]hosted)\b",
    re.IGNORECASE,
)

#: What the product is and is not.
_PRODUCT_SCOPE: Final = re.compile(
    r"\b(scope|in scope|out of scope|mvp|feature|features|capability|"
    r"capabilities|product|user[- ]facing|include|includes|exclude|excludes|"
    r"drop|support for|not support)\b",
    re.IGNORECASE,
)

#: When, in what order, and against what stage.
_PLANNING: Final = re.compile(
    r"\b(stage|stages|milestone|milestones|release|releases|phase|phases|"
    r"schedule|scheduled|timeline|deadline|sprint|iteration|first release|"
    r"current stage|later stage)\b",
    re.IGNORECASE,
)

#: Who may decide, and what a decision binds.
#:
#: Checked last (`D-123`). Reading a process instruction as governance
#: manufactures authority the evidence never claimed, which is the failure doc
#: 08 names; reading governance as process understates it and creates none.
_GOVERNANCE: Final = re.compile(
    r"\b(authority|authorities|governance|policy|policies|permission|"
    r"permissions|sign[- ]?off|accountable|may not|must not|may override|"
    r"override|ownership|owns|entitled|mandate|mandated|binding)\b",
    re.IGNORECASE,
)

#: Wordings that bound a decision to the conversation it was made in.
_SESSION: Final = re.compile(
    r"\b(in this session|this session|for now|right now|today|temporar\w+|"
    r"for the moment|just for now|during this conversation|meanwhile)\b",
    re.IGNORECASE,
)

#: Wordings that declare an area finished enough for the current stage.
_SUFFICIENCY: Final = re.compile(
    r"\b(sufficiently (defined|resolved|covered|specified)|"
    r"(is|are) sufficient|good enough|enough for now|"
    r"(complete|closed|settled|done) for (the |this )?(current |now)?stage)\b",
    re.IGNORECASE,
)

#: Words carrying no subject on their own, so an area key is never matched by them.
_KEY_STOPWORDS: Final = frozenset({"and", "or", "of", "the", "a", "an"})

_CLASS_ORDER: Final = (
    (_WORKFLOW, DecisionClass.WORKFLOW),
    (_ARCHITECTURE, DecisionClass.ARCHITECTURE),
    (_PRODUCT_SCOPE, DecisionClass.PRODUCT_SCOPE),
    (_PLANNING, DecisionClass.PLANNING),
    (_GOVERNANCE, DecisionClass.GOVERNANCE),
)


def class_of(statement: str) -> DecisionClass:
    """Which of doc 08's classes the wording carries.

    Ordered so the least-claiming reading wins where two fire — see `D-123`.
    """

    for pattern, decision_class in _CLASS_ORDER:
        if pattern.search(statement):
            return decision_class
    return DecisionClass.UNCLASSIFIED


def scope_of(statement: str) -> EffectiveScope:
    """Whether the decision binds the project or only the conversation."""

    return EffectiveScope.SESSION if _SESSION.search(statement) else EffectiveScope.PROJECT


def area_declared_sufficient(
    statement: str, template: ReadinessTemplate = SOFTWARE_TEMPLATE
) -> str | None:
    """The readiness area this statement declares finished, or ``None``.

    Two conditions, both required: the statement says *sufficient*, and it names
    exactly one area. The area is matched on the template's own key words rather
    than through `areas_named_by`, which scores subject-matter signals — a
    sufficiency declaration names its area by title, and widening those shared
    signals to catch four fixture rows is `D-16`.
    """

    if not _SUFFICIENCY.search(statement):
        return None
    lowered = statement.casefold()
    named = [
        area.key
        for area in template.areas
        if all(
            re.search(rf"\b{re.escape(word)}\b", lowered)
            for word in area.key.split("_")
            if word not in _KEY_STOPWORDS
        )
    ]
    return named[0] if len(named) == 1 else None


@dataclass(frozen=True, slots=True)
class DecisionCandidate:
    """One cluster of decision evidence, before anything decides what it is."""

    members: tuple[str, ...]
    """Opaque member keys — the caller's knowledge item ids, as strings."""

    canonical_key: str
    statement: str
    confirmed_by_person: bool = False
    """Whether the evidence carries a person's confirmation.

    The only thing that can plan `authoritative`. Wording cannot (`D-123`).
    """


@dataclass(frozen=True, slots=True)
class PlannedDecision:
    """One decision as the model would hold it, with the reason for its state."""

    candidate: DecisionCandidate
    decision_class: DecisionClass
    scope: EffectiveScope
    lifecycle: SynthesizedLifecycle
    authority: Authority
    basis: str


@dataclass(frozen=True, slots=True)
class DecisionModelPlan:
    """What a decision synthesis run would write, before it writes anything."""

    decisions: tuple[PlannedDecision, ...]

    awaiting: tuple[tuple[str, str], ...]
    """Decisions nobody has settled, each with what is being asked.

    Derived from the lifecycle rather than stored beside it, which is what makes
    doc 08's *proposed and to decide at once* unrepresentable here.
    """

    conflicts: tuple[tuple[str, str], ...]
    """Accepted decisions contradicted by the project's own state.

    Doc 08: new evidence conflicting with an accepted decision *"must trigger
    conflict analysis, not silently create parallel contradictory records"*.
    """

    session_scoped: tuple[tuple[str, str], ...]
    """Decisions refused permanence, each with the reason.

    Reported rather than dropped: the evidence said a choice was made, and
    hiding it is how a temporary decision quietly becomes governance.
    """


def plan_decision_model(
    candidates: Sequence[DecisionCandidate],
    open_proposals_by_area: Mapping[str, int] | None = None,
) -> DecisionModelPlan:
    """Turn decision evidence into a model of choices, proposals and conflicts.

    ``open_proposals_by_area`` is doc 08's area-sufficiency check: a decision
    declaring an area finished while that area still holds undecided candidates
    is a conflict for a person. It is an input because it is a fact about the
    project, not about the sentence.
    """

    open_proposals = open_proposals_by_area or {}
    decisions: list[PlannedDecision] = []
    awaiting: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    session_scoped: list[tuple[str, str]] = []

    for candidate in candidates:
        statement = candidate.statement
        scope = scope_of(statement)
        settled = candidate.confirmed_by_person and scope is EffectiveScope.PROJECT

        if candidate.confirmed_by_person and scope is EffectiveScope.SESSION:
            session_scoped.append(
                (
                    statement,
                    "The wording binds this to the current session, so a confirmation "
                    "settles it for now and not for the project.",
                )
            )
        elif scope is EffectiveScope.SESSION:
            session_scoped.append(
                (
                    statement,
                    "The wording binds this to the current session, so it never "
                    "becomes project governance and never asks for a decision.",
                )
            )

        decisions.append(
            PlannedDecision(
                candidate=candidate,
                decision_class=class_of(statement),
                scope=scope,
                lifecycle=(
                    SynthesizedLifecycle.AUTHORITATIVE if settled else SynthesizedLifecycle.WORKING
                ),
                authority=Authority.HUMAN if settled else Authority.WORKING_MODEL,
                basis=(
                    "a person confirmed this evidence, so it is the project's choice"
                    if settled
                    else "nobody has settled this, so it is the working model's reading"
                ),
            )
        )

        if settled:
            area = area_declared_sufficient(statement)
            if area is not None and open_proposals.get(area, 0) > 0:
                conflicts.append(
                    (
                        statement,
                        f"{area} still holds {open_proposals[area]} undecided candidates, "
                        "so the project's state contradicts this accepted decision.",
                    )
                )
            continue

        if scope is EffectiveScope.PROJECT:
            awaiting.append(
                (
                    statement,
                    "Evidence proposes this and nobody has accepted it, so it is "
                    "KAE's reading until somebody settles it.",
                )
            )

    return DecisionModelPlan(
        decisions=tuple(decisions),
        awaiting=tuple(awaiting),
        conflicts=tuple(conflicts),
        session_scoped=tuple(session_scoped),
    )
