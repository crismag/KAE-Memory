"""Answering without deciding, through the tool a person actually uses (N36).

The manual test that produced this target: KAE asked one question, the answer
was "I don't know yet. Recommend something reasonable for a prototype, but don't
make it a permanent project decision", and there was no way to record that. The
tool had one outcome — answered — and taking it would have written a decision
nobody made into the project.

These assertions are about the **lifecycle**, not about wording:

    a settling answer closes the question and it leaves the queue;
    a non-settling one is recorded and the question stays unresolved;
    an unresolved question is not asked again on the next call, and is counted;
    the response says which happened rather than making a caller infer it;
    answering later is not a correction, because nothing was decided before;
    a stand-in answer without its assumption is refused.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        clarification=ClarificationService(factory),
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Sparse Inbox", key="n36-inbox").id)


@pytest.fixture
def question(context: tools.ToolContext, project_id: str) -> dict[str, Any]:
    """The first question this project's own findings justify asking.

    Derived, not invented: a test that made up a clarification id would prove
    the tool accepts arguments, not that the queue behaves.
    """

    payload = dispatch(context, "kae_get_clarifications", {"project_id": project_id})
    questions = payload["questions"]
    assert questions, "an empty project must have something to ask about"
    return dict(questions[0])


def _answer(
    context: tools.ToolContext, project_id: str, question_id: str, **extra: Any
) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_answer_clarification",
        {
            "project_id": project_id,
            "clarification_id": question_id,
            "answer": "I don't know yet. Something reasonable for a prototype.",
            **extra,
        },
    )


def _list(context: tools.ToolContext, project_id: str, **extra: Any) -> dict[str, Any]:
    return dispatch(
        context, "kae_get_clarifications", {"project_id": project_id, "limit": 50, **extra}
    )


def _open_ids(context: tools.ToolContext, project_id: str, **extra: Any) -> set[str]:
    payload = _list(context, project_id, **extra)
    return {str(question["clarification_id"]) for question in payload["questions"]}


class TestADecisionClosesTheQuestion:
    def test_an_answer_settles_it(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        payload = _answer(context, project_id, question["clarification_id"], disposition="answered")

        assert payload["question_settled"] is True
        assert payload["still_open"] is False

    def test_a_settled_question_leaves_the_queue(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        _answer(context, project_id, question["clarification_id"], disposition="answered")

        assert question["clarification_id"] not in _open_ids(context, project_id)

    def test_answered_is_the_default(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """The ordinary case must not need a caller to know a new parameter."""

        payload = _answer(context, project_id, question["clarification_id"])

        assert payload["disposition"] == "answered"
        assert payload["question_settled"] is True


class TestUncertaintyIsRecordedAndDecidesNothing:
    @pytest.mark.parametrize("disposition", ["unknown_by_user", "deferred"])
    def test_the_question_stays_open(
        self,
        context: tools.ToolContext,
        project_id: str,
        question: dict[str, Any],
        disposition: str,
    ) -> None:
        """The target in one assertion. Nobody decided, so nothing is decided."""

        payload = _answer(
            context, project_id, question["clarification_id"], disposition=disposition
        )

        assert payload["question_settled"] is False
        assert payload["still_open"] is True
        assert question["clarification_id"] in _open_ids(context, project_id, include_deferred=True)

    def test_what_the_person_said_is_still_stored(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """Not settling is not discarding. "I don't know yet" is evidence about
        the project, and losing it would be the other half of the same defect."""

        payload = _answer(
            context, project_id, question["clarification_id"], disposition="unknown_by_user"
        )

        assert payload["answer_id"]
        sessions = context.memory.sessions_for_project(ProjectId(project_id))
        stored = [
            message
            for session in sessions
            for message in context.memory.messages_for_session(session.id)
        ]
        assert any("I don't know yet" in message.content for message in stored)

    def test_it_is_still_extracted(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """Uncertainty is often informative — "not for a prototype" is a
        constraint. Skipping extraction would throw that away."""

        payload = _answer(context, project_id, question["clarification_id"], disposition="deferred")

        assert payload["extraction_run_id"]

    def test_the_caller_is_told_the_question_will_return(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """An agent that reported this as resolved would be reporting a
        decision, so the response says out loud that it is not one."""

        payload = _answer(context, project_id, question["clarification_id"], disposition="deferred")

        assert any("stays open" in step for step in payload["next_steps"])

    def test_deciding_later_is_not_a_correction(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """The point of deferring. A person who says "I don't know yet" must be
        able to come back and say what they chose, and a conflict there would
        make deferring a trap."""

        _answer(context, project_id, question["clarification_id"], disposition="deferred")

        settled = dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": question["clarification_id"],
                "answer": "Markdown files on disk.",
                "disposition": "answered",
            },
        )

        assert settled.get("error") is None
        assert settled["question_settled"] is True
        assert question["clarification_id"] not in _open_ids(context, project_id)

    def test_a_second_real_answer_still_conflicts(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """Deferring loosened the rule for undecided questions only. Two
        different decisions for one question is still a contradiction."""

        _answer(context, project_id, question["clarification_id"], disposition="answered")

        second = dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": question["clarification_id"],
                "answer": "Something else entirely.",
                "disposition": "answered",
                # A different key: the same key is a retry, and a retry of an
                # answer is safe. What must not pass is a second, different
                # decision for one question.
                "idempotency_key": "a-different-key",
            },
        )

        assert second["error"] == "conflict"


class TestUnresolvedIsNotTheSameAsAskedAgain:
    """The other half of the acceptance criterion. A question that stays open
    must not be re-offered on every call — a person who says "I don't know yet"
    and is asked the same thing next turn learns to stop reading the list."""

    def test_a_deferred_question_is_not_asked_again(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        _answer(context, project_id, question["clarification_id"], disposition="deferred")

        assert question["clarification_id"] not in _open_ids(context, project_id)

    def test_it_is_counted_rather_than_dropped(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """Held back is not resolved. A count that ignored these would let a
        project look finished while questions went unanswered."""

        before = _list(context, project_id)["deferred"]

        _answer(context, project_id, question["clarification_id"], disposition="deferred")

        assert _list(context, project_id)["deferred"] == before + 1

    def test_asking_for_it_returns_it_with_what_was_said(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        _answer(context, project_id, question["clarification_id"], disposition="unknown_by_user")

        listed = _list(context, project_id, include_deferred=True)["questions"]
        found = next(
            item for item in listed if item["clarification_id"] == question["clarification_id"]
        )

        assert found["disposition"] == "unknown_by_user"

    def test_an_untouched_question_reports_no_response(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """`open` means nobody was asked yet, and must stay distinguishable
        from "asked, and they did not know"."""

        assert question["disposition"] == "open"

    def test_deciding_it_later_removes_it_from_both(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        _answer(context, project_id, question["clarification_id"], disposition="deferred")
        _answer(
            context,
            project_id,
            question["clarification_id"],
            answer="Markdown files on disk.",
            disposition="answered",
        )

        assert question["clarification_id"] not in _open_ids(
            context, project_id, include_deferred=True
        )
        assert _list(context, project_id)["deferred"] == 0


class TestAStandInNeedsSomethingToStandOn:
    def test_delegation_without_an_assumption_is_refused(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """ "You choose" produces a choice. A choice with no assumption record is
        one nobody can find later to revisit — which is exactly what the person
        asked for when they said "don't make it permanent"."""

        payload = _answer(
            context, project_id, question["clarification_id"], disposition="delegated"
        )

        assert payload["error"] == "invalid_argument"

    def test_delegation_with_an_assumption_is_recorded_and_stays_open(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        payload = _answer(
            context,
            project_id,
            question["clarification_id"],
            disposition="delegated",
            assumption_id="assumption-1",
        )

        assert payload["assumption_id"] == "assumption-1"
        assert payload["question_settled"] is False
        assert question["clarification_id"] in _open_ids(context, project_id, include_deferred=True)

    def test_an_unknown_disposition_is_refused(
        self, context: tools.ToolContext, project_id: str, question: dict[str, Any]
    ) -> None:
        """Ignoring it would silently settle a question the caller meant to
        leave open — the worst available failure."""

        payload = _answer(context, project_id, question["clarification_id"], disposition="maybe")

        assert payload["error"] == "invalid_argument"


class TestTheContractIsDiscoverable:
    def test_the_schema_offers_the_dispositions(self) -> None:
        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_answer_clarification")
        offered = set(definition["inputSchema"]["properties"]["disposition"]["enum"])

        assert {"answered", "deferred", "unknown_by_user", "delegated"} <= offered

    def test_the_schema_does_not_offer_states_a_caller_cannot_choose(self) -> None:
        """`open` and `suggested` are where a question lives before anyone
        responds. Offering them would invite a caller to "record" nothing."""

        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_answer_clarification")
        offered = set(definition["inputSchema"]["properties"]["disposition"]["enum"])

        assert not {"open", "suggested", "superseded"} & offered

    def test_the_description_says_uncertainty_does_not_close(self) -> None:
        """An agent reads this and nothing else before choosing a disposition."""

        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_answer_clarification")

        assert "leaves it open" in definition["description"]
