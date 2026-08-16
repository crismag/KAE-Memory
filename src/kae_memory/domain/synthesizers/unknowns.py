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

## What ranks a theme, and what does not — yet

Doc 09 asks for ranking by what an unknown *blocks*: blocks definition, blocks
architecture, needed before implementation. That needs a blocking relation
between a question and an area, and **KAE-Memory has none for unknowns** —
`classify_offline` assigns an area only for `actor` and `assumption`, so no
unknown carries one.

So this ranks by what is actually knowable: **how often the project returned to
the question**, and its recorded severity. That is corroboration, not blocking
impact, and every emitted item says so rather than implying an authority the
data cannot support. `SYN-11` is the engine that does it properly, and
`OD-NAV-2` is the same question one layer up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..identifiers import KnowledgeItemId
from .goals import CLUSTER_RADIUS, cluster_by_complete_linkage, medoid

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
    """False while no blocking relation exists. Never silently true."""


def is_current(role: str | None) -> bool:
    """Whether an extracted unknown still counts as unknown.

    `None` means no explicit role, which the evidence model reads as `active`.
    `resolved` and `superseded` mean another source answered it; `noise` means
    it was never a project question. None of the three is a current unknown, and
    all three remain retrievable — this decides what is *asked*, not what is
    kept.
    """

    return role in {None, "active", "supporting", "conflicting"}


def theme_priority(theme: UnknownTheme) -> int:
    """Rank, high first. Corroboration and severity — **not** blocking impact.

    A question the conversation returned to six times is more likely to matter
    than one asked once, and that is the strongest signal the data supports
    today. It is a weaker claim than doc 09 asks for, and the emitted item says
    which claim it is making.
    """

    weight = {"critical": 3, "major": 2, "minor": 1}.get(theme.severity, 1)
    return theme.asked * 10 + weight


def plan_unknowns(
    item_ids: Sequence[KnowledgeItemId],
    questions: Mapping[KnowledgeItemId, str],
    severities: Mapping[KnowledgeItemId, str],
    roles: Mapping[KnowledgeItemId, str | None],
    distance: Callable[[KnowledgeItemId, KnowledgeItemId], float | None],
    *,
    bound: int = ATTENTION_BOUND,
) -> UnknownPlan:
    """Reconcile extracted unknowns into current themes and a bounded queue.

    Pure. Storage, transactions and the evidence graph belong above it.
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
        themes.append(
            UnknownTheme(
                members=members,
                canonical_id=canonical,
                question=questions[canonical],
                severity=severity,
            )
        )

    themes.sort(key=lambda theme: (-theme_priority(theme), str(theme.canonical_id)))
    return UnknownPlan(
        themes=tuple(themes),
        attention=tuple(themes[:bound]),
        resolved=resolved,
        # Stated by the type rather than by a docstring, so a caller that starts
        # ranking by blocking impact has to change this and cannot forget to.
        ranked_by_blocking=False,
    )


def _strongest(severities: set[str]) -> str:
    for grade in ("critical", "major", "minor"):
        if grade in severities:
            return grade
    return "minor"


def explain(theme: UnknownTheme, ranked_by_blocking: bool) -> str:
    """Why this reached a person, in words that do not overclaim.

    Doc 01 requires an attention item to say what it is, why it matters and what
    it affects. The third is exactly what cannot be said honestly yet, so this
    says how the item was chosen instead — which is a smaller claim and a true
    one.
    """

    times = "asked once" if theme.asked == 1 else f"asked {theme.asked} times"
    basis = (
        "ranked by what it blocks"
        if ranked_by_blocking
        else "ranked by how often the project returned to it, not by what it blocks — "
        "KAE cannot yet say which areas depend on an open question"
    )
    asked = f"This is still unresolved and was {times} across the project's evidence."
    return f"{asked} {basis.capitalize()}."
