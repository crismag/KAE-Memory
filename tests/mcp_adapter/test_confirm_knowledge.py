"""The MCP confirmation surface (T12).

What a caller can do wrong here is more interesting than what it can do right:
confirm someone else's knowledge, confirm wording that has since changed, or
retry a call and record a second decision. Each is checked through ``dispatch``,
because that is the path a client actually takes and it converts exceptions into
the structured payloads a client reads.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.workspace import ActorType
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

STATEMENT = "Only an authorised approver may approve a report."


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
    """Return one project id and one proposed knowledge id."""

    project = context.memory.create_project(name, key=key)
    run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, f"{key}-seed")
    written = context.memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="requirement", content=STATEMENT, source="interview")],
    )
    return str(project.id), str(written[0].id)


@pytest.fixture
def seeded(context: tools.ToolContext) -> tuple[str, str]:
    return _seed(context, "Ministry Reporting", "confirm-ministry")


def _confirm(context: tools.ToolContext, **arguments: object) -> dict:
    """Dispatch a confirmation, defaulting the reviewer.

    `reviewer` is required by the tool, so a test that is not about attribution
    supplies one rather than repeating it at every call site.
    """

    arguments.setdefault("reviewer", "cris")
    return dispatch(context, "kae_confirm_knowledge", dict(arguments))


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        """A wrapper that exists but is not declared is unreachable by clients."""

        assert "kae_confirm_knowledge" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_the_declaration_requires_a_version(self) -> None:
        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_confirm_knowledge")
        assert "expected_version" in declaration["inputSchema"]["required"]

    def test_the_declaration_requires_a_named_reviewer(self) -> None:
        """FR-005 is no longer structural here; attribution is what is left."""

        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_confirm_knowledge")
        assert "reviewer" in declaration["inputSchema"]["required"]


class TestConfirmation:
    def test_a_proposed_statement_becomes_authoritative(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = _confirm(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["state"] == "validated"
        assert result["authoritative"] is True
        assert result["already_applied"] is False

    def test_the_response_stays_compact(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """A mutation reports what changed, not the whole project (ADR-0021)."""

        project_id, knowledge_id = seeded

        result = _confirm(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert set(result) == {
            "knowledge_id",
            "state",
            "version",
            "authoritative",
            "already_applied",
            "knowledge_revision",
            "readiness_changed",
        }


class TestRefusals:
    def test_another_project_cannot_confirm_this_item(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        _, knowledge_id = seeded
        other_project, _ = _seed(context, "Other", "confirm-other")

        result = _confirm(
            context, project_id=other_project, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "knowledge_not_found"

    def test_a_foreign_item_is_indistinguishable_from_a_missing_one(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Otherwise the error confirms that an unreachable item exists."""

        _, knowledge_id = seeded
        other_project, _ = _seed(context, "Other", "confirm-other-2")

        foreign = _confirm(
            context, project_id=other_project, knowledge_id=knowledge_id, expected_version=1
        )
        missing = _confirm(
            context, project_id=other_project, knowledge_id="no-such-item", expected_version=1
        )

        assert foreign["error"] == missing["error"]

    def test_a_stale_version_is_a_conflict_not_a_success(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        context.memory.correct_knowledge(
            _knowledge_id(knowledge_id), "Corrected wording.", source="interview"
        )

        result = _confirm(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "version_conflict"

    def test_a_missing_version_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """Without it there is no way to know what the reviewer read."""

        project_id, knowledge_id = seeded

        result = _confirm(context, project_id=project_id, knowledge_id=knowledge_id)

        assert result["error"] == "invalid_argument"

    def test_rejected_knowledge_cannot_be_confirmed(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        context.memory.reject_knowledge(_knowledge_id(knowledge_id))

        result = _confirm(
            context, project_id=project_id, knowledge_id=knowledge_id, expected_version=1
        )

        assert result["error"] == "invalid_state_transition"

    def test_no_failure_leaks_a_connection_string(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        _, knowledge_id = seeded
        other_project, _ = _seed(context, "Other", "confirm-other-3")

        result = _confirm(
            context, project_id=other_project, knowledge_id=knowledge_id, expected_version=1
        )

        assert "postgresql" not in str(result)
        assert "cockroachdb" not in str(result)


class TestReplay:
    def test_a_retry_with_the_same_key_records_one_decision(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        arguments = {
            "project_id": project_id,
            "knowledge_id": knowledge_id,
            "expected_version": 1,
            "reviewer": "cris",
            "idempotency_key": "retry-1",
        }

        first = _confirm(context, **arguments)
        second = _confirm(context, **arguments)

        assert first["already_applied"] is False
        assert second["already_applied"] is True
        history = context.memory.review_history(ProjectId(project_id), _knowledge_id(knowledge_id))
        assert len(history) == 1

    def test_a_replay_does_not_claim_readiness_changed_again(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded
        arguments = {
            "project_id": project_id,
            "knowledge_id": knowledge_id,
            "expected_version": 1,
            "reviewer": "cris",
            "idempotency_key": "retry-2",
        }
        _confirm(context, **arguments)

        second = _confirm(context, **arguments)

        assert second["readiness_changed"] is False


class TestAttribution:
    def test_a_confirmation_without_a_reviewer_is_refused(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """An agent not told who is confirming cannot record that a person did.

        This is the residual protection after FR-005 stopped being structural:
        the surface may relay a human decision, never originate one.
        """

        project_id, knowledge_id = seeded

        result = dispatch(
            context,
            "kae_confirm_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": 1,
            },
        )

        assert result["error"] == "invalid_argument"
        assert "reviewer" in result["message"]

    def test_a_blank_reviewer_does_not_satisfy_attribution(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        result = dispatch(
            context,
            "kae_confirm_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": 1,
                "reviewer": "   ",
            },
        )

        assert result["error"] == "invalid_argument"


class TestActorHonesty:
    def test_an_agent_submission_is_recorded_as_an_agent(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        """This used to be recorded as USER, putting model output under the
        actor type reserved for a person."""

        project_id, _ = seeded
        dispatch(
            context,
            "kae_submit_observation",
            {
                "project_id": project_id,
                "observation": "The approval step is undocumented.",
                "idempotency_key": "obs-1",
            },
        )

        sessions = context.memory.sessions_for_project(ProjectId(project_id))
        messages = context.memory.messages_for_session(sessions[0].id)
        assert messages[-1].actor_type is ActorType.AGENT

    def test_a_confirmation_is_recorded_as_a_person(
        self, context: tools.ToolContext, seeded: tuple[str, str]
    ) -> None:
        project_id, knowledge_id = seeded

        _confirm(
            context,
            project_id=project_id,
            knowledge_id=knowledge_id,
            expected_version=1,
            reviewer="cris",
        )

        history = context.memory.review_history(ProjectId(project_id), _knowledge_id(knowledge_id))
        assert history[0].actor_type is ActorType.USER
        assert history[0].actor_id == "cris"


def _knowledge_id(value: str):
    from kae_memory.domain.identifiers import KnowledgeItemId

    return KnowledgeItemId(value)
