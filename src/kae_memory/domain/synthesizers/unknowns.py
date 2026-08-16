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

The other eight dimensions of `SYN-11` — materiality, urgency, confidence,
conflict, authority, reversibility, information gain, novelty — are not built.
`OD-NAV-2` is the same blocking question one layer up.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from ..area_classification import areas_named_by
from ..clustering import cluster_by_complete_linkage
from ..identifiers import KnowledgeItemId
from ..readiness import SOFTWARE_TEMPLATE, ReadinessTemplate
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
class UnknownTheme:
    """One unresolved question, however many times it was asked."""

    members: tuple[KnowledgeItemId, ...]
    canonical_id: KnowledgeItemId
    question: str
    severity: str

    blocks: tuple[str, ...] = ()
    """Area keys this question names that measured coverage has not reached.

    Empty where the question names no area, where every area it names is already
    ``sufficient``, and — indistinguishably — where the project has no readiness
    snapshot to intersect against. `UnknownPlan.ranked_by_blocking` is what tells
    those apart, which is why it travels with the themes rather than with a
    theme.
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


def blocked_areas(question: str, incomplete_areas: Collection[str]) -> tuple[str, ...]:
    """The areas ``question`` names that measured coverage has not yet reached.

    Naming is not blocking: a question about acceptance criteria in a project
    whose acceptance criteria are already ``sufficient`` is a question the
    project answered somewhere else, and ranking it above one standing in front
    of an empty area would be ranking by wording.
    """

    named = areas_named_by(question)
    return tuple(area for area in named if area in incomplete_areas)


def theme_priority(theme: UnknownTheme) -> int:
    """Rank, high first. What it blocks, then corroboration, then severity.

    Blocking impact leads where it is known — doc 09 asks for exactly that — and
    a theme with an empty `UnknownTheme.blocks` scores as it did before the
    relation existed, so a project with no readiness snapshot is ranked by the
    same function rather than by a second code path.

    Corroboration stays the tie-break: a question the conversation returned to
    six times is more likely to matter than one asked once. It is a weaker claim
    than blocking impact, and the emitted item says which claim it is making.
    """

    weight = {"critical": 3, "major": 2, "minor": 1}.get(theme.severity, 1)
    return len(theme.blocks) * 10_000 + theme.asked * 10 + weight


def plan_unknowns(
    item_ids: Sequence[KnowledgeItemId],
    questions: Mapping[KnowledgeItemId, str],
    severities: Mapping[KnowledgeItemId, str],
    roles: Mapping[KnowledgeItemId, str | None],
    distance: Callable[[KnowledgeItemId, KnowledgeItemId], float | None],
    *,
    bound: int = ATTENTION_BOUND,
    incomplete_areas: Collection[str] | None = None,
) -> UnknownPlan:
    """Reconcile extracted unknowns into current themes and a bounded queue.

    Pure. Storage, transactions and the evidence graph belong above it.

    ``incomplete_areas`` is the set of area keys the project's last readiness
    snapshot records as below ``sufficient``. ``None`` means *no snapshot*, which
    is not the same as *every area covered*: the first cannot rank by blocking
    impact at all, the second ranks by it and finds nothing blocked.
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
        themes.append(
            UnknownTheme(
                members=members,
                canonical_id=canonical,
                question=question,
                severity=severity,
                blocks=(
                    () if incomplete_areas is None else blocked_areas(question, incomplete_areas)
                ),
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
        ranked_by_blocking=incomplete_areas is not None,
    )


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
    is a column value wearing a sentence's clothes.
    """

    times = "asked once" if theme.asked == 1 else f"asked {theme.asked} times"
    if not ranked_by_blocking:
        basis = (
            "ranked by how often the project returned to it, not by what it blocks — "
            "KAE cannot yet say which areas depend on an open question"
        )
    elif theme.blocks:
        areas = ", ".join(area_labels(theme.blocks))
        basis = f"ranked by what it blocks: {areas} {_are(theme.blocks)} not yet covered"
    else:
        basis = (
            "ranked by what it blocks, and it blocks nothing measured — "
            "no area it names is still short of coverage"
        )
    asked = f"This is still unresolved and was {times} across the project's evidence."
    # Upper-cases the first character and nothing else. `str.capitalize()` would
    # lower-case the rest, silently rewriting a label this function was handed
    # rather than composed — harmless while every label is sentence-case, wrong
    # the first time one is not.
    return f"{asked} {basis[0].upper()}{basis[1:]}."


def area_labels(
    keys: Sequence[str], template: ReadinessTemplate = SOFTWARE_TEMPLATE
) -> tuple[str, ...]:
    """The template's human name for each area key, in the order given."""

    names = {area.key: area.name for area in template.areas}
    return tuple(names[key] for key in keys)


def _are(areas: tuple[str, ...]) -> str:
    return "is" if len(areas) == 1 else "are"
