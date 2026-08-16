"""Assumption synthesis — an interpretation of a conversation is not a project belief.

`05-ASSUMPTIONS.md`: the extracted list *"mixes real project assumptions with LLM
interpretation scaffolding such as uncertainty about whether `KAE` names the
system or whether prior context exists"*, and *"conversation-parsing assumptions
should not become durable project review work."*

Doc 05's own definition is the whole test: a project assumption is *"an uncertain
proposition currently used to reason or plan whose falsity could change project
scope, architecture, requirements, cost, workflow, or outcome."* Read strictly,
that sentence carries the two questions this module answers — **is it about the
project**, and **what would change if it were wrong** — and everything else in
the doc is downstream of them.

## Doc 05's seven lifecycle states are five that already exist (`D-135`)

    working                              →  SynthesizedLifecycle.WORKING
    validated / accepted                 →  SynthesizedLifecycle.AUTHORITATIVE
    superseded                           →  SynthesizedLifecycle.SUPERSEDED
    resolved into established knowledge  →  SynthesizedLifecycle.RESOLVED
    historical                           →  EvidenceRole.HISTORICAL

An `AssumptionLifecycle` holding those words would be a second copy of a state
two vocabularies already hold, free to disagree with either after a rerun
(`D-125`, and `D-123`/`D-134` made the same call for decisions and for epistemic
class). Of the remaining two, **material-needs-validation is derived** — it is
an assumption that is still working, still uncertain and carries a statable
consequence — and **disproven is not produced by anything**: it needs a
contradiction signal no layer in the estate computes, so it is a stated absence
rather than a member nothing can ever hold.

## Scaffolding is separated, and it is already `noise`

An interpretation assumption is classified out, reported by name, and given no
synthesized object — the separation `D-129` made between a principle and a
requirement. Its evidence role is `EvidenceRole.NOISE`, which is doc 17's own
eighth class: `D-134` put noise on the *how this participates in reasoning* axis
precisely because it is not a fact about where the row came from. So the two
rows agree and neither is a copy of the other — `EPI-1` says such a row is
`assumed` (it is an assumption, whoever wrote it), and this module says it is
about the conversation rather than the project.

## Nothing here raises attention

Doc 05: *"Do not preserve stale assumptions as permanent review items."* One
interrupt per unvalidated assumption is the review queue `ADR-0007` exists to
remove, under a new name (`D-125`, for decisions, in the same words). Needing
validation is a **state a reader sorts by**, not an interruption. What would
legitimately interrupt is doc 05's *disproven*, and see above.

Everything here is pure. Storage, the run and the attention items live above.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..synthesis import Authority, EvidenceRole, SynthesizedLifecycle
from .constraints import subject_terms


class ConsequenceDomain(StrEnum):
    """What would change if the assumption turned out to be false.

    Doc 05's six, plus the honest absence of one. `UNDETERMINED` is a real
    answer and the common one: an assumption whose falsity KAE cannot connect to
    anything is doc 05's complaint measured, not a gap to fill by guessing.
    """

    SCOPE = "scope"
    ARCHITECTURE = "architecture"
    REQUIREMENTS = "requirements"
    COST = "cost"
    WORKFLOW = "workflow"
    OUTCOME = "outcome"
    UNDETERMINED = "undetermined"


#: Wordings whose subject is the conversation, the speaker or a name, rather
#: than the project.
#:
#: Doc 05's hygiene question 1, and its three named examples are the shape:
#: whether `KAE` names the system, whether prior context still applies, and
#: whether the speaker means this product. Each is an extractor resolving a
#: reference — a question about reading the transcript, which is answered by
#: reading the transcript and never by the project changing.
_INTERPRETATION: Final = re.compile(
    r"\b(the speaker|the author|this (session|conversation|discussion|thread|"
    r"exchange|transcript)|prior (conversation|context)|earlier (context|"
    r"message|messages)|the name of the (system|product|project)|"
    r"under discussion|referr?(ing|ed|s) to|the same (thing|system|product) as|"
    r"context still applies|mentioned (above|earlier)|what the (user|speaker) "
    r"means)\b",
    re.IGNORECASE,
)

_COST: Final = re.compile(
    r"\b(cost|costs|costly|price|pricing|budget|billing|billed|paid|"
    r"free tier|spend|spending|quota|licence|license|subscription)\b",
    re.IGNORECASE,
)
_ARCHITECTURE: Final = re.compile(
    r"\b(architecture|architectural|component|components|module|modules|"
    r"database|storage|disk|stack|framework|library|runtime|environment|"
    r"deploy\w*|host\w*|infrastructure|platform|protocol|adapter|provider|"
    r"endpoint|api|local[- ]first|offline|machine|server|network)\b",
    re.IGNORECASE,
)
_WORKFLOW: Final = re.compile(
    r"\b(workflow|process|procedure|step|steps|confirm|confirms|confirming|"
    r"review|reviews|approval|approve|approves|sign[- ]?off|decide|decides|"
    r"decision|decisions|interview|interviews|hand[- ]?off)\b",
    re.IGNORECASE,
)
_REQUIREMENTS: Final = re.compile(
    r"\b(requirement|requirements|acceptance|criteria|criterion|specification|"
    r"specified|behaviour|behavior|must|shall)\b",
    re.IGNORECASE,
)
_SCOPE: Final = re.compile(
    r"\b(scope|in scope|out of scope|mvp|release|releases|feature|features|"
    r"milestone|phase|phases|slice|first version|later)\b",
    re.IGNORECASE,
)
_OUTCOME: Final = re.compile(
    r"\b(outcome|outcomes|value|adoption|success|successful|useful|usable|"
    r"usability|trust|quality|satisfaction)\b",
    re.IGNORECASE,
)

#: Ordered most specific first, and `OUTCOME` last deliberately: every one of
#: the other five also changes the outcome, so reading outcome first would
#: swallow the distinctions doc 05 draws between them.
_CONSEQUENCE_ORDER: Final = (
    (_COST, ConsequenceDomain.COST),
    (_ARCHITECTURE, ConsequenceDomain.ARCHITECTURE),
    (_WORKFLOW, ConsequenceDomain.WORKFLOW),
    (_REQUIREMENTS, ConsequenceDomain.REQUIREMENTS),
    (_SCOPE, ConsequenceDomain.SCOPE),
    (_OUTCOME, ConsequenceDomain.OUTCOME),
)


def is_about_the_project(statement: str) -> bool:
    """Doc 05's first hygiene question, as the only thing that separates.

    False means the sentence is about reading the conversation. It does not mean
    the sentence is wrong, and nothing is dropped for it — see `AssumptionModelPlan.scaffolding`.
    """

    return not _INTERPRETATION.search(statement)


def consequence_of(statement: str) -> ConsequenceDomain:
    """What doc 05 says could change if this were false."""

    for pattern, domain in _CONSEQUENCE_ORDER:
        if pattern.search(statement):
            return domain
    return ConsequenceDomain.UNDETERMINED


@dataclass(frozen=True, slots=True)
class AssumptionCandidate:
    """One cluster of assumption evidence, before anything decides what it is.

    ``members`` arrives already clustered, the same as every other synthesizer
    here. Doc 05's consolidation section — account ownership, single-user
    behaviour, collaboration and decision authority becoming *"a coherent
    assumption/decision area"* — is that clustering, and deliberately not a
    lexical grouper in this module: those four corpus sentences share at most one
    content word between any pair, so a word-overlap grouper would produce four
    singletons and read like a working consolidation (`D-135`).
    """

    members: tuple[str, ...]
    """Opaque member keys — the caller's knowledge item ids, as strings."""

    canonical_key: str
    statement: str
    confirmed_by_person: bool = False
    """Whether a person accepted this as established.

    The only thing that plans `authoritative`. Doc 05 separates *validated /
    accepted* from *working* by an act, never by how confidently the sentence is
    worded (`D-123`, `D-129`, `D-132`).
    """


