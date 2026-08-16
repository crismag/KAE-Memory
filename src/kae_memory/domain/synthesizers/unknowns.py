"""Unknowns reconciled to what is *currently* unknown, and what needs a person.

`09-MATERIAL-UNKNOWNS.md`. The corpus holds 59 unknowns, every one graded
critical, each offered with Confirm/Reject. They are legitimate questions,
semantic duplicates, questions another source already answered, conversation
artefacts, and garbage — presented identically.

## The principle, and it is not a synthesizer detail

> **Unknown-at-extraction-time is not the same as currently unknown.**

An extractor records that a chunk could not answer something. That is a fact
about the chunk. Whether the *project* still does not know it is a different
question, answerable only against everything the project has since learned —
which is why this runs over the reconciled graph rather than over the rows.

## Three gates, in order

**Currency.** Phase 2 already marks an unknown `RESOLVED` when identity evidence
supersedes it (`what-are-we-building` against the project's own identity
statement). A resolved unknown is not a current unknown, and nothing here
resurrects one.

**Consolidation.** Eight wordings of *what does development-ready mean* are one
unresolved theme, not eight questions. Clustering is the same complete-linkage
rule `D-100` measured for goals, over the same statement-space vectors
`D-103` provides, for the same reason: single linkage chains, and a chained
theme is a question nobody asked.

**Materiality.** Only some themes are worth interrupting a person for, and
`ATTENTION_BOUND` is the promise the whole package makes — a project with
thousands of observations may legitimately have a handful of attention items.

## What ranks a theme

Doc 09 asks for ranking by what an unknown *blocks*: blocks definition, blocks
architecture, needed before implementation. `SYN-11a`/`D-149` supplies the
relation, and it is derived rather than invented — a theme's candidate areas are
the ones its wording names (`areas_named_by`, which scores text against the whole
template rather than against the kinds a `unknown` can be filed under, because
`classify_by_content` returns `None` for one by design). Naming an area is not
blocking it: the blocked set is the named areas intersected with the areas the
last readiness snapshot records as **below sufficient**.

Where no snapshot exists there are no area states to intersect against, so
nothing is blocked, `ranked_by_blocking` stays false and the ranking falls back
to what it was — **how often the project returned to the question**, and its
recorded severity, which is corroboration rather than blocking impact. Both
orderings are one function, so a project without readiness ranks exactly as it
did before the relation existed.

**Materiality** — `SYN-11`/`D-152` — is how much of that blocking matters, and it
is derived from the same snapshot rather than invented: every area carries the
weight and the mandatory flag the template gave it when coverage was measured. A
question standing in front of a required area outranks one standing in front of
any number of optional ones, and among equals the heavier area leads.

**Conflict** — `SYN-11`/`D-154` — is the third dimension from the same snapshot:
each area records whether a statement counted toward it is party to an unresolved
contradiction, so a question standing in front of a contested blocked area leads
one standing in front of a quiet area of the same weight. It breaks ties below
materiality and never displaces it. Its limit is that `blocks` holds only areas
below `sufficient`, so a *covered* area that is contradicted is not seen here at
all — conflict as its own attention source is still owed.

**Information gain** — `SYN-11`/`D-157` — is the fourth from the same rows and the
last one they can answer: each area records how many confirmed statements it
holds and how many its minimum asks for, and `evaluate_area` closes an undivided
area at exactly that comparison. A blocked area one statement short of its own
minimum is *one answer away*, and the question in front of it leads one whose
areas would still be short afterwards. A contradicted area is never one answer
away, whatever its shortfall.

**Novelty** — `SYN-11`/`D-160` — is the fifth, and it reads the snapshot's own
instant rather than its rows: a theme first asked *after* coverage was last
measured is one that measurement does not account for. Neither the wall clock nor
KAE's own prior output decides it — the first would reorder the queue while
nothing happened, the second would rank by how many times synthesis had been run.

**Confidence** — `SYN-11`/`D-163` — is the sixth and the only one that reads
nothing about the project: `areas_named_by` scores the wording against the whole
template and discards the score, so a question that named its areas from one weak
signal and one that named them plainly arrived here identical, and every
dimension above is computed on top of that match. The grade is the score read
against the signal table's own weights, it promotes rather than penalises, and it
ranks last before repetition because how well KAE read a sentence must not
displace a fact about the project. The extractor's own `Confidence` is refused as
the source: no deployment sets `KAE_EXTRACTION`, so the offline adapter writes one
literal grade on every item, and it is confidence in a transcription rather than
in the claim being ranked.

The remaining dimensions of `SYN-11` — urgency, authority, reversibility — are
not built, and none of them can read this snapshot.
**Authority is not merely unbuilt, it does not discriminate** (`D-159`): a
question makes no claim, so :func:`~kae_memory.domain.authority.scope_of` returns
``None`` for it, and every scope a `KnowledgeKind` *can* reach is authoritative
for `USER_STATEMENT` alone — so *does this need a person* is uniformly yes for
anything an unknown stands in front of. ``tests/domain/test_authority.py`` pins
that, and it is what will fail on the day it stops being true. `OD-NAV-2` is the
same blocking question one layer up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from ..area_classification import HIGH, LOW, MEDIUM, naming_of
from ..clustering import cluster_by_complete_linkage
from ..identifiers import KnowledgeItemId
from .goals import CLUSTER_RADIUS, medoid

#: How many themes may reach a person from one project.
#:
#: The corpus fixture asserts the same number from the other side. A queue that
#: can grow with evidence is the defect this package exists to remove, so the
#: bound is a constant rather than a percentage.
ATTENTION_BOUND = 8

#: What a person can do about an unresolved question.
#:
#: Doc 01's invariant: *every item surfaced for human attention must provide at
#: least one direct, semantically appropriate path toward resolution, and defer
#: alone does not satisfy it.* These are the gestures the attention API actually
#: has, so the interface cannot offer one the backend will refuse.
UNKNOWN_ACTIONS: tuple[str, ...] = ("answer", "discuss", "defer")


@dataclass(frozen=True, slots=True)
class UncoveredArea:
    """One discovery area a readiness snapshot leaves short of coverage.

    Name, weight and mandatory flag are read off **that snapshot** rather than
    off the current template (`D-152`). A snapshot records the semantics its
    number was computed under, and `ReadinessSnapshot.is_behind_template` exists
    precisely because a project can sit on an older version indefinitely — so
    weighing its coverage with today's template would rank a question by a rule
    its measurement never used.
    """

    key: str
    name: str
    weight: float
    required: bool
    """`AreaDefinition.mandatory`: whether readiness is unreachable without it."""

    contradicted: bool = False
    """Whether a statement counted toward this area is party to an unresolved
    contradiction (`D-154`).

    `AreaResult.contradicted`, recorded by the same calculation that produced the
    state. `ADR-0008` keeps it beside the coverage ladder rather than inside it,
    because short of coverage and internally inconsistent are two facts, and an
    area is routinely both.
    """

    shortfall: int | None = None
    """How many more confirmed statements this area's own minimum asks for
    (`D-157`) — ``minimum_confirmed - confirmed_count``, floored at zero, from the
    same snapshot row.

    ``None`` means the counts were not read, which is not ``0``: zero means the
    count threshold is already met and the area is short for another reason, as
    a divided area is when only one of its claims is established.
    """

    @property
    def one_answer_away(self) -> bool:
        """Whether one more confirmed statement would meet this area's minimum.

        False for a contradicted area whatever the shortfall (`D-157`): an area
        whose statements already disagree is not closed by adding one more, which
        is `D-154`'s claim, and the two must not assert opposite things about the
        same area on the same line.
        """

        return self.shortfall == 1 and not self.contradicted


@dataclass(frozen=True, slots=True)
class UnknownTheme:
    """One unresolved question, however many times it was asked."""

    members: tuple[KnowledgeItemId, ...]
    canonical_id: KnowledgeItemId
    question: str
    severity: str

    blocks: tuple[UncoveredArea, ...] = ()
    """Areas this question names that measured coverage has not reached.

    Ordered as the ranking read them — required first, then heaviest — so the
    sentence a person sees lists them in the order that produced the rank.

    Empty where the question names no area, where every area it names is already
    ``sufficient``, and — indistinguishably — where the project has no readiness
    snapshot to intersect against. `UnknownPlan.ranked_by_blocking` is what tells
    those apart, which is why it travels with the themes rather than with a
    theme.
    """

    named_strength: str | None = None
    """How firmly the wording chose the areas in `blocks` — `D-163`.

    ``None`` where there is nothing to be confident about: the question named no
    area, every area it named is already covered, or the project has no snapshot
    to intersect against. All three mean the same thing here, which is that no
    blocking claim was made, so there is none to grade.
    """

    novel: bool = False
    """Whether this question was first asked after coverage was last measured.

    `D-160`. The comparison is against the readiness snapshot's `calculated_at`
    and against nothing else: the snapshot is the understanding every other
    dimension here is computed against, so a question older than it was already
    standing when that picture was drawn, and a question newer than it is not
    accounted for by it at all. False where the project has no snapshot, and
    false where any member predates it — a question asked again is not new.
    """

    @property
    def asked(self) -> int:
        """How many extracted observations say this. Never a confidence score."""

        return len(self.members)


@dataclass(frozen=True, slots=True)
class UnknownPlan:
    """What one reconciliation run would surface, and what it would not."""

    themes: tuple[UnknownTheme, ...]
    """Every current theme, ranked. Longer than what reaches a person."""

    attention: tuple[UnknownTheme, ...]
    """The themes that become attention items — at most `ATTENTION_BOUND`."""

    resolved: tuple[KnowledgeItemId, ...]
    """Unknowns the evidence graph already answered. Not attention, not lost."""

    ranked_by_blocking: bool
    """Whether measured coverage was available to rank against. Never silently
    true: false means the project has no readiness snapshot, so no theme's
    `UnknownTheme.blocks` could be computed and the order is corroboration."""


def is_current(role: str | None) -> bool:
    """Whether an extracted unknown still counts as unknown.

    `None` means no explicit role, which the evidence model reads as `active`.
    `resolved` and `superseded` mean another source answered it; `noise` means
    it was never a project question. None of the three is a current unknown, and
    all three remain retrievable — this decides what is *asked*, not what is
    kept.
    """

    return role in {None, "active", "supporting", "conflicting"}


def blocked_areas(
    question: str, uncovered_areas: Sequence[UncoveredArea]
) -> tuple[UncoveredArea, ...]:
    """The areas ``question`` names that measured coverage has not yet reached.

    See `naming_strength` for how firmly the question named them, which
    `theme_priority` weighs and this function deliberately does not — the set of
    blocked areas is the same whether the wording chose them faintly or plainly.

    Naming is not blocking: a question about acceptance criteria in a project
    whose acceptance criteria are already ``sufficient`` is a question the
    project answered somewhere else, and ranking it above one standing in front
    of an empty area would be ranking by wording.

    Ordered by consequence — required before optional, heavier before lighter,
    contested before quiet, one answer away before further off, key last so the
    order is stable — because this order is both what ranks the theme and what the
    reader is shown.
    """

    named = set(naming_of(question).areas)
    blocked = [area for area in uncovered_areas if area.key in named]
    blocked.sort(
        key=lambda area: (
            not area.required,
            -area.weight,
            not area.contradicted,
            not area.one_answer_away,
            area.key,
        )
    )
    return tuple(blocked)


#: Ceiling on the corroboration term, so it cannot climb into the band above it.
#:
#: `D-152`: the terms below were bands in intent and not in arithmetic — a theme
#: asked a thousand times outscored a theme that blocks an area, because
#: ``asked * 10`` was free to exceed the blocking band's width. Capping makes two
#: absurdly-repeated themes equally corroborated, which is a claim worth making;
#: promoting repetition above blocking impact silently is not.
CORROBORATION_CEILING = 9_999

#: Ceiling on the materiality term, in hundredths of a weight unit.
#:
#: The same argument one band up (`D-154`): a term with something underneath it
#: has to be bounded or the band beneath it is a claim rather than an
#: arithmetic fact. Ninety-nine weight units of blocked area is far past any
#: template — the software template's ten areas sum to well under it — so the cap
#: is unreachable in practice and the band separation is provable rather than
#: assumed.
MATERIALITY_CEILING = 9_999

#: The most the corroboration term can reach: the capped count, plus severity.
_CORROBORATION_MAX = CORROBORATION_CEILING * 10 + 3

#: The bands, low to high, each computed from the most everything below it can
#: reach rather than chosen (`D-157`).
#:
#: `D-154` predicted that inserting a term underneath materiality would repeat
#: `D-152`'s escape one level up, and it did: there is no room between
#: corroboration's 99,993 and a `CONFLICT_BAND` of 100,000. Deriving each band
#: makes the separation a property of the arithmetic instead of a claim about
#: four literals, so the next dimension moves one line rather than silently
#: overlapping the one beneath it.
CONFIDENCE_BAND = _CORROBORATION_MAX + 1
#: How many grades the confidence term has above `LOW`, which scores nothing.
CONFIDENCE_CEILING = 2
NOVELTY_BAND = CONFIDENCE_BAND * (CONFIDENCE_CEILING + 1)
GAIN_BAND = NOVELTY_BAND * 2
CONFLICT_BAND = GAIN_BAND * 2
MATERIALITY_BAND = CONFLICT_BAND * 2
REQUIRED_BAND = MATERIALITY_BAND * (MATERIALITY_CEILING + 1)


def theme_priority(theme: UnknownTheme) -> int:
    """Rank, high first. What it blocks, how much that weighs, then corroboration.

    Blocking impact leads where it is known — doc 09 asks for exactly that — and
    a theme with an empty `UnknownTheme.blocks` scores as it did before the
    relation existed, so a project with no readiness snapshot is ranked by the
    same function rather than by a second code path.

    **Materiality is layered over blocking rather than beside it** (`D-152`).
    Blocking anything ``required`` outranks blocking any quantity of optional
    areas, because a mandatory area is what makes readiness unreachable while an
    optional one only moves the score; within that, the summed weight the
    template gave those areas decides.

    **Conflict breaks the ties materiality leaves** (`D-154`). An area whose
    statements already disagree cannot be closed by adding one more, so the
    question standing in front of it is worth more attention than one standing in
    front of a quiet area of the same weight. It sits below materiality rather
    than beside it: the weight is what the template records about consequence,
    and contradiction is a condition on what is blocked.

    **Information gain sits directly below conflict** (`D-157`). A blocked area one
    confirmed statement short of its own minimum is one answer away, and asking
    now buys more than asking in front of areas that stay short afterwards. It
    ranks below conflict because what is there being wrong is a stronger claim
    than what is missing being small — and a contradicted area is excluded from
    the term rather than merely outranked by it.

    **Novelty sits directly below information gain** (`D-160`). A question first
    asked after coverage was last measured is one the measurement above it never
    saw. It is the weakest of the five because *not yet accounted for* says
    nothing about consequence, and it still leads repetition, because it is a
    fact about the project's own timeline rather than a count of how many times
    an extractor wrote the same sentence down.

    **Confidence sits directly below novelty** (`D-163`), and it is the only term
    here that is not a fact about the project: it says how firmly the question's
    wording chose the areas every term above was computed from. That is why it is
    last before repetition — a statement about how well KAE read a sentence must
    not displace a statement about the project's state, so it orders only the
    questions everything above it is silent between.

    Corroboration stays the last tie-break: a question the conversation returned
    to six times is more likely to matter than one asked once. It is a weaker
    claim than blocking impact, and the emitted item says which claim it is
    making.
    """

    severity = {"critical": 3, "major": 2, "minor": 1}.get(theme.severity, 1)
    corroboration = min(theme.asked, CORROBORATION_CEILING) * 10 + severity
    confidence = CONFIDENCE_BAND * _CONFIDENCE_GRADES.get(theme.named_strength or "", 0)
    novelty = NOVELTY_BAND if theme.novel else 0
    gain = GAIN_BAND if any(area.one_answer_away for area in theme.blocks) else 0
    conflict = CONFLICT_BAND if any(area.contradicted for area in theme.blocks) else 0
    # Hundredths of a weight unit, so a template expressing weights more finely
    # than the software template's halves still orders correctly.
    materiality = min(round(sum(area.weight for area in theme.blocks) * 100), MATERIALITY_CEILING)
    blocks_required = any(area.required for area in theme.blocks)
    return (
        (REQUIRED_BAND if blocks_required else 0)
        + materiality * MATERIALITY_BAND
        + conflict
        + gain
        + novelty
        + confidence
        + corroboration
    )


#: What each naming grade is worth, `LOW` worth nothing.
#:
#: A promotion and never a penalty (`D-163`): a faintly named claim scores what a
#: theme with no claim at all scores, so a weak match cannot push a question
#: below one the ranking knows nothing about.
_CONFIDENCE_GRADES = {LOW: 0, MEDIUM: 1, HIGH: CONFIDENCE_CEILING}


def plan_unknowns(
    item_ids: Sequence[KnowledgeItemId],
    questions: Mapping[KnowledgeItemId, str],
    severities: Mapping[KnowledgeItemId, str],
    roles: Mapping[KnowledgeItemId, str | None],
    distance: Callable[[KnowledgeItemId, KnowledgeItemId], float | None],
    *,
    bound: int = ATTENTION_BOUND,
    uncovered_areas: Sequence[UncoveredArea] | None = None,
    first_asked: Mapping[KnowledgeItemId, datetime] | None = None,
    measured_at: datetime | None = None,
) -> UnknownPlan:
    """Reconcile extracted unknowns into current themes and a bounded queue.

    Pure. Storage, transactions and the evidence graph belong above it.

    ``uncovered_areas`` are the areas the project's last readiness snapshot
    records as below ``sufficient``, carrying that snapshot's own weights.
    ``None`` means *no snapshot*, which is not the same as *every area covered*:
    the first cannot rank by blocking impact at all, the second ranks by it and
    finds nothing blocked.

    ``first_asked`` and ``measured_at`` come from that same read — when each
    observation was written, and when the snapshot was calculated. They decide
    novelty (`D-160`) and are optional together: without the instant there is
    nothing to compare against, and claiming novelty from a clock reading taken
    now would reorder the queue between two runs over identical evidence.
    """

    resolved = tuple(item for item in item_ids if not is_current(roles.get(item)))
    current = [item for item in item_ids if is_current(roles.get(item))]

    themes: list[UnknownTheme] = []
    for members in cluster_by_complete_linkage(current, distance, radius=CLUSTER_RADIUS):
        canonical = medoid(members, distance)
        # The theme's severity is the strongest any member carries. A question
        # asked once as critical and five times as minor is still critical: the
        # grade is about consequence, and averaging it would let repetition
        # dilute a real one.
        severity = _strongest({severities.get(member, "minor") for member in members})
        question = questions[canonical]
        blocks = () if uncovered_areas is None else blocked_areas(question, uncovered_areas)
        themes.append(
            UnknownTheme(
                members=members,
                canonical_id=canonical,
                question=question,
                severity=severity,
                blocks=blocks,
                named_strength=naming_strength(question) if blocks else None,
                novel=_is_novel(members, first_asked, measured_at),
            )
        )

    themes.sort(key=lambda theme: (-theme_priority(theme), str(theme.canonical_id)))
    return UnknownPlan(
        themes=tuple(themes),
        attention=tuple(themes[:bound]),
        resolved=resolved,
        # Read off the input rather than asserted: the ranking is by blocking
        # impact exactly when there were measured area states to intersect
        # against, so the flag cannot drift from what the sort actually did.
        ranked_by_blocking=uncovered_areas is not None,
    )


def naming_strength(question: str) -> str | None:
    """How firmly ``question``'s wording chose the areas it names (`D-163`).

    The grade the area classifier already computed and threw away. ``None`` where
    the question names no area at all, which is not a weak match but the absence
    of one.
    """

    return naming_of(question).strength


def _is_novel(
    members: Sequence[KnowledgeItemId],
    first_asked: Mapping[KnowledgeItemId, datetime] | None,
    measured_at: datetime | None,
) -> bool:
    """Whether every wording of this question was written after ``measured_at``.

    `D-160`. A member with no recorded time makes the theme not novel rather than
    novel: the claim is that the measurement never saw this question, and a
    missing timestamp is not evidence for it.
    """

    if measured_at is None or not first_asked:
        return False
    times = [first_asked.get(member) for member in members]
    if any(time is None for time in times):
        return False
    return min(time for time in times if time is not None) > measured_at


def _strongest(severities: set[str]) -> str:
    for grade in ("critical", "major", "minor"):
        if grade in severities:
            return grade
    return "minor"


def explain(theme: UnknownTheme, ranked_by_blocking: bool) -> str:
    """Why this reached a person, in words that do not overclaim.

    Doc 01 requires an attention item to say what it is, why it matters and what
    it affects. The third is answered only where the ranking answered it: with a
    readiness snapshot the sentence names the areas standing behind the question,
    and without one it says how the item was chosen instead — the smaller claim,
    and the true one there.

    An area is named by the template's word for it and never by its key
    (`D-151`): this string is read on an attention card, and `acceptance_criteria`
    is a column value wearing a sentence's clothes. An area readiness does not
    require says so (`D-152`), because *"Delivery and operational context is not
    yet covered"* otherwise reads as something the project cannot proceed
    without, which the template denies. A question newer than that measurement
    says so too (`D-160`), because it changes what the rest of the sentence is
    worth: the areas were weighed by a picture drawn before it was asked.
    """

    times = "asked once" if theme.asked == 1 else f"asked {theme.asked} times"
    if not ranked_by_blocking:
        basis = (
            "ranked by how often the project returned to it, not by what it blocks — "
            "KAE cannot yet say which areas depend on an open question"
        )
    elif theme.blocks:
        areas = ", ".join(area_phrase(area) for area in theme.blocks)
        basis = f"ranked by what it blocks: {areas} {_are(theme.blocks)} not yet covered"
        # `D-163`. Said only where the match was faint, because that is where it
        # changes what the reader should conclude: the areas above were matched
        # from a single weak signal in the wording, so the list may be wrong.
        if theme.named_strength == LOW:
            basis += f", though the question's wording matches {_them(theme.blocks)} only faintly"
    else:
        basis = (
            "ranked by what it blocks, and it blocks nothing measured — "
            "no area it names is still short of coverage"
        )
    # `D-160`. Said only where it is true, and said as what it is: the last
    # coverage measurement predates the question, so the areas named above were
    # weighed by a picture drawn before anybody asked this.
    if theme.novel:
        basis += ", and it was first asked after coverage was last measured"
    asked = f"This is still unresolved and was {times} across the project's evidence."
    # Upper-cases the first character and nothing else. `str.capitalize()` would
    # lower-case the rest, silently rewriting a label this function was handed
    # rather than composed — harmless while every label is sentence-case, wrong
    # the first time one is not.
    return f"{asked} {basis[0].upper()}{basis[1:]}."


def area_phrase(area: UncoveredArea) -> str:
    """How one blocked area is said in a sentence somebody reads.

    A qualifier appears only where it changes what the reader should conclude: an
    area readiness does not require (`D-152`), one whose statements already
    disagree (`D-154`) — because it says why the area is not closed by one more
    answer — and one that is a single confirmed statement short of what it asks
    for (`D-157`), which is the opposite condition and never appears beside it.

    The shortfall is said as a distance to the area's own minimum and never as a
    promise about this question: KAE cannot know that an answer here would be
    filed as a statement counting toward that area.
    """

    qualifiers = []
    if not area.required:
        qualifiers.append("not required for readiness")
    if area.contradicted:
        qualifiers.append("statements there already contradict each other")
    if area.one_answer_away:
        qualifiers.append("one confirmed statement short of what it asks for")
    if not qualifiers:
        return area.name
    return f"{area.name} ({', and '.join(qualifiers)})"


def _are(areas: tuple[UncoveredArea, ...]) -> str:
    return "is" if len(areas) == 1 else "are"


def _them(areas: tuple[UncoveredArea, ...]) -> str:
    return "it" if len(areas) == 1 else "them"
