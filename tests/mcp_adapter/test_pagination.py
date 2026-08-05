"""Pagination, limits, and detail levels on read tools (T4, ADR-0021).

The wrapper shape was fixed in ADR-0021 §Coordination so that this work
populates it rather than designing it. What these tests defend is the one
property a caller cannot recover for itself:

    `total` counts everything, not the page.

An agent that read twenty of forty open decisions and believed it had seen them
all would plan around a project it has only partly understood — and nothing in
the response would tell it otherwise. That is why `total` is the count before
limiting, and why a cursor that cannot be read is an error rather than a
silent restart from the top.
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
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.workspace import SessionType
from kae_memory.mcp import response_policy, tools
from kae_memory.mcp.response_policy import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidPolicyError,
    paginate,
)
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
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        embedder_name="deterministic",
    )


class TestTheWrapper:
    """The shape ADR-0021 fixed: {total, page, cursor, results}."""

    def test_the_wrapper_has_exactly_the_agreed_keys(self) -> None:
        page = paginate(list(range(5)))

        assert set(page) == {"total", "page", "cursor", "results"}

    def test_total_counts_everything_not_the_page(self) -> None:
        """The assertion this whole file exists for."""

        page = paginate(list(range(40)), limit=20)

        assert page["total"] == 40
        assert len(page["results"]) == 20

    def test_the_cursor_advances_and_then_stops(self) -> None:
        first = paginate(list(range(25)), limit=10)
        second = paginate(list(range(25)), limit=10, cursor=first["cursor"])
        third = paginate(list(range(25)), limit=10, cursor=second["cursor"])

        assert first["cursor"] == "10"
        assert second["cursor"] == "20"
        assert third["cursor"] is None, "absent means finished, not unknown"
        assert first["results"] + second["results"] + third["results"] == list(range(25))

    def test_page_numbers_are_one_based(self) -> None:
        first = paginate(list(range(30)), limit=10)
        second = paginate(list(range(30)), limit=10, cursor=first["cursor"])

        assert first["page"] == 1
        assert second["page"] == 2

    def test_a_single_page_carries_no_cursor(self) -> None:
        page = paginate([1, 2, 3], limit=10)

        assert page["cursor"] is None
        assert page["total"] == 3

    def test_an_empty_result_is_still_the_wrapper(self) -> None:
        """Zero results and a failure must not look alike."""

        page = paginate([])

        assert page == {"total": 0, "page": 1, "cursor": None, "results": []}


class TestLimits:
    def test_the_default_applies_when_none_is_given(self) -> None:
        page = paginate(list(range(200)))

        assert len(page["results"]) == DEFAULT_PAGE_SIZE

    def test_the_ceiling_cannot_be_raised(self) -> None:
        """A page is a budget, not a suggestion."""

        page = paginate(list(range(500)), limit=10_000)

        assert len(page["results"]) == MAX_PAGE_SIZE

    def test_a_zero_or_negative_limit_still_returns_something(self) -> None:
        assert len(paginate(list(range(10)), limit=0)["results"]) == 1
        assert len(paginate(list(range(10)), limit=-5)["results"]) == 1


class TestCursorsFailLoudly:
    def test_an_unreadable_cursor_is_an_error(self) -> None:
        """Treating it as zero would re-read page one while the caller advanced."""

        with pytest.raises(InvalidPolicyError) as raised:
            paginate(list(range(10)), cursor="page-two-please")

        assert "previous response" in str(raised.value)

    def test_a_negative_cursor_is_refused(self) -> None:
        with pytest.raises(InvalidPolicyError):
            paginate(list(range(10)), cursor="-1")

    def test_an_absent_cursor_starts_at_the_beginning(self) -> None:
        assert paginate(list(range(10)), limit=3, cursor=None)["results"] == [0, 1, 2]
        assert paginate(list(range(10)), limit=3, cursor="  ")["results"] == [0, 1, 2]

    def test_a_cursor_past_the_end_yields_an_empty_page(self) -> None:
        page = paginate(list(range(10)), limit=5, cursor="99")

        assert page["results"] == []
        assert page["total"] == 10, "total still describes the collection"


class TestReadToolsAreWrapped:
    def test_list_projects_paginates(self, context: tools.ToolContext) -> None:
        for index in range(5):
            context.memory.create_project(f"Project {index}", key=f"paged-{index}")

        first = dispatch(context, "kae_list_projects", {"limit": 2})

        assert first["total"] == 5
        assert len(first["results"]) == 2
        assert first["cursor"] == "2"

    def test_open_decisions_paginate(self, context: tools.ToolContext) -> None:
        project = context.memory.create_project("Decisions", key="paged-decisions")
        session = context.memory.open_session(project.id, SessionType.DISCOVERY)
        message = context.memory.record_message(
            project.id, session.id, "Several things are undecided."
        ).message
        run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, "paged-1", session.id)
        context.memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    KnowledgeKind.UNKNOWN.value, f"Open question {index}?", "seed", message.id
                )
                for index in range(6)
            ],
        )

        page = dispatch(
            context, "kae_get_open_decisions", {"project_id": str(project.id), "limit": 2}
        )

        assert page["total"] >= 6
        assert len(page["results"]) == 2
        assert page["cursor"] is not None
        assert all("source" in entry for entry in page["results"])

    def test_every_paginated_tool_declares_limit_and_cursor(self) -> None:
        """A wrapper a caller cannot page through is a wrapper in name only."""

        paginated = {"kae_list_projects", "kae_get_open_decisions", "kae_search_knowledge"}
        for definition in TOOL_DEFINITIONS:
            if definition["name"] not in paginated:
                continue
            properties = definition["inputSchema"]["properties"]
            assert "cursor" in properties, definition["name"]
            assert "limit" in properties, definition["name"]


class TestTheCountSplit:
    """ADR-0021 rule 5: one number could not say what it counted."""

    def test_search_reports_chunks_and_items_separately(self, context: tools.ToolContext) -> None:
        project = context.memory.create_project("Counting", key="paged-counting")

        payload = dispatch(
            context, "kae_search_knowledge", {"project_id": str(project.id), "query": "approval"}
        )

        assert "matched_chunks" in payload
        assert "matched_knowledge_items" in payload
        assert "count" not in payload, "the ambiguous name is gone, not aliased"

    def test_search_still_carries_the_wrapper(self, context: tools.ToolContext) -> None:
        project = context.memory.create_project("Wrapped", key="paged-wrapped")

        payload = dispatch(
            context, "kae_search_knowledge", {"project_id": str(project.id), "query": "approval"}
        )

        assert {"total", "page", "cursor", "results"} <= set(payload)


class TestDetailLevels:
    """Rule 15: the arithmetic behind a number is not the number."""

    def test_per_area_counts_are_withheld_below_diagnostic(
        self, factory: sessionmaker[Session]
    ) -> None:
        readiness = ReadinessService(factory)
        readiness.install_template()
        economy = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
            response_policy=response_policy.PROFILES[response_policy.ResponseProfile.ECONOMY],
        )
        project = economy.memory.create_project("Detail", key="paged-detail")

        payload = dispatch(economy, "kae_get_readiness", {"project_id": str(project.id)})

        for area in payload.get("areas", []):
            assert "confirmed" not in area
            assert "proposed" not in area
            assert "state" in area, "whether an area holds the project back always stays"

    def test_diagnostic_restores_them(self, context: tools.ToolContext) -> None:
        project = context.memory.create_project("Diagnostic", key="paged-diagnostic")

        payload = dispatch(
            context,
            "kae_get_readiness",
            {"project_id": str(project.id), "detail": "diagnostic"},
        )

        assert any("confirmed" in area for area in payload.get("areas", []))


class TestIntegrityProseSurvivesCompaction:
    def test_the_observation_note_shortens_rather_than_vanishing(self) -> None:
        """`note` is an integrity statement; `why` is explanatory and gates.

        Deciding which is which was ADR-0021 §Coordination item 4, so that this
        work could not accidentally gate a field that states what a response
        did *not* do.
        """

        long_form = (
            "Recorded verbatim as evidence. Nothing is confirmed by this call; a "
            "person confirms what becomes project knowledge."
        )

        assert long_form in response_policy.SHORT_FORMS
        assert "not confirmed" in response_policy.SHORT_FORMS[long_form]


def _statements(payload: dict[str, Any]) -> list[Any]:
    return list(payload["results"])
