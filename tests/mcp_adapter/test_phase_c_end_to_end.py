"""The whole Phase C review workflow, through MCP, in one scenario (T15).

Each review tool is tested in isolation elsewhere. This exists because a system
can be correct in every part and wrong in aggregate: three tools that each
behave, over a project whose knowledge, search results, audit trail, and
readiness no longer agree with one another.

One project, three proposals, every decision, and then the questions a person
would actually ask afterwards — what does this project say, what did we turn
down, and who decided.
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
from kae_memory.domain.lifecycle import AUTHORITATIVE, HISTORICAL
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch
from kae_memory.persistence.chunk_repository import ChunkRepository

VALID = "Only an authorised approver may approve a report."
INVALID = "The service publishes reports over SNS."
INACCURATE = "Reports are filed quarterly."
CORRECTED = "Reports are filed monthly."
ALREADY_CONFIRMED = "Every approval is recorded against a named person."
REWORDED = "Every approval records the person who granted it."


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


@pytest.fixture
def reviewed(context: tools.ToolContext, factory: sessionmaker[Session]) -> dict[str, object]:
    """Run the full workflow once; every test below reads its outcome.

    Built as a fixture rather than one long test so a failure names the
    property that broke rather than the step it broke on.
    """

    project = context.memory.create_project("Ministry Reporting", key="phase-c-e2e")
    other = context.memory.create_project("Other Ministry", key="phase-c-other")
    run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, "e2e-seed")
    written = context.memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind="goal", content=text, source="interview")
            for text in (VALID, INVALID, INACCURATE, ALREADY_CONFIRMED)
        ],
    )
    valid, invalid, inaccurate, confirmed_already = (str(item.id) for item in written)

    # A statement confirmed before this session, to correct later.
    context.memory.review_confirm(
        project.id, KnowledgeItemId(confirmed_already), expected_version=1, actor_id="cris"
    )

    common = {"project_id": str(project.id), "reviewer": "cris"}

    results = {
        "confirm": dispatch(
            context,
            "kae_confirm_knowledge",
            {**common, "knowledge_id": valid, "expected_version": 1, "idempotency_key": "e2e-c"},
        ),
        "reject": dispatch(
            context,
            "kae_reject_knowledge",
            {
                **common,
                "knowledge_id": invalid,
                "expected_version": 1,
                "reason_code": "incorrect",
                "note": "The repository uses SQS.",
            },
        ),
        "correct_proposed": dispatch(
            context,
            "kae_correct_knowledge",
            {
                **common,
                "knowledge_id": inaccurate,
                "expected_version": 1,
                "content": CORRECTED,
            },
        ),
        "correct_confirmed": dispatch(
            context,
            "kae_correct_knowledge",
            {
                **common,
                "knowledge_id": confirmed_already,
                "expected_version": 1,
                "content": REWORDED,
            },
        ),
    }

    # A retry of a completed decision.
    results["retry"] = dispatch(
        context,
        "kae_confirm_knowledge",
        {**common, "knowledge_id": valid, "expected_version": 1, "idempotency_key": "e2e-c"},
    )
    # A decision written against wording that has since moved.
    results["stale"] = dispatch(
        context,
        "kae_confirm_knowledge",
        {**common, "knowledge_id": inaccurate, "expected_version": 1},
    )
    # A neighbouring project reaching for knowledge it does not own.
    results["cross_project"] = dispatch(
        context,
        "kae_confirm_knowledge",
        {
            "project_id": str(other.id),
            "reviewer": "cris",
            "knowledge_id": valid,
            "expected_version": 1,
        },
    )

    return {
        "project_id": str(project.id),
        "other_id": str(other.id),
        "valid": valid,
        "invalid": invalid,
        "inaccurate": inaccurate,
        "confirmed_already": confirmed_already,
        "results": results,
        "factory": factory,
    }


def _search(context: tools.ToolContext, project_id: str, query: str) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_search_knowledge",
        {"project_id": project_id, "query": query, "mode": "lexical", "limit": 20},
    )


class TestDecisionsLand:
    def test_the_valid_statement_is_authoritative(self, reviewed: dict[str, Any]) -> None:
        assert reviewed["results"]["confirm"]["state"] == "validated"
        assert reviewed["results"]["confirm"]["authoritative"] is True

    def test_the_invalid_statement_is_rejected(self, reviewed: dict[str, Any]) -> None:
        assert reviewed["results"]["reject"]["state"] == "rejected"

    def test_correcting_a_proposal_accepts_it(self, reviewed: dict[str, Any]) -> None:
        assert reviewed["results"]["correct_proposed"]["state"] == "validated"
        assert reviewed["results"]["correct_proposed"]["replaced_version"] == 1

    def test_correcting_confirmed_knowledge_returns_it_for_review(
        self, reviewed: dict[str, Any]
    ) -> None:
        assert reviewed["results"]["correct_confirmed"]["state"] == "proposed"
        assert reviewed["results"]["correct_confirmed"]["authoritative"] is False


class TestRefusalsHold:
    def test_the_retry_changed_nothing(self, reviewed: dict[str, Any]) -> None:
        assert reviewed["results"]["retry"]["already_applied"] is True
        assert reviewed["results"]["retry"]["readiness_changed"] is False

    def test_the_stale_decision_was_refused(self, reviewed: dict[str, Any]) -> None:
        assert reviewed["results"]["stale"]["error"] == "version_conflict"

    def test_the_cross_project_decision_was_refused(self, reviewed: dict[str, Any]) -> None:
        assert reviewed["results"]["cross_project"]["error"] == "knowledge_not_found"

    def test_the_neighbouring_project_holds_no_review_history(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        """A refused decision must not leave a trace in the project that tried."""

        events = context.memory.review_history_for_project(ProjectId(reviewed["other_id"]))

        assert events == ()


class TestWhatTheProjectNowSays:
    def test_rejected_knowledge_is_gone_from_search(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        result = _search(context, reviewed["project_id"], "publishes")

        assert result["matched_chunks"] == 0

    def test_corrected_wording_is_what_search_returns(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        assert _search(context, reviewed["project_id"], "monthly")["matched_chunks"] == 1
        assert _search(context, reviewed["project_id"], "quarterly")["matched_chunks"] == 0

    def test_every_result_says_whether_a_person_confirmed_it(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        result = _search(context, reviewed["project_id"], "approval OR approver OR filed")

        for entry in result["results"]:
            assert entry["state"] in {"proposed", "validated"}
            assert isinstance(entry["authoritative"], bool)

    def test_authoritative_retrieval_excludes_what_awaits_review(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        """The reworded statement is proposed again and must not be quoted as fact."""

        assert context.retrieval is not None
        hits = context.retrieval.find(
            ProjectId(reviewed["project_id"]), "approval", limit=20, lifecycle=AUTHORITATIVE
        )

        assert not any(REWORDED in hit.text for hit in hits)

    def test_nothing_leaked_into_the_neighbouring_project(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        assert _search(context, reviewed["other_id"], "approver")["matched_chunks"] == 0


class TestTheRecordSurvives:
    def test_the_rejected_statement_is_still_readable(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        """Rejection is not deletion."""

        assert context.retrieval is not None
        hits = context.retrieval.find(
            ProjectId(reviewed["project_id"]), "publishes", limit=20, lifecycle=HISTORICAL
        )

        assert any(INVALID in hit.text for hit in hits)

    def test_the_original_wording_of_a_correction_is_preserved(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        held = context.memory.retrieve_knowledge(ProjectId(reviewed["project_id"]), lifecycle=None)
        item = next(i for i in held if str(i.id) == reviewed["inaccurate"])

        assert item.versions[0].content == INACCURATE
        assert item.current_version.content == CORRECTED

    def test_why_the_rejection_happened_is_on_the_record(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        history = context.memory.review_history(
            ProjectId(reviewed["project_id"]), KnowledgeItemId(reviewed["invalid"])
        )

        assert history[-1].reason_code is not None
        assert history[-1].note == "The repository uses SQS."

    def test_the_project_log_holds_one_event_per_decision(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        """Four decisions were made. The retry, the stale request, and the
        cross-project attempt must not have added a fifth."""

        events = context.memory.review_history_for_project(ProjectId(reviewed["project_id"]))

        # The pre-session confirmation, plus confirm, reject, and two corrections.
        assert len(events) == 5
        assert [event.action for event in events].count(ReviewAction.CORRECTED) == 2

    def test_every_decision_names_who_made_it(
        self, context: tools.ToolContext, reviewed: dict[str, Any]
    ) -> None:
        events = context.memory.review_history_for_project(ProjectId(reviewed["project_id"]))

        assert all(event.actor_id == "cris" for event in events)
        assert all(event.created_at.tzinfo is not None for event in events)


class TestEmbeddingHandoff:
    def test_corrected_content_is_queued_for_re_embedding(self, reviewed: dict[str, Any]) -> None:
        factory = reviewed["factory"]

        with factory() as db:
            chunks = ChunkRepository(db).list_for_knowledge(KnowledgeItemId(reviewed["inaccurate"]))

        assert chunks
        assert all(chunk.state is EmbeddingState.STALE for chunk in chunks)

    def test_the_existing_workflow_picks_the_correction_up(self, reviewed: dict[str, Any]) -> None:
        factory = reviewed["factory"]

        with factory() as db:
            outstanding = ChunkRepository(db).list_needing_embedding(
                ProjectId(reviewed["project_id"]), limit=100
            )

        assert any(CORRECTED in chunk.text for chunk in outstanding)
