"""Deterministic pair classification does not mint a model."""

from __future__ import annotations

from tests.synthesis.corpus import (
    AREA_SUFFICIENT_TEXT,
    DEVELOPMENT_READY_PLAN,
    HOLD_MOON_TEXT,
    PLANNING_EXPERTISE,
    PROJECT_IDENTITY_TEXT,
    WHAT_ARE_WE_BUILDING,
    observations_for,
)

from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.reconciliation import (
    EvidenceSnapshot,
    PairRelation,
    classify_pair,
    is_identity_statement,
    is_identity_unknown,
    is_support_pair,
    plan_reconciliation,
)
from kae_memory.domain.relationships import KnowledgeRelation
from kae_memory.domain.synthesis import EvidenceRole


def _snap(
    item_id: str,
    kind: KnowledgeKind,
    content: str,
    lifecycle: LifecycleState = LifecycleState.PROPOSED,
) -> EvidenceSnapshot:
    return EvidenceSnapshot(KnowledgeItemId(item_id), kind.value, content, lifecycle)


class TestIdentityUnknownsAreTypedNotLexical:
    def test_corpus_identity_questions_are_identity_unknowns(self) -> None:
        questions = observations_for(WHAT_ARE_WE_BUILDING)
        assert len(questions) == 6
        assert all(is_identity_unknown(item.kind.value, item.content) for item in questions)

    def test_neighbouring_unknowns_are_not_collapsed_into_identity(self) -> None:
        assert not is_identity_unknown(
            KnowledgeKind.UNKNOWN.value, "What does development-ready mean for this project?"
        )
        assert not is_identity_unknown(
            KnowledgeKind.UNKNOWN.value,
            "What evidence is enough to close what-are-we-building?",
        )

    def test_product_identity_statement_is_recognised(self) -> None:
        assert is_identity_statement(KnowledgeKind.GOAL.value, PROJECT_IDENTITY_TEXT)
        assert not is_identity_statement(
            KnowledgeKind.GOAL.value,
            "KAE should ask before making consequential decisions.",
        )

    def test_identity_unknown_resolves_against_identity_evidence(self) -> None:
        identity = _snap("g1", KnowledgeKind.GOAL, PROJECT_IDENTITY_TEXT)
        unknown = _snap("u1", KnowledgeKind.UNKNOWN, "What are we building?")
        leftover = _snap(
            "u2", KnowledgeKind.UNKNOWN, "What does development-ready mean for this project?"
        )

        assert classify_pair(identity, unknown) is PairRelation.RESOLVE
        assert classify_pair(identity, leftover) is PairRelation.NONE


class TestSupportIsConservative:
    def test_overlap_support_requires_shared_stems_and_length_cap(self) -> None:
        left = _snap("a", KnowledgeKind.GOAL, "Retain original source notes for every project.")
        right = _snap(
            "b", KnowledgeKind.GOAL, "Retain original source notes for every project after decode."
        )

        assert is_support_pair(left, right)
        assert classify_pair(left, right) is PairRelation.SUPPORT

    def test_short_actor_does_not_support_a_longer_mention(self) -> None:
        actor = _snap("a", KnowledgeKind.ACTOR, "User")
        longer = _snap("b", KnowledgeKind.ACTOR, "The user entering notes")

        assert not is_support_pair(actor, longer)

    def test_planning_expertise_paraphrases_are_not_support_pairs(self) -> None:
        goals = [
            item for item in observations_for(PLANNING_EXPERTISE) if item.kind is KnowledgeKind.GOAL
        ]
        snapshots = tuple(
            _snap(f"g{index}", KnowledgeKind.GOAL, item.content) for index, item in enumerate(goals)
        )
        graph = plan_reconciliation(snapshots)

        assert [edge for edge in graph.edges if edge.type is KnowledgeRelation.SUPPORTS] == []

    def test_development_ready_paraphrases_are_not_forced_into_one_cluster(self) -> None:
        goals = [
            item
            for item in observations_for(DEVELOPMENT_READY_PLAN)
            if item.kind is KnowledgeKind.GOAL
        ]
        snapshots = tuple(
            _snap(f"d{index}", KnowledgeKind.GOAL, item.content) for index, item in enumerate(goals)
        )
        graph = plan_reconciliation(snapshots)
        support = [edge for edge in graph.edges if edge.type is KnowledgeRelation.SUPPORTS]
        clustered = {str(edge.source_id) for edge in support} | {
            str(edge.target_id) for edge in support
        }

        assert len(clustered) < len(snapshots)


class TestConflictsAndResolutionPlan:
    def test_opposite_polarity_near_duplicates_contradict(self) -> None:
        allowed = _snap("a", KnowledgeKind.RULE, "Users may approve their own reports.")
        forbidden = _snap("b", KnowledgeKind.RULE, "Users may not approve their own reports.")

        assert classify_pair(allowed, forbidden) is PairRelation.CONTRADICT

    def test_sufficiency_conflicts_with_leftover_candidate_review(self) -> None:
        settled = _snap(
            "d1",
            KnowledgeKind.DECISION,
            AREA_SUFFICIENT_TEXT,
            LifecycleState.VALIDATED,
        )
        leftover = _snap(
            "d2",
            KnowledgeKind.DECISION,
            "Use Confirm or Reject on each extracted candidate.",
        )

        assert classify_pair(settled, leftover) is PairRelation.CONTRADICT

    def test_hold_moon_is_not_an_identity_resolution(self) -> None:
        goal = _snap("g", KnowledgeKind.GOAL, HOLD_MOON_TEXT)
        unknown = _snap("u", KnowledgeKind.UNKNOWN, HOLD_MOON_TEXT)

        assert classify_pair(goal, unknown) is PairRelation.NONE

    def test_plan_assigns_resolved_without_touching_lifecycle(self) -> None:
        snapshots = (
            _snap("g1", KnowledgeKind.GOAL, PROJECT_IDENTITY_TEXT),
            _snap("u1", KnowledgeKind.UNKNOWN, "What are we building?"),
            _snap("u2", KnowledgeKind.UNKNOWN, "Which project is this?"),
        )
        graph = plan_reconciliation(snapshots)

        assert graph.resolved_item_ids == (KnowledgeItemId("u1"), KnowledgeItemId("u2"))
        roles = dict(graph.roles)
        assert roles[KnowledgeItemId("u1")] is EvidenceRole.RESOLVED
        assert KnowledgeItemId("g1") not in roles
        assert all(edge.type is KnowledgeRelation.SUPERSEDES for edge in graph.edges)
        assert {section.domain for section in graph.affected} == {"goal", "unknown"}
