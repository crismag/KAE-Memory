"""The clarification answer surface (T17).

The assertion that matters most here is not that an answer is stored. It is
that the response never says knowledge changed, because it has not: the answer
is evidence, extraction is queued, and what extraction produces is a candidate a
person still confirms.

A caller that reads "answered" as "the project now knows this" would be acting
on an unreviewed claim, which is the failure the whole review model exists to
prevent. So the three facts stay separate, and no response profile may compact
them together.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ANSWERS, ASKS_ABOUT, ClarificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import MessageId, ProjectId
from kae_memory.domain.workspace import ActorType, MessageType
from kae_memory.mcp import tools
from kae_memory.mcp.response_policy import INTEGRITY_FIELDS
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

ANSWER = "Roughly 25 ministries file reports, and the finance team reviews them."


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    memory = MemoryService(factory)
    return tools.ToolContext(
        memory=memory,
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        embedder_name="deterministic",
        clarification=ClarificationService(factory, memory),
    )


def _project(context: tools.ToolContext, name: str, key: str) -> str:
    project = context.memory.create_project(name, key=key)
    run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, f"{key}-seed")
    context.memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="goal", content="Ministries file monthly reports.", source="interview"
            )
        ],
    )
    return str(project.id)


@pytest.fixture
def asked(context: tools.ToolContext) -> tuple[str, str]:
    """A project with one open, answerable question."""

    project_id = _project(context, "Ministry Reporting", "answer-ministry")
    listed = dispatch(context, "kae_get_clarifications", {"project_id": project_id, "limit": 1})
    return project_id, listed["questions"][0]["clarification_id"]


def _answer(context: tools.ToolContext, **arguments: object) -> dict[str, Any]:
    arguments.setdefault("answer", ANSWER)
    return dispatch(context, "kae_answer_clarification", dict(arguments))


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        assert "kae_answer_clarification" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_the_description_says_knowledge_is_not_yet_changed(self) -> None:
        """A caller reads this before deciding what the call means."""

        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_answer_clarification")
        description = declaration["description"].lower()

        assert "evidence" in description
        assert "confirm" in description


class TestReportingIntegrity:
    """The point of the target."""

    def test_the_response_says_knowledge_has_not_changed(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked

        result = _answer(context, project_id=project_id, clarification_id=clarification_id)

        assert result["status"] == "answered"
        assert result["knowledge_state"] == "pending_extraction"
        assert result["knowledge_changed"] is False
        assert result["readiness_changed"] is False

    def test_no_knowledge_is_actually_created(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """The response would be a lie if this were not true."""

        project_id, clarification_id = asked
        before = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)

        _answer(context, project_id=project_id, clarification_id=clarification_id)

        after = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
        assert len(after) == len(before)

    def test_the_knowledge_revision_does_not_advance(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked
        before = context.readiness.knowledge_revision(ProjectId(project_id))

        result = _answer(context, project_id=project_id, clarification_id=clarification_id)

        assert result["knowledge_revision"] == before

    def test_the_integrity_fields_survive_compaction(self) -> None:
        """An economy profile must not turn 'answered' into 'known'."""

        for field in ("knowledge_state", "knowledge_changed"):
            assert field in INTEGRITY_FIELDS

    def test_extraction_is_scheduled_not_run(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked

        result = _answer(context, project_id=project_id, clarification_id=clarification_id)

        runs = context.memory.runs_for_project(ProjectId(project_id))
        queued = next(r for r in runs if str(r.id) == result["extraction_run_id"])
        assert queued.status is RunStatus.PENDING
        assert queued.role is AgentRole.REQUIREMENTS


class TestTheAnswerItself:
    def test_it_is_stored_verbatim(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """Rewriting a person's words would break the provenance chain."""

        project_id, clarification_id = asked

        result = _answer(context, project_id=project_id, clarification_id=clarification_id)

        stored = context.memory.get_message(MessageId(result["answer_id"]))
        assert stored is not None
        assert stored.content == ANSWER
        assert stored.message_type is MessageType.ANSWER

    def test_it_is_attributed_to_a_person(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked

        result = _answer(
            context,
            project_id=project_id,
            clarification_id=clarification_id,
            actor_id="cris",
        )

        stored = context.memory.get_message(MessageId(result["answer_id"]))
        assert stored is not None
        assert stored.actor_type is ActorType.USER
        assert stored.actor_id == "cris"

    def test_it_links_back_to_its_question(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked

        result = _answer(context, project_id=project_id, clarification_id=clarification_id)

        stored = context.memory.get_message(MessageId(result["answer_id"]))
        assert stored is not None
        assert str(stored.metadata[ANSWERS]) == clarification_id

    def test_it_carries_the_subject_forward(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """So the subject survives once the finding that prompted it is gone."""

        project_id, clarification_id = asked

        result = _answer(context, project_id=project_id, clarification_id=clarification_id)

        stored = context.memory.get_message(MessageId(result["answer_id"]))
        assert stored is not None
        assert stored.metadata.get(ASKS_ABOUT)


class TestOneAnswer:
    def test_a_retry_records_one_answer(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked
        arguments = {
            "project_id": project_id,
            "clarification_id": clarification_id,
            "answer": ANSWER,
            "idempotency_key": "answer-retry-1",
        }

        first = dispatch(context, "kae_answer_clarification", arguments)
        second = dispatch(context, "kae_answer_clarification", arguments)

        assert first["replayed"] is False
        assert second["replayed"] is True
        assert second["answer_id"] == first["answer_id"]

    def test_a_retry_does_not_queue_a_second_extraction(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """Two runs over one answer would propose the same knowledge twice."""

        project_id, clarification_id = asked
        arguments = {
            "project_id": project_id,
            "clarification_id": clarification_id,
            "answer": ANSWER,
            "idempotency_key": "answer-retry-2",
        }

        first = dispatch(context, "kae_answer_clarification", arguments)
        second = dispatch(context, "kae_answer_clarification", arguments)

        assert second["extraction_run_id"] == first["extraction_run_id"]

    def test_a_different_answer_to_the_same_question_is_refused(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """Nothing downstream could say which one the project believes."""

        project_id, clarification_id = asked
        _answer(context, project_id=project_id, clarification_id=clarification_id)

        result = _answer(
            context,
            project_id=project_id,
            clarification_id=clarification_id,
            answer="Something else entirely.",
            idempotency_key="a-different-key",
        )

        assert result["error"] == "conflict"

    def test_an_answered_question_leaves_the_open_list(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked

        _answer(context, project_id=project_id, clarification_id=clarification_id)

        listed = dispatch(
            context, "kae_get_clarifications", {"project_id": project_id, "limit": 50}
        )
        assert clarification_id not in {q["clarification_id"] for q in listed["questions"]}


class TestRefusals:
    def test_an_empty_answer_is_refused(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """It records that someone was asked and says nothing about what they know."""

        project_id, clarification_id = asked

        result = _answer(
            context, project_id=project_id, clarification_id=clarification_id, answer="   "
        )

        assert result["error"] == "invalid_argument"

    def test_another_project_cannot_answer_this_question(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        """This once wrote into the other project's session."""

        _, clarification_id = asked
        other = _project(context, "Other Ministry", "answer-other")

        result = _answer(context, project_id=other, clarification_id=clarification_id)

        assert result["error"] == "knowledge_not_found"

    def test_a_message_that_is_not_a_question_is_refused(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, clarification_id = asked
        first = _answer(context, project_id=project_id, clarification_id=clarification_id)

        result = _answer(context, project_id=project_id, clarification_id=first["answer_id"])

        assert result["error"] in {"invalid_argument", "knowledge_not_found"}

    def test_an_unknown_clarification_is_refused(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        project_id, _ = asked

        result = _answer(
            context, project_id=project_id, clarification_id="00000000-0000-0000-0000-000000000000"
        )

        assert result["error"] == "knowledge_not_found"

    def test_no_failure_leaks_a_connection_string(
        self, context: tools.ToolContext, asked: tuple[str, str]
    ) -> None:
        _, clarification_id = asked
        other = _project(context, "Other Ministry", "answer-other-2")

        result = _answer(context, project_id=other, clarification_id=clarification_id)

        assert "postgresql" not in str(result)
        assert "cockroachdb" not in str(result)
