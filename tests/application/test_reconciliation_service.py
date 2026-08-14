"""Reconciliation writes an evidence graph, not a synthesized model."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import (
    MemoryService,
    ReconciliationService,
    SynthesisService,
    WriteKnowledgeRequest,
)
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.relationships import KnowledgeRelation
from kae_memory.domain.synthesis import EvidenceRole


def _project(
    factory: sessionmaker[Session], key: str
) -> tuple[MemoryService, ReconciliationService, SynthesisService, ProjectId]:
    memory = MemoryService(factory)
    return (
        memory,
        ReconciliationService(factory),
        SynthesisService(factory),
        memory.create_project("Reconciliation", key=key).id,
    )


def _write(
    memory: MemoryService,
    project_id: ProjectId,
    kind: str,
    content: str,
    *,
    confirm: bool = False,
) -> KnowledgeItem:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, f"extract-{content}")
    item = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind=kind, content=content, source="interview")]
    )[0]
    if not confirm:
        return item
    memory.confirm_knowledge(item.id)
    return next(
        candidate
        for candidate in memory.retrieve_knowledge(project_id, lifecycle=None)
        if candidate.id == item.id
    )


class TestSupportAndConflictPersistAsEvidenceGraph:
    def test_near_paraphrase_writes_supports_without_deleting_rows(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project_id = _project(factory, "support-pair")
        first = _write(
            memory,
            project_id,
            "goal",
            "Retain original source notes for every project.",
        )
        second = _write(
            memory,
            project_id,
            "goal",
            "Retain original source notes for every project after decode.",
        )

        report = recon.reconcile(project_id, idempotency_key="full")

        assert report.replayed is False
        assert report.edges_written >= 1
        types = {edge.type for edge in report.graph.edges}
        assert KnowledgeRelation.SUPPORTS in types
        stored = memory.retrieve_knowledge(project_id, lifecycle=None)
        assert {item.current_version.content for item in stored} == {
            first.current_version.content,
            second.current_version.content,
        }
        assert synthesis.list_objects(project_id) == ()
        assert synthesis.list_attention(project_id) == ()

    def test_polarity_conflict_writes_contradicts_and_keeps_lifecycle(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project_id = _project(factory, "polarity")
        allowed = _write(memory, project_id, "rule", "Users may approve their own reports.")
        forbidden = _write(memory, project_id, "rule", "Users may not approve their own reports.")

        report = recon.reconcile(project_id, idempotency_key="full")

        assert any(edge.type is KnowledgeRelation.CONTRADICTS for edge in report.graph.edges)
        roles = dict(report.graph.roles)
        assert roles[allowed.id] is EvidenceRole.CONFLICTING
        assert roles[forbidden.id] is EvidenceRole.CONFLICTING
        stored = {item.id: item for item in memory.retrieve_knowledge(project_id, lifecycle=None)}
        assert stored[allowed.id].lifecycle is LifecycleState.PROPOSED
        assert stored[forbidden.id].lifecycle is LifecycleState.PROPOSED
        assert synthesis.evidence_role(allowed.id) is EvidenceRole.CONFLICTING


class TestStaleUnknownResolution:
    def test_identity_unknown_is_resolved_without_superseding_lifecycle(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project_id = _project(factory, "identity")
        identity = _write(
            memory,
            project_id,
            "goal",
            "KAE turns discussions and documents into a development-ready project definition.",
        )
        unknown = _write(memory, project_id, "unknown", "What are we building?")

        report = recon.reconcile(project_id, idempotency_key="full")

        assert unknown.id in report.resolved_item_ids
        assert synthesis.evidence_role(unknown.id) is EvidenceRole.RESOLVED
        stored = next(
            item
            for item in memory.retrieve_knowledge(project_id, lifecycle=None)
            if item.id == unknown.id
        )
        assert stored.lifecycle is LifecycleState.PROPOSED
        assert any(edge.type is KnowledgeRelation.SUPERSEDES for edge in report.graph.edges)
        assert synthesis.evidence_role(identity.id) is EvidenceRole.ACTIVE
        assert synthesis.list_objects(project_id) == ()

    def test_incremental_pass_resolves_a_new_identity_unknown(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, _synthesis, project_id = _project(factory, "incremental")
        _write(
            memory,
            project_id,
            "goal",
            "KAE turns discussions and documents into a development-ready project definition.",
        )
        recon.reconcile(project_id, idempotency_key="before")
        unknown = _write(memory, project_id, "unknown", "Which project is this?")

        report = recon.reconcile(
            project_id,
            idempotency_key="after",
            item_ids=[unknown.id],
        )

        assert report.replayed is False
        assert unknown.id in report.resolved_item_ids
        assert "unknown" in {section.domain for section in report.affected}


class TestIdempotence:
    def test_rerunning_unchanged_evidence_writes_nothing_further(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, recon, synthesis, project_id = _project(factory, "idempotent")
        _write(
            memory,
            project_id,
            "goal",
            "Retain original source notes for every project.",
        )
        _write(
            memory,
            project_id,
            "goal",
            "Retain original source notes for every project after decode.",
        )

        first = recon.reconcile(project_id, idempotency_key="full")
        second = recon.reconcile(project_id, idempotency_key="full")

        assert second.replayed is True
        assert second.event.id == first.event.id
        assert second.edges_written == 0
        assert second.roles_written == 0
        assert len(synthesis.list_changes(project_id)) == 1
        assert first.graph.edges == second.graph.edges
