"""The MCP rejection surface (T13).

Rejection has one property confirmation does not: it must say why. A rejected
statement stays readable forever, and a reader who cannot tell a factual error
from a scope decision has the record without the meaning.
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
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
from kae_memory.domain.knowledge_review import RejectionReason, ReviewAction
from kae_memory.domain.lifecycle import HISTORICAL, LifecycleState
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

STATEMENT = "The service publishes reports over SNS."


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
        [WriteKnowledgeRequest(kind="requirement", content=STATEMENT, source="inference")],
    )
    return str(project.id), str(written[0].id)


@pytest.fixture
def seeded(context: tools.ToolContext) -> tuple[str, str]:
    return _seed(context, "Ministry Reporting", "reject-ministry")


def _reject(context: tools.ToolContext, **arguments: object) -> dict[str, Any]:
    arguments.setdefault("reviewer", "cris")
    arguments.setdefault("reason_code", "incorrect")
    return dispatch(context, "kae_reject_knowledge", dict(arguments))


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        assert "kae_reject_knowledge" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_a_reason_and_a_reviewer_are_both_required(self) -> None:
        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_reject_knowledge")
        required = declaration["inputSchema"]["required"]

        assert "reason_code" in required
        assert "reviewer" in required
        assert "expected_version" in required


class TestRejection:
    def test_proposed_knowledge_can_be_ruled_out(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = _reject(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["state"] == "rejected"
        assert result["authoritative"] is False
        assert result["retrievable"] is False

    def test_rejection_is_not_deletion(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """The statement and its wording survive; only its standing changes."""

        project_id, knowledge_id = seeded
        _reject(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        held = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
        rejected = next(item for item in held if str(item.id) == knowledge_id)

        assert rejected.lifecycle is LifecycleState.REJECTED
        assert rejected.current_version.content == STATEMENT

    def test_the_reason_is_recorded(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """`reject_knowledge` used to accept a note and drop it on the floor."""

        project_id, knowledge_id = seeded

        _reject(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            reason_code="incorrect",
            note="The repository uses SQS, not SNS.",
        )

        history = context.memory.review_history(
            ProjectId(project_id), KnowledgeItemId(knowledge_id)
        )
        assert history[-1].action is ReviewAction.REJECTED
        assert history[-1].reason_code is RejectionReason.INCORRECT
        assert history[-1].note == "The repository uses SQS, not SNS."
        assert history[-1].actor_id == "cris"


class TestReasonDiscipline:
    def test_a_missing_reason_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = dispatch(
            context,
            "kae_reject_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": 1,
                "reviewer": "cris",
            },
        )

        assert result["error"] == "invalid_argument"

    def test_an_unknown_reason_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = _reject(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            reason_code="because-i-said-so",
        )

        assert result["error"] == "invalid_argument"

    def test_other_without_a_note_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """'other' with nothing else records that someone declined to say."""

        project_id, knowledge_id = seeded

        result = _reject(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            reason_code="other",
        )

        assert result["error"] == "invalid_argument"

    def test_other_with_a_note_is_accepted(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = _reject(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            reason_code="other",
            note="Superseded by a decision recorded outside this project.",
        )

        assert result["state"] == "rejected"


class TestRefusals:
    def test_another_project_cannot_reject_this_item(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        _, knowledge_id = seeded
        other_project, _ = _seed(context, "Other", "reject-other")

        result = _reject(
            context, project_id=other_project, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "knowledge_not_found"

    def test_a_stale_version_is_a_conflict(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        context.memory.correct_knowledge(
            KnowledgeItemId(knowledge_id), "Corrected wording.", source="interview"
        )

        result = _reject(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "version_conflict"

    def test_confirmed_knowledge_cannot_be_rejected_through_this_tool(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Retiring something already authoritative is supersession, not rejection."""

        project_id, knowledge_id = seeded
        context.memory.review_confirm(
            ProjectId(project_id), KnowledgeItemId(knowledge_id), expected_version=1
        )

        result = _reject(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "invalid_state_transition"

    def test_a_missing_reviewer_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = dispatch(
            context,
            "kae_reject_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": 1,
                "reason_code": "incorrect",
            },
        )

        assert result["error"] == "invalid_argument"
        assert "reviewer" in result["message"]


class TestReplay:
    def test_a_retry_records_one_rejection(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        arguments = {
            "project_id": project_id,
            "knowledge_id": knowledge_id,
            "expected_version": 1,
            "reason_code": "irrelevant",
            "reviewer": "cris",
            "idempotency_key": "reject-retry-1",
        }

        first = dispatch(context, "kae_reject_knowledge", arguments)
        second = dispatch(context, "kae_reject_knowledge", arguments)

        assert first["already_applied"] is False
        assert second["already_applied"] is True
        history = context.memory.review_history(
            ProjectId(project_id), KnowledgeItemId(knowledge_id)
        )
        assert len(history) == 1


class TestSearchEffect:
    def test_a_rejected_statement_leaves_search(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        before = dispatch(
            context,
            "kae_search_knowledge",
            {"project_id": project_id, "query": "publishes", "mode": "lexical"},
        )
        assert before["count"] >= 1

        _reject(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        after = dispatch(
            context,
            "kae_search_knowledge",
            {"project_id": project_id, "query": "publishes", "mode": "lexical"},
        )
        assert after["count"] == 0

    def test_it_remains_reachable_historically(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        _reject(context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1)

        assert context.retrieval is not None
        hits = context.retrieval.find(
            ProjectId(project_id), "publishes", limit=10, lifecycle=HISTORICAL
        )

        assert any(STATEMENT in hit.text for hit in hits)


class TestResultLabelling:
    def test_search_results_report_whether_a_person_confirmed_them(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, _ = seeded

        result = dispatch(
            context,
            "kae_search_knowledge",
            {"project_id": project_id, "query": "publishes", "mode": "lexical"},
        )

        assert result["results"]
        for entry in result["results"]:
            assert entry["state"] == "proposed"
            assert entry["authoritative"] is False
