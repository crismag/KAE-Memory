"""Golden corpus: Phase 2 reconciles the evidence graph without synthesizing a model."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReconciliationService, SynthesisService
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.relationships import KnowledgeRelation
from kae_memory.domain.synthesis import EvidenceRole
from tests.synthesis.corpus import (
    AREA_SUFFICIENT_TEXT,
    OBSERVATIONS,
    PLANNING_EXPERTISE,
    WHAT_ARE_WE_BUILDING,
    observations_for,
)
from tests.synthesis.load import load_golden_corpus


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, ReconciliationService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-reconciliation")
    return memory, ReconciliationService(factory), SynthesisService(factory), project


class TestGoldenCorpusReconciliation:
    def test_identity_unknowns_are_resolved_and_every_row_remains(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project = _services(factory)
        loaded = load_golden_corpus(memory, project.id)
        report = recon.reconcile(project.id, idempotency_key="full")

        by_content = {item.current_version.content: item for item in loaded.items}
        stale = [by_content[item.content] for item in observations_for(WHAT_ARE_WE_BUILDING)]
        assert {item.id for item in stale} <= set(report.resolved_item_ids)
        for item in stale:
            assert synthesis.evidence_role(item.id) is EvidenceRole.RESOLVED
            stored = next(
                candidate
                for candidate in memory.retrieve_knowledge(project.id, lifecycle=None)
                if candidate.id == item.id
            )
            assert stored.lifecycle is LifecycleState.PROPOSED

        remaining = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(remaining) == len(OBSERVATIONS)
        assert synthesis.list_objects(project.id) == ()
        assert synthesis.list_attention(project.id) == ()
        assert "unknown" in {section.domain for section in report.affected}

    def test_conflicting_state_is_recorded_as_contradiction(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project = _services(factory)
        loaded = load_golden_corpus(memory, project.id)
        report = recon.reconcile(project.id, idempotency_key="full")

        leftover = next(
            item
            for item in loaded.items
            if item.current_version.content == "Use Confirm or Reject on each extracted candidate."
        )
        settled = next(
            item for item in loaded.items if item.current_version.content == AREA_SUFFICIENT_TEXT
        )
        assert any(
            edge.type is KnowledgeRelation.CONTRADICTS
            and edge.source_id == settled.id
            and edge.target_id == leftover.id
            for edge in report.graph.edges
        )
        assert synthesis.evidence_role(leftover.id) is EvidenceRole.CONFLICTING
        assert settled.lifecycle is LifecycleState.VALIDATED
        assert leftover.lifecycle is LifecycleState.PROPOSED

    def test_planning_expertise_paraphrases_are_not_one_support_cluster(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, _synthesis, project = _services(factory)
        loaded = load_golden_corpus(memory, project.id)
        report = recon.reconcile(project.id, idempotency_key="full")

        texts = {
            item.content
            for item in observations_for(PLANNING_EXPERTISE)
            if item.kind is KnowledgeKind.GOAL
        }
        ids = {
            item.id
            for item in loaded.items
            if item.kind == KnowledgeKind.GOAL.value and item.current_version.content in texts
        }
        clustered = {
            endpoint
            for edge in report.graph.edges
            if edge.type is KnowledgeRelation.SUPPORTS
            for endpoint in (edge.source_id, edge.target_id)
            if endpoint in ids
        }
        assert len(clustered) < len(ids)

    def test_rerun_is_idempotent_and_still_mints_no_model(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)
        first = recon.reconcile(project.id, idempotency_key="full")
        second = recon.reconcile(project.id, idempotency_key="full")

        assert second.replayed is True
        assert second.event.id == first.event.id
        assert second.edges_written == 0
        assert second.roles_written == 0
        assert first.graph.edges == second.graph.edges
        assert synthesis.list_objects(project.id) == ()
        assert synthesis.list_attention(project.id) == ()
        assert len(synthesis.list_changes(project.id)) == 1
