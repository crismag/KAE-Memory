"""Goal synthesis — 47 extracted sentences to a model a person can hold.

`02-GOALS-SYNTHESIS.md`: a goal is a relatively stable, high-level desired
outcome. The corpus holds 47 goal-shaped observations that are semantic
duplicates, misclassified requirements, conversation-local instructions, and one
piece of deliberate garbage. A flat Confirm/Reject list is not a goal model.

## Clustering is complete linkage, and that is measured (`D-100`)

`EM-3` was blocked because `D-76` found cosine still merged 26 of 88 statements
into one group at every threshold. That is **single-link chaining**, and it
reproduces here: on real `mxbai-embed-large` vectors, single linkage at radius
0.45 puts **46 of 47 goals in one cluster**. Complete linkage at the same radius
produces 19, with the six `planning-expertise` paraphrases in a cluster of
exactly six and no cluster mixing two regression cases.

Complete linkage *is* a diameter cap: two clusters merge only when **every**
cross pair is within the radius, so a chain of near-neighbours cannot drag
unrelated statements together. It prefers splitting to merging, which is the
safe direction — a wrongly split goal is visible and correctable, a wrongly
merged one has already destroyed the distinction.

## Membership is judged, and that is also measured (`D-101`)

Three deterministic exclusion rules were tried against the fixture and each
failed. Frequency promotes `hold-moon`, because the garbage is repeated across
the corpus on purpose. Corroboration excludes it and also excludes ~25
legitimate singletons. Isolation ranks it most isolated at 0.483 — four
hundredths from *"Cloud providers are adapters, not the canonical runtime"*,
which is a real goal, and a threshold in that gap is tuned to two points.

So membership is a judgement with a recorded reason, and `GoalJudge` is the
seam. Where no judge is available, only corroborated clusters are promoted: a
smaller model that is safe, rather than a full one that is wrong.

Everything in this module is pure. Storage, transactions and the model call live
above it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from math import sqrt
from typing import Protocol

from ..identifiers import KnowledgeItemId

#: Cosine radius at which two goal clusters may merge under complete linkage.
#: Measured, not chosen: see the table in `D-100`.
CLUSTER_RADIUS = 0.45

#: Markers that scope a statement to the conversation rather than the project.
#:
#: A deterministic pre-filter, so a judge is only asked about genuine ambiguity.
#: These are cheap to test and cheap to be wrong about — a project goal phrased
#: with one of these is a goal somebody will restate.
_CONVERSATION_SCOPE = (
    "in this conversation",
    "in this chat",
    "in this session",
    "in this thread",
    "in the next reply",
    "in your next reply",
    "for the rest of this conversation",
    "earlier in this chat",
    "my next message",
)

_SECOND_PERSON_INSTRUCTION = re.compile(
    r"^\s*(please\s+)?(use|remember|wait|don'?t|do not|stop|continue|reply|answer|repeat)\b",
    re.IGNORECASE,
)


def is_conversation_local(text: str) -> bool:
    """Whether a statement is about the conversation rather than the project.

    *"Use bullet points in the next reply"* is a real instruction that was
    really given, and it is not a goal of the software being planned. It stays
    evidence; it does not enter the model.

    Requires **both** an instruction shape and a conversation-scope marker. Each
    alone over-matches: *"Don't ask me more than one question at a time"* could
    be a product goal, and *"Topic rooms should keep their conversation
    identity across visits"* mentions conversation while being a genuine goal.
    """

    lowered = text.lower()
    scoped = any(marker in lowered for marker in _CONVERSATION_SCOPE)
    if not scoped:
        return False
    return bool(_SECOND_PERSON_INSTRUCTION.match(text)) or lowered.startswith("in this ")


def cosine_distance(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Cosine distance in `[0, 2]`, or ``None`` where it is not defined.

    The same measure the database uses, computed here so clustering can be
    tested without one. A zero-length vector has no direction and therefore no
    angle to anything: that is `None`, not zero — a model that returns zeros on
    failure would otherwise merge every failed row into one confident cluster.
    """

    if len(left) != len(right) or not left:
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return None
    return 1.0 - (dot / (left_norm * right_norm))


def distance_over(
    vectors: Mapping[KnowledgeItemId, Sequence[float]],
) -> Callable[[KnowledgeItemId, KnowledgeItemId], float | None]:
    """A distance function over stored vectors, missing ones included.

    An item with no vector is incomparable to everything, so it clusters alone
    and keeps its own wording. That is the honest rendering of *nothing here
    could compare this*.
    """

    def distance(left: KnowledgeItemId, right: KnowledgeItemId) -> float | None:
        first, second = vectors.get(left), vectors.get(right)
        if first is None or second is None:
            return None
        return cosine_distance(first, second)

    return distance


@dataclass(frozen=True, slots=True)
class GoalCandidate:
    """One cluster of goal evidence, before anything decides it is a goal."""

    members: tuple[KnowledgeItemId, ...]
    canonical_id: KnowledgeItemId
    statement: str

    @property
    def corroborated(self) -> bool:
        """Whether more than one observation says this.

        Not a quality signal — a single well-put goal is still a goal — but it
        is the one signal available when nothing can judge (`D-101`).
        """

        return len(self.members) > 1


