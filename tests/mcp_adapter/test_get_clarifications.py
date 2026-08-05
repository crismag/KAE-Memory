"""The clarification read surface (T16).

The contract this settles: a clarification derived from a finding has no
identity, and `kae_answer_clarification` needs one. So this call materialises
the questions it returns. That is a mutation behind a `get_` name, and the
tests below hold it to being idempotent, bounded, project-scoped, and honest
about what it left out.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.workspace import MessageType
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

ASKABLE = {"missing_area", "partial_area", "open_question", "open_blocker"}


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
    """A project with almost nothing in it, so its gaps are real."""

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
def project_id(context: tools.ToolContext) -> str:
    return _project(context, "Ministry Reporting", "clarify-ministry")


def _get(context: tools.ToolContext, **arguments: object) -> dict[str, Any]:
    return dispatch(context, "kae_get_clarifications", dict(arguments))


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        assert "kae_get_clarifications" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_the_description_declares_that_it_records(self) -> None:
        """A `get_` that mutates must say so where a caller will read it."""

        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_get_clarifications")
        assert "record" in declaration["description"].lower()


class TestAnswerableIdentity:
    def test_every_question_carries_an_id(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The whole reason this call materialises."""

        result = _get(context, project_id=project_id)

        assert result["count"] > 0
        for question in result["questions"]:
            assert question["clarification_id"]

    def test_the_id_resolves_to_a_stored_question(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        from kae_memory.domain.identifiers import MessageId

        result = _get(context, project_id=project_id)
        first = result["questions"][0]["clarification_id"]

        message = context.memory.get_message(MessageId(first))
        assert message is not None
        assert message.message_type is MessageType.QUESTION
        assert message.project_id == ProjectId(project_id)

    def test_the_subject_is_preserved_on_the_question(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """`asks_about` is what survives once the finding is resolved away."""

        from kae_memory.application.clarification_service import ASKS_ABOUT
        from kae_memory.domain.identifiers import MessageId

        result = _get(context, project_id=project_id)
        message = context.memory.get_message(MessageId(result["questions"][0]["clarification_id"]))

        assert message is not None
        assert message.metadata.get(ASKS_ABOUT)


class TestIdempotence:
    def test_asking_twice_does_not_ask_twice(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A person must not be asked the same thing because a caller retried."""

        first = _get(context, project_id=project_id)
        second = _get(context, project_id=project_id)

        assert [q["clarification_id"] for q in first["questions"]] == [
            q["clarification_id"] for q in second["questions"]
        ]

    def test_the_second_call_reports_nothing_newly_asked(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _get(context, project_id=project_id)

        # `newly_asked` is diagnostic detail: whether *this* call materialised a
        # question is tracing information, not part of answering it. Below that
        # level the field is withheld, so asking for it is the only way to
        # observe the idempotence it records.
        second = _get(context, project_id=project_id, limit=50, detail="diagnostic")

        assert all(q["newly_asked"] is False for q in second["questions"])

    def test_the_tracing_fields_are_withheld_by_default(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """These two were declared as `questions[]....` and so matched nothing.

        Both shipped at every detail level while the field map said they did
        not. Nothing failed — the compaction simply was not happening.
        """

        questions = _get(context, project_id=project_id)["questions"]

        assert questions, "the project must raise questions or this proves nothing"
        for question in questions:
            assert "newly_asked" not in question
            assert "knowledge_ids" not in question

    def test_no_duplicate_question_messages_accumulate(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        for _ in range(3):
            _get(context, project_id=project_id, limit=50)

        sessions = context.memory.sessions_for_project(ProjectId(project_id))
        questions = [
            message
            for session in sessions
            for message in context.memory.messages_for_session(session.id)
            if message.message_type is MessageType.QUESTION
        ]
        assert len(questions) == len({str(m.content) for m in questions})


class TestWhatIsAsked:
    def test_only_answerable_gaps_are_returned(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """ "Confirm these candidates" is work, not a question."""

        result = _get(context, project_id=project_id, limit=50)

        assert result["questions"]
        for question in result["questions"]:
            assert question["finding_kind"] in ASKABLE

    def test_results_are_ordered_most_severe_first(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

        result = _get(context, project_id=project_id, limit=50)
        ranks = [order.get(q["severity"], 99) for q in result["questions"]]

        assert ranks == sorted(ranks)

    def test_an_answered_question_stops_being_offered(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        from kae_memory.domain.identifiers import MessageId

        first = _get(context, project_id=project_id, limit=50)
        answered = first["questions"][0]["clarification_id"]
        assert context.clarification is not None
        context.clarification.answer(
            ProjectId(project_id), MessageId(answered), "Roughly 25 ministries."
        )

        again = _get(context, project_id=project_id, limit=50)

        assert answered not in {q["clarification_id"] for q in again["questions"]}


class TestBounding:
    def test_the_default_bound_applies(self, context: tools.ToolContext, project_id: str) -> None:
        result = _get(context, project_id=project_id)

        assert result["count"] <= 10

    def test_a_bounded_result_says_what_it_left_out(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A short queue and a truncated one are indistinguishable otherwise."""

        result = _get(context, project_id=project_id, limit=1)

        assert result["count"] == 1
        assert result["omitted"] is not None
        assert result["omitted"]["available"] > 1

    def test_an_unbounded_result_reports_no_truncation(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        result = _get(context, project_id=project_id, limit=100)

        assert result["omitted"] is None

    def test_a_nonsense_limit_is_refused(self, context: tools.ToolContext, project_id: str) -> None:
        assert _get(context, project_id=project_id, limit=0)["error"] == "invalid_argument"


class TestIsolation:
    def test_another_project_sees_its_own_questions_only(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        other = _project(context, "Other Ministry", "clarify-other")

        mine = _get(context, project_id=project_id, limit=50)
        theirs = _get(context, project_id=other, limit=50)

        mine_ids = {q["clarification_id"] for q in mine["questions"]}
        their_ids = {q["clarification_id"] for q in theirs["questions"]}
        assert mine_ids
        assert their_ids
        assert not (mine_ids & their_ids)

    def test_an_unknown_project_is_refused(self, context: tools.ToolContext) -> None:
        result = _get(context, project_id="00000000-0000-0000-0000-000000000000")

        assert result["error"] == "project_not_found"


class TestServiceOwnership:
    """The defects this target fixes, at the layer that has to hold them."""

    def test_asked_does_not_leak_another_projects_session(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """`project_id` was accepted and ignored, so any session id was readable."""

        other = _project(context, "Other Ministry", "clarify-own-1")
        assert context.clarification is not None
        _get(context, project_id=other, limit=50)
        their_session = context.memory.sessions_for_project(ProjectId(other))[0]

        leaked = context.clarification.asked(ProjectId(project_id), their_session.id)

        assert leaked == ()

    def test_unanswered_does_not_leak_another_projects_session(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        other = _project(context, "Other Ministry", "clarify-own-2")
        assert context.clarification is not None
        _get(context, project_id=other, limit=50)
        their_session = context.memory.sessions_for_project(ProjectId(other))[0]

        leaked = context.clarification.unanswered(ProjectId(project_id), their_session.id)

        assert leaked == ()

    def test_answering_another_projects_question_is_refused(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """This wrote into the *other* project's session while claiming this id."""

        from kae_memory.domain.identifiers import MessageId

        other = _project(context, "Other Ministry", "clarify-own-3")
        theirs = _get(context, project_id=other, limit=50)["questions"][0]["clarification_id"]
        assert context.clarification is not None

        with pytest.raises(LookupError):
            context.clarification.answer(
                ProjectId(project_id), MessageId(theirs), "An answer from elsewhere."
            )
