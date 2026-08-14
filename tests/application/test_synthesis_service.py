"""The three knowledge layers persist separately, and extraction is not attention."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.domain.errors import AuthoritativeOverrideError, IdempotencyConflictError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.synthesis import (
    AttentionKind,
    AttentionStatus,
    Authority,
    ChangeTrigger,
    EvidenceBindingKind,
    EvidenceRole,
    SynthesizedLifecycle,
)


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, SynthesisService, ProjectId]:
    memory = MemoryService(factory)
    return memory, SynthesisService(factory), memory.create_project("Layers", key="layers").id


def _write(memory: MemoryService, project_id: ProjectId, text: str) -> Any:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "extract-1")
    return memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="goal", content=text, source="interview")]
    )[0]


class TestExtractionDoesNotBecomeTheModel:
    def test_writing_knowledge_creates_neither_model_nor_attention(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        memory, synthesis, project_id = project
        item = _write(memory, project_id, "Hold something until it reaches the moon.")

        assert item.lifecycle is LifecycleState.PROPOSED
        assert synthesis.list_objects(project_id) == ()
        assert synthesis.list_attention(project_id) == ()
        assert synthesis.evidence_role(item.id) is EvidenceRole.ACTIVE


class TestSynthesizedObjectsAreSeparateFromEvidence:
    def test_put_is_idempotent_by_identity(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        first = synthesis.put_object(
            project_id, "goal", "planning-expertise", "Planning expertise", "One outcome."
        )
        second = synthesis.put_object(
            project_id, "goal", "planning-expertise", "Planning expertise", "One outcome."
        )

        assert first.id == second.id
        assert first.revision == 1
        assert len(synthesis.list_objects(project_id)) == 1

    def test_working_update_bumps_revision_without_minting_a_twin(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        first = synthesis.put_object(
            project_id, "goal", "planning-expertise", "Planning expertise", "One outcome."
        )
        updated = synthesis.put_object(
            project_id, "goal", "planning-expertise", "Planning expertise", "A clearer outcome."
        )

        assert updated.id == first.id
        assert updated.revision == 2
        assert updated.statement == "A clearer outcome."
        assert len(synthesis.list_objects(project_id)) == 1

    def test_binding_evidence_does_not_delete_the_extracted_row(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        memory, synthesis, project_id = project
        item = _write(memory, project_id, "Produce a development-ready plan.")
        obj = synthesis.put_object(
            project_id, "goal", "dev-ready", "Development-ready plan", "One outcome."
        )

        binding = synthesis.bind_evidence(project_id, obj.id, item.id, EvidenceBindingKind.SUPPORTS)
        replay = synthesis.bind_evidence(project_id, obj.id, item.id, EvidenceBindingKind.SUPPORTS)

        assert binding.id == replay.id
        stored = next(
            candidate
            for candidate in memory.retrieve_knowledge(project_id, lifecycle=None)
            if candidate.id == item.id
        )
        assert stored.current_version.content == "Produce a development-ready plan."
        view = synthesis.get_object(project_id, obj.id)
        assert view is not None
        assert len(view.evidence) == 1

    def test_evidence_role_does_not_change_statement_lifecycle(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        memory, synthesis, project_id = project
        item = _write(memory, project_id, "Hold something until it reaches the moon.")

        synthesis.set_evidence_role(project_id, item.id, EvidenceRole.NOISE)

        stored = next(
            candidate
            for candidate in memory.retrieve_knowledge(project_id, lifecycle=None)
            if candidate.id == item.id
        )
        assert stored.lifecycle is LifecycleState.PROPOSED
        assert synthesis.evidence_role(item.id) is EvidenceRole.NOISE


class TestHumanAuthorityOutranksWorkingSynthesis:
    def test_human_correction_blocks_a_later_working_overwrite(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        obj = synthesis.put_object(
            project_id, "goal", "identity", "What we are building", "A working guess."
        )
        corrected = synthesis.correct_object(
            project_id, obj.id, "What we are building", "KAE, a planning product."
        )

        assert corrected.authority is Authority.HUMAN
        assert corrected.lifecycle is SynthesizedLifecycle.AUTHORITATIVE

        with pytest.raises(AuthoritativeOverrideError):
            synthesis.put_object(
                project_id, "goal", "identity", "What we are building", "A later AI guess."
            )

        still = synthesis.get_object(project_id, obj.id)
        assert still is not None
        assert still.object.statement == "KAE, a planning product."


class TestChangeEventsAreIdempotent:
    def test_the_same_key_and_payload_return_the_same_event(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        first = synthesis.record_change(
            project_id, "cycle-1", ChangeTrigger.RECONCILIATION, "clustered six goals"
        )
        second = synthesis.record_change(
            project_id, "cycle-1", ChangeTrigger.RECONCILIATION, "clustered six goals"
        )

        assert first.id == second.id
        assert len(synthesis.list_changes(project_id)) == 1

    def test_the_same_key_with_a_different_payload_conflicts(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        synthesis.record_change(
            project_id, "cycle-1", ChangeTrigger.RECONCILIATION, "clustered six goals"
        )

        with pytest.raises(IdempotencyConflictError):
            synthesis.record_change(
                project_id, "cycle-1", ChangeTrigger.RECONCILIATION, "something else"
            )


class TestAttentionIsNotUnconfirmedExtraction:
    def test_attention_identity_does_not_mint_a_second_interrupt(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        first = synthesis.put_attention(
            project_id,
            AttentionKind.DECISION,
            "Choose collaboration MVP",
            "Two candidates remain.",
            identity_key="collab-mvp",
        )
        second = synthesis.put_attention(
            project_id,
            AttentionKind.DECISION,
            "Choose collaboration MVP",
            "Two candidates remain.",
            identity_key="collab-mvp",
        )

        assert first.id == second.id
        assert len(synthesis.list_attention(project_id)) == 1

    def test_resolved_attention_leaves_the_live_queue(
        self, project: tuple[MemoryService, SynthesisService, ProjectId]
    ) -> None:
        _memory, synthesis, project_id = project
        item = synthesis.put_attention(
            project_id,
            AttentionKind.UNKNOWN,
            "What are we building?",
            "Identity evidence already exists.",
            identity_key="what-building",
        )

        resolved = synthesis.resolve_attention(project_id, item.id, AttentionStatus.RESOLVED)

        assert resolved.status is AttentionStatus.RESOLVED
        assert synthesis.list_attention(project_id) == ()
        history = synthesis.list_attention(project_id, open_only=False)
        assert len(history) == 1
        assert history[0].status is AttentionStatus.RESOLVED