@dataclass(frozen=True, slots=True)
class GoalJudgement:
    """Whether a candidate belongs in the project's goal model, and why."""

    include: bool
    reason: str


class GoalJudge(Protocol):
    """Decides whether a candidate is a goal *of this project*.

    Given the candidate and what the project has established about itself. The
    reason is stored beside the object, so a person reading the model can see
    why something is in it and overrule it — human correction outranks working
    synthesis, which `SynthesisService` already enforces.
    """

    def judge(self, statement: str, identity: Sequence[str]) -> GoalJudgement:
        """Return a verdict with a reason. Never raises for an unclear case."""
        ...


def cluster_by_complete_linkage(
    item_ids: Sequence[KnowledgeItemId],
    distance: Callable[[KnowledgeItemId, KnowledgeItemId], float | None],
    *,
    radius: float = CLUSTER_RADIUS,
) -> tuple[tuple[KnowledgeItemId, ...], ...]:
    """Group items so that every pair inside a group is within ``radius``.

    Agglomerative, merging the closest admissible pair of clusters first, where
    a pair's score is the **largest** distance across them. That maximum is what
    makes this resist chaining: admitting a member that is close to one existing
    member but far from another would raise the score above the radius and the
    merge is refused.

    ``distance`` returns ``None`` where two items cannot be compared — an
    unembedded row, say. Unknown is not zero and not infinity: the pair simply
    never merges, so an unindexed item stays a cluster of one rather than
    joining the first thing it is asked about.

    Deterministic: ties break on the ordering of ``item_ids``, so the same
    evidence produces the same clusters and the same identity keys.
    """

    groups: list[list[KnowledgeItemId]] = [[item] for item in item_ids]

    while True:
        best: tuple[float, int, int] | None = None
        for left, right in combinations(range(len(groups)), 2):
            worst = 0.0
            admissible = True
            for a in groups[left]:
                for b in groups[right]:
                    gap = distance(a, b)
                    if gap is None or gap > radius:
                        admissible = False
                        break
                    worst = max(worst, gap)
                if not admissible:
                    break
            if admissible and (best is None or worst < best[0]):
                best = (worst, left, right)
        if best is None:
            return tuple(tuple(group) for group in groups)
        _, left, right = best
        groups[left] = groups[left] + groups[right]
        del groups[right]


def medoid(
    members: Sequence[KnowledgeItemId],
    distance: Callable[[KnowledgeItemId, KnowledgeItemId], float | None],
) -> KnowledgeItemId:
    """The member closest to all the others — the cluster's own best wording.

    Not the longest, not the first, and never generated: the canonical statement
    is one somebody actually said, so the model quotes the project rather than
    paraphrasing it. Where nothing can be compared, the first member stands, and
    ordering is stable so identity does not drift between runs.
    """

    if len(members) == 1:
        return members[0]
    best: tuple[float, KnowledgeItemId] | None = None
    for candidate in members:
        total = 0.0
        for other in members:
            if other == candidate:
                continue
            gap = distance(candidate, other)
            # An incomparable pair counts as the radius rather than as zero, so
            # an unembedded member cannot win by being unmeasurable.
            total += CLUSTER_RADIUS if gap is None else gap
        if best is None or total < best[0]:
            best = (total, candidate)
    assert best is not None
    return best[1]


@dataclass(frozen=True, slots=True)
class GoalModelPlan:
    """What a synthesis run would write, before it writes anything."""

    promoted: tuple[tuple[GoalCandidate, str], ...]
    """Candidates entering the model, each with the reason it was included."""

    withheld: tuple[tuple[GoalCandidate, str], ...]
    """Candidates staying evidence, each with the reason it was not."""

    judged: bool
    """Whether a judge decided membership, or corroboration stood in for one."""


def plan_goal_model(
    candidates: Sequence[GoalCandidate],
    identity: Sequence[str],
    judge: GoalJudge | None,
) -> GoalModelPlan:
    """Decide which candidates become goals, and record why for every one.

    Both halves are returned. A synthesizer that reported only what it kept
    would make its own exclusions unauditable, and the first question anybody
    asks about a model this size is what is *not* in it.
    """

    promoted: list[tuple[GoalCandidate, str]] = []
    withheld: list[tuple[GoalCandidate, str]] = []

    for candidate in candidates:
        if is_conversation_local(candidate.statement):
            withheld.append(
                (
                    candidate,
                    "Scoped to the conversation rather than the project, so it is "
                    "evidence of what was asked and not a goal of what is built.",
                )
            )
            continue
        if judge is None:
            # Degraded, and honest about the cost: a single well-put goal is
            # still a goal, and this drops it (`D-101`).
            if candidate.corroborated:
                promoted.append(
                    (
                        candidate,
                        f"{len(candidate.members)} observations say this, and no judge "
                        "was available to assess uncorroborated candidates.",
                    )
                )
            else:
                withheld.append(
                    (
                        candidate,
                        "Said once, and no judge was available to assess it. Kept as "
                        "evidence rather than promoted unassessed.",
                    )
                )
            continue
        verdict = judge.judge(candidate.statement, identity)
        (promoted if verdict.include else withheld).append((candidate, verdict.reason))

    return GoalModelPlan(
        promoted=tuple(promoted), withheld=tuple(withheld), judged=judge is not None
    )