@dataclass(frozen=True, slots=True)
class PlannedAssumption:
    """One project assumption as the model would hold it."""

    candidate: AssumptionCandidate
    consequence: ConsequenceDomain
    lifecycle: SynthesizedLifecycle
    authority: Authority
    needs_validation: bool
    """Doc 05's *material-needs-validation*, derived and stored nowhere.

    True where the assumption is still working and its falsity reaches a named
    consequence domain. An assumption whose consequence is `undetermined` stays
    working knowledge, which is doc 05's fifth hygiene question answered in the
    direction that asks a person for less.
    """

    basis: str


@dataclass(frozen=True, slots=True)
class Separated:
    """A row classified out of the assumption model, with the reason."""

    statement: str
    reason: str
    role: EvidenceRole
    """How the row participates in reasoning instead.

    Carried here rather than left to the caller so that two writers cannot
    choose two different answers for the same finding.
    """


@dataclass(frozen=True, slots=True)
class AssumptionModelPlan:
    """What an assumption synthesis run would write, before it writes anything."""

    assumptions: tuple[PlannedAssumption, ...]

    scaffolding: tuple[Separated, ...]
    """Interpretation assumptions, separated rather than filtered.

    Reported by name because a silent drop is indistinguishable from an
    extractor that never produced them, and doc 05's complaint is precisely that
    nobody can see which rows are which.
    """

    resolved: tuple[Separated, ...]
    """Assumptions the project already knows the answer to.

    Doc 05's third hygiene question, and its *resolved into established
    knowledge* state. Established statements are an input because whether
    something is settled is a fact about the project rather than about the
    sentence (`D-123`).
    """

    needing_validation: tuple[tuple[str, str], ...]
    """Each material assumption and what makes it material.

    A projection of `PlannedAssumption.needs_validation`, not a second source of
    it — the module docstring is explicit that this is a state a reader sorts by
    and never a queue of interruptions.
    """


