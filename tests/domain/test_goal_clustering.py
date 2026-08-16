"""Clustering that cannot chain, and exclusions that say why (`D-100`, `D-101`).

`EM-3` is blocked because `D-76` found cosine still merged 26 of 88 statements
into one group at every threshold. The measure was never the defect —
**single-link chaining** was, and it reproduces on this corpus with real
vectors: single linkage at radius 0.45 puts 46 of 47 goals in one cluster where
complete linkage produces 19.

The first test here is that failure in miniature. It is the whole reason this
module exists, so it is the first thing asserted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from kae_memory.domain.clustering import cluster_by_complete_linkage
from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.synthesizers.goals import (
    CLUSTER_RADIUS,
    GoalCandidate,
    GoalJudgement,
    is_conversation_local,
    medoid,
    plan_goal_model,
)


def _ids(count: int) -> list[KnowledgeItemId]:
    return [KnowledgeItemId(f"item-{index}") for index in range(count)]


def _line(step: float) -> Callable[[KnowledgeItemId, KnowledgeItemId], float]:
    """Points evenly spaced along a line: the shape chaining exploits."""

    def distance(left: KnowledgeItemId, right: KnowledgeItemId) -> float:
        a = int(str(left).rsplit("-", 1)[1])
        b = int(str(right).rsplit("-", 1)[1])
        return abs(a - b) * step

    return distance


class TestItCannotChain:
    def test_a_chain_of_near_neighbours_does_not_become_one_cluster(self) -> None:
        """`D-76` in miniature.

        Ten statements, each a hair from the next and the ends far apart. Single
        linkage merges the lot, because it only ever asks about the closest
        pair. Complete linkage asks about the furthest, so the chain stops where
        the diameter would exceed the radius.
        """

        items = _ids(10)
        # Each neighbour is a fifth of the radius away; the ends are 9/5 of it.
        clusters = cluster_by_complete_linkage(
            items, _line(CLUSTER_RADIUS / 5), radius=CLUSTER_RADIUS
        )

        assert len(clusters) > 1, "a chain collapsed into one cluster — this is D-76"
        largest = max(len(cluster) for cluster in clusters)
        assert largest <= 6

    def test_every_pair_inside_a_cluster_is_within_the_radius(self) -> None:
        """The invariant complete linkage exists to provide.

        Stated as a property over the output rather than trusting the loop: this
        is what makes a cluster a claim about all of its members and not about a
        path through them.
        """

        items = _ids(12)
        distance = _line(CLUSTER_RADIUS / 4)

        for cluster in cluster_by_complete_linkage(items, distance, radius=CLUSTER_RADIUS):
            for left in cluster:
                for right in cluster:
                    assert distance(left, right) <= CLUSTER_RADIUS

    def test_two_tight_groups_far_apart_stay_apart(self) -> None:
        near, far = _ids(3), [KnowledgeItemId(f"far-{i}") for i in range(3)]

        def distance(left: KnowledgeItemId, right: KnowledgeItemId) -> float:
            same_side = str(left).startswith("far") == str(right).startswith("far")
            return 0.05 if same_side else 0.9

        clusters = cluster_by_complete_linkage(near + far, distance, radius=CLUSTER_RADIUS)

        assert sorted(len(cluster) for cluster in clusters) == [3, 3]


class TestWhatCannotBeCompared:
    def test_an_unmeasurable_pair_never_merges(self) -> None:
        """Unknown is not zero.

        An unembedded row returning `None` must not join the first cluster it is
        asked about. It stays a cluster of one, which is what *we could not
        compare this* looks like in output.
        """

        items = _ids(3)

        def distance(left: KnowledgeItemId, right: KnowledgeItemId) -> float | None:
            return None if "item-2" in {str(left), str(right)} else 0.1

        clusters = cluster_by_complete_linkage(items, distance, radius=CLUSTER_RADIUS)

        assert (KnowledgeItemId("item-2"),) in clusters

    def test_the_medoid_is_never_the_unmeasurable_member(self) -> None:
        # Otherwise the cluster's canonical wording is chosen by being
        # unmeasurable, which reads as the best statement and is the absence
        # of one.
        items = _ids(3)

        def distance(left: KnowledgeItemId, right: KnowledgeItemId) -> float | None:
            return None if "item-2" in {str(left), str(right)} else 0.1

        assert medoid(items, distance) != KnowledgeItemId("item-2")

    def test_clustering_is_deterministic(self) -> None:
        # Identity keys derive from the canonical member. A run that reordered
        # its clusters would remint the model each time and lose every human
        # correction attached to it.
        items = _ids(8)
        distance = _line(CLUSTER_RADIUS / 3)

        first = cluster_by_complete_linkage(items, distance, radius=CLUSTER_RADIUS)
        second = cluster_by_complete_linkage(items, distance, radius=CLUSTER_RADIUS)

        assert first == second


class TestConversationLocalInstructions:
    @pytest.mark.parametrize(
        "text",
        [
            "In this conversation, wait for my next message before continuing.",
            "Use bullet points in the next reply.",
            "Remember what I said earlier in this chat.",
            "Don't ask me more than one question at a time in this session.",
        ],
    )
    def test_an_instruction_about_the_conversation_is_not_a_goal(self, text: str) -> None:
        assert is_conversation_local(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Topic rooms should keep their conversation identity across visits.",
            "Interviewing should feel like collaboration, not a form.",
            "The product should recommend before it asks, when it can.",
            "Keep a durable record of project knowledge across sessions.",
        ],
    )
    def test_a_goal_that_mentions_conversation_survives(self, text: str) -> None:
        """The over-match this rule is shaped to avoid.

        Half of this product is about conversation, so a marker alone would
        delete real goals. Both an instruction shape and a conversation-scope
        marker are required.
        """

        assert not is_conversation_local(text)


def _candidate(statement: str, members: int = 1) -> GoalCandidate:
    ids = tuple(KnowledgeItemId(f"{statement[:8]}-{index}") for index in range(members))
    return GoalCandidate(members=ids, canonical_id=ids[0], statement=statement)


class _Judge:
    """A judge that refuses one statement, to prove the seam is honoured."""

    def __init__(self, refuse: str) -> None:
        self._refuse = refuse

    def judge(self, statement: str, identity: Sequence[str]) -> GoalJudgement:
        if statement == self._refuse:
            return GoalJudgement(include=False, reason="Unrelated to what this project is.")
        return GoalJudgement(include=True, reason="Consistent with the project's identity.")


class TestWhoDecidesMembership:
    def test_a_refused_candidate_is_withheld_with_its_reason(self) -> None:
        plan = plan_goal_model(
            [_candidate("Hold something until it reaches the moon."), _candidate("Real goal.")],
            ["KAE turns discussions into a project definition."],
            _Judge(refuse="Hold something until it reaches the moon."),
        )

        assert [c.statement for c, _ in plan.promoted] == ["Real goal."]
        assert plan.withheld[0][1] == "Unrelated to what this project is."
        assert plan.judged

    def test_every_candidate_is_accounted_for(self) -> None:
        """Promoted plus withheld is all of them.

        A synthesizer that reported only what it kept would make its own
        exclusions unauditable, and *what is not in the model* is the first
        question anybody asks about one this small.
        """

        candidates = [_candidate(f"Goal {index}.") for index in range(5)]

        plan = plan_goal_model(candidates, [], _Judge(refuse="Goal 3."))

        assert len(plan.promoted) + len(plan.withheld) == len(candidates)

    def test_without_a_judge_only_corroborated_candidates_are_promoted(self) -> None:
        """`ADR-0006` degraded mode, with its cost stated.

        A smaller model that is safe beats a full one that is wrong. The cost is
        real and named in the reason: a single well-put goal is still a goal,
        and this drops it.
        """

        plan = plan_goal_model(
            [_candidate("Said twice.", members=2), _candidate("Said once.")],
            [],
            judge=None,
        )

        assert [c.statement for c, _ in plan.promoted] == ["Said twice."]
        assert "no judge was available" in plan.withheld[0][1]
        assert not plan.judged

    def test_a_conversation_instruction_is_excluded_before_any_judge_is_asked(self) -> None:
        # Cheap and deterministic first, so the model is only asked about
        # genuine ambiguity — and so this exclusion holds with no model at all.
        plan = plan_goal_model(
            [_candidate("Use bullet points in the next reply.")],
            [],
            _Judge(refuse="nothing"),
        )

        assert plan.promoted == ()
        assert "conversation" in plan.withheld[0][1].lower()
