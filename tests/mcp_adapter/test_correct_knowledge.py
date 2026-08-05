"""The MCP correction surface (T14).

Correction is the one review action that changes what the project says. The
thing it must never do is lose what the agent originally proposed: the audit
trail's value is in showing both what was suggested and what a person made of
it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.chunks import EmbeddingState
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
from kae_memory.domain.knowledge_review import ReviewAction
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.workspace import ActorType
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch
from kae_memory.persistence.chunk_repository import ChunkRepository

ORIGINAL = "The service publishes reports over SNS."
CORRECTED = "The service publishes reports over SQS."


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        embedder_name="deterministic",
    )


def _seed(context: tools.ToolContext, name: str, key: str) -> tuple[str, str]:
    project = context.memory.create_project(name, key=key)
    run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, f"{key}-seed")
    written = context.memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="requirement", content=ORIGINAL, source="inference")],
    )
    return str(project.id), str(written[0].id)


@pytest.fixture
def seeded(context: tools.ToolContext) -> tuple[str, str]:
    return _seed(context, "Ministry Reporting", "correct-ministry")


def _correct(context: tools.ToolContext, **arguments: object) -> dict[str, Any]:
    arguments.setdefault("reviewer", "cris")
    arguments.setdefault("content", CORRECTED)
    return dispatch(context, "kae_correct_knowledge", dict(arguments))


def _item(context: tools.ToolContext, project_id: str, knowledge_id: str) -> KnowledgeItem:
    held = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
    return next(item for item in held if str(item.id) == knowledge_id)


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        assert "kae_correct_knowledge" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_content_reviewer_and_version_are_required(self) -> None:
        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_correct_knowledge")
        required = declaration["inputSchema"]["required"]

        assert {"content", "reviewer", "expected_version"} <= set(required)


class TestAppendOnly:
    def test_the_original_wording_is_preserved(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Losing what the agent proposed would gut the audit trail."""

        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        item = _item(context, project_id, knowledge_id)
        assert item.versions[0].content == ORIGINAL
        assert item.current_version.content == CORRECTED
        assert len(item.versions) == 2

    def test_the_correction_is_attributed_to_a_person_not_a_run(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        _correct(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            reviewer="cris",
        )

        item = _item(context, project_id, knowledge_id)
        assert str(item.current_version.provenance.actor_id) == "cris"
        assert str(item.current_version.provenance.execution_id) == "human"

    def test_the_original_provenance_survives(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        item = _item(context, project_id, knowledge_id)
        assert item.versions[0].provenance.source == "inference"


class TestLifecycleSplit:
    def test_correcting_a_proposal_accepts_the_corrected_form(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """The reviewer wrote the words; asking them to confirm is ceremony."""

        project_id, knowledge_id = seeded

        result = _correct(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["state"] == "validated"
        assert result["authoritative"] is True

    def test_correcting_confirmed_knowledge_returns_it_for_review(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """The old confirmation applied to the old wording."""

        project_id, knowledge_id = seeded
        context.memory.review_confirm(
            ProjectId(project_id), KnowledgeItemId(knowledge_id), expected_version=1
        )

        result = _correct(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["state"] == "proposed"
        assert result["authoritative"] is False

    def test_an_agent_correction_never_validates(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Otherwise the worker could confirm knowledge, and FR-005 falls in a
        second place nobody would look."""

        project_id, knowledge_id = seeded

        outcome = context.memory.review_correct(
            ProjectId(project_id),
            KnowledgeItemId(knowledge_id),
            expected_version=1,
            content=CORRECTED,
            actor_type=ActorType.AGENT,
            actor_id="review-agent",
        )

        assert outcome.item.lifecycle is LifecycleState.PROPOSED


class TestAuditRecord:
    def test_the_event_names_both_versions(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        history = context.memory.review_history(
            ProjectId(project_id), KnowledgeItemId(knowledge_id)
        )
        event = history[-1]
        assert event.action is ReviewAction.CORRECTED
        assert event.from_version_number == 1
        assert event.version_number == 2

    def test_a_correction_is_distinguishable_from_a_plain_confirmation(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Both can end validated; only one rewrote what the project says."""

        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        history = context.memory.review_history(
            ProjectId(project_id), KnowledgeItemId(knowledge_id)
        )
        assert history[-1].action is ReviewAction.CORRECTED
        assert history[-1].to_lifecycle is LifecycleState.VALIDATED

    def test_the_response_reports_the_version_it_replaced(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = _correct(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["replaced_version"] == 1
        assert result["version"] == 2


class TestEmbedding:
    def test_corrected_text_is_queued_for_re_embedding(
        self, context: tools.ToolContext, seeded: tuple[str, str], factory: sessionmaker[Session]
    ) -> None:
        """ADR-0008: the old vector serves until a re-embed lands, and the
        chunk is marked so the existing worker will pick it up."""

        project_id, knowledge_id = seeded

        result = _correct(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["embedding"] == "pending"
        with factory() as db:
            chunks = ChunkRepository(db).list_for_knowledge(KnowledgeItemId(knowledge_id))
        assert chunks
        assert all(chunk.state is EmbeddingState.STALE for chunk in chunks)

    def test_the_chunk_text_is_the_corrected_wording(
        self, context: tools.ToolContext, seeded: tuple[str, str], factory: sessionmaker[Session]
    ) -> None:
        """Retrieval must return the current text even while the vector is stale."""

        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        with factory() as db:
            chunks = ChunkRepository(db).list_for_knowledge(KnowledgeItemId(knowledge_id))
        assert any(CORRECTED in chunk.text for chunk in chunks)
        assert not any(ORIGINAL in chunk.text for chunk in chunks)

    def test_a_correction_is_discovered_by_the_re_embedding_workflow(
        self, context: tools.ToolContext, seeded: tuple[str, str], factory: sessionmaker[Session]
    ) -> None:
        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        with factory() as db:
            outstanding = ChunkRepository(db).list_needing_embedding(
                ProjectId(project_id), limit=100
            )
        assert any(CORRECTED in chunk.text for chunk in outstanding)


class TestRefusals:
    def test_an_empty_correction_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = _correct(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            content="   ",
        )

        assert result["error"] == "invalid_argument"

    def test_another_project_cannot_correct_this_item(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        _, knowledge_id = seeded
        other_project, _ = _seed(context, "Other", "correct-other")

        result = _correct(
            context, project_id=other_project, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "knowledge_not_found"

    def test_a_stale_version_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Two reviewers correcting the same wording must not silently stack."""

        project_id, knowledge_id = seeded
        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        result = _correct(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            content="A third wording.",
        )

        assert result["error"] == "version_conflict"

    def test_rejected_knowledge_cannot_be_corrected(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        context.memory.reject_knowledge(KnowledgeItemId(knowledge_id))

        result = _correct(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "invalid_state_transition"

    def test_a_missing_reviewer_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = dispatch(
            context,
            "kae_correct_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": 1,
                "content": CORRECTED,
            },
        )

        assert result["error"] == "invalid_argument"
        assert "reviewer" in result["message"]


class TestReplay:
    def test_a_retry_does_not_append_a_second_version(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """The dangerous failure: a retry that corrects the correction."""

        project_id, knowledge_id = seeded
        arguments = {
            "project_id": project_id,
            "knowledge_id": knowledge_id,
            "expected_version": 1,
            "content": CORRECTED,
            "reviewer": "cris",
            "idempotency_key": "correct-retry-1",
        }

        first = dispatch(context, "kae_correct_knowledge", arguments)
        second = dispatch(context, "kae_correct_knowledge", arguments)

        assert first["already_applied"] is False
        assert second["already_applied"] is True
        item = _item(context, project_id, knowledge_id)
        assert len(item.versions) == 2
        history = context.memory.review_history(
            ProjectId(project_id), KnowledgeItemId(knowledge_id)
        )
        assert len(history) == 1


class TestSearchEffect:
    def test_search_returns_the_corrected_wording(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        result = dispatch(
            context,
            "kae_search_knowledge",
            {"project_id": project_id, "query": "SQS", "mode": "lexical"},
        )

        assert result["matched_chunks"] == 1
        assert CORRECTED in result["results"][0]["text"]

    def test_the_replaced_wording_is_no_longer_matched(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """A chunk that kept matching text the item no longer says would be a
        result nobody can act on."""

        project_id, knowledge_id = seeded

        _correct(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        result = dispatch(
            context,
            "kae_search_knowledge",
            {"project_id": project_id, "query": "SNS", "mode": "lexical"},
        )

        assert result["matched_chunks"] == 0