def _already_established(statement: str, established: Sequence[str]) -> str | None:
    """The established statement that already answers this, if one does.

    Containment, not overlap: the established sentence must speak about
    everything the assumption speaks about. `D-124` measured what a shared-term
    threshold does instead, and a looser rule here would quietly retire an
    assumption the project still holds.
    """

    terms = subject_terms(statement)
    if not terms:
        return None
    for known in established:
        if terms <= subject_terms(known):
            return known
    return None


def plan_assumption_model(
    candidates: Sequence[AssumptionCandidate],
    established: Sequence[str] = (),
) -> AssumptionModelPlan:
    """Turn assumption evidence into project beliefs, with what each one costs if wrong.

    ``established`` are statements the project already settled. Passing none is
    legitimate and means nothing is retired as already-known, which is the safe
    direction: a missed resolution leaves an assumption a person can still see.
    """

    assumptions: list[PlannedAssumption] = []
    scaffolding: list[Separated] = []
    resolved: list[Separated] = []
    needing: list[tuple[str, str]] = []

    for candidate in candidates:
        statement = candidate.statement

        if not is_about_the_project(statement):
            scaffolding.append(
                Separated(
                    statement=statement,
                    reason=(
                        "This is about reading the conversation rather than about the "
                        "project, so its falsity changes nothing a person plans."
                    ),
                    role=EvidenceRole.NOISE,
                )
            )
            continue

        known = _already_established(statement, established)
        if known is not None:
            resolved.append(
                Separated(
                    statement=statement,
                    reason=(
                        f"The project already establishes this: {known!r}. It is knowledge "
                        "rather than an uncertain proposition."
                    ),
                    role=EvidenceRole.RESOLVED,
                )
            )
            continue

        consequence = consequence_of(statement)
        settled = candidate.confirmed_by_person
        needs_validation = not settled and consequence is not ConsequenceDomain.UNDETERMINED

        assumptions.append(
            PlannedAssumption(
                candidate=candidate,
                consequence=consequence,
                lifecycle=(
                    SynthesizedLifecycle.AUTHORITATIVE if settled else SynthesizedLifecycle.WORKING
                ),
                authority=Authority.HUMAN if settled else Authority.WORKING_MODEL,
                needs_validation=needs_validation,
                basis=(
                    "a person accepted this, so it is established rather than assumed"
                    if settled
                    else f"if this is wrong, the project's {consequence.value} changes"
                    if consequence is not ConsequenceDomain.UNDETERMINED
                    else (
                        "nothing in the wording says what would change if this were "
                        "wrong, so it stays working knowledge"
                    )
                ),
            )
        )

        if needs_validation:
            needing.append(
                (
                    statement,
                    f"Its falsity would change the project's {consequence.value}.",
                )
            )

    return AssumptionModelPlan(
        assumptions=tuple(assumptions),
        scaffolding=tuple(scaffolding),
        resolved=tuple(resolved),
        needing_validation=tuple(needing),
    )
