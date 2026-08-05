"""How an unavailable capability reports itself.

The gap must stay a gap. What changes here is that it now names its subject and
the path forward, because "unavailable" alone leaves a caller unable to tell an
unregistered module from an unsupported feature — and those have different
remedies.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.mcp import tools
from kae_memory.mcp.errors import CapabilityUnavailableError
from kae_memory.mcp.server import dispatch

APPROVAL_KNOWLEDGE = [
    ("requirement", "Only an authorised approver may approve a report."),
    ("rule", "A submitter cannot approve their own report."),
    ("actor", "Ministry leaders submit monthly reports."),
    ("constraint", "Identity must come from the existing organisational directory."),
]


@pytest.fixture
def gap_context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
    )


@pytest.fixture
def seeded_project(gap_context: tools.ToolContext) -> str:
    memory = gap_context.memory
    project = memory.create_project("Ministry Reporting", key="gap-ministry")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "gap-seed")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in APPROVAL_KNOWLEDGE
        ],
    )
    for item in items:
        memory.confirm_knowledge(item.id)
    assert gap_context.retrieval is not None
    for item in items:
        gap_context.retrieval.chunk_knowledge(item, project.name)
    gap_context.retrieval.embed_pending(project.id)
    return str(project.id)


@pytest.fixture
def gap(gap_context: tools.ToolContext, seeded_project: str) -> dict[str, Any]:
    return dispatch(
        gap_context,
        "kae_get_module_context",
        {"project_id": seeded_project, "module": "approval workflow"},
    )


class TestTheGapStaysAGap:
    def test_it_is_still_an_error(self, gap: dict[str, Any]) -> None:
        """Adding a path forward must not soften the verdict."""

        assert gap["error"] == "capability_unavailable"
        assert "not available" in gap["message"]

    def test_the_original_contract_is_intact(self, gap: dict[str, Any]) -> None:
        """A consumer reading only the old fields must still be correct.

        The *reason* changed with N17-N19: modules are modelled now, so what is
        missing is registration rather than the capability. The shape did not
        change, which is what a consumer depends on.
        """

        assert "no modules are registered in this project" in gap["missing_capabilities"]
        assert gap["use_instead"]
        assert "Do not" in gap["guidance"]

    def test_it_still_raises_for_callers_not_using_dispatch(
        self, gap_context: tools.ToolContext, seeded_project: str
    ) -> None:
        with pytest.raises(CapabilityUnavailableError):
            tools.kae_get_module_context(gap_context, seeded_project, "approval workflow")

    def test_an_empty_module_name_is_still_rejected(
        self, gap_context: tools.ToolContext, seeded_project: str
    ) -> None:
        payload = dispatch(
            gap_context, "kae_get_module_context", {"project_id": seeded_project, "module": "  "}
        )

        assert payload["error"] == "invalid_argument"


class TestTheSubject:
    def test_the_requested_module_is_named_back(self, gap: dict[str, Any]) -> None:
        assert gap["subject"]["module"] == "approval workflow"
        assert gap["subject"]["project"] == "Ministry Reporting"

    def test_not_registered_is_distinguished_from_unsupported(self, gap: dict[str, Any]) -> None:
        """Two different problems with two different remedies.

        A caller must not read this as "you typed the wrong module name".
        """

        assert gap["subject"]["status"] == "not_registered"
        assert "nothing to look up until one is registered" in gap["subject"]["detail"]

    def test_next_steps_name_the_way_out(self, gap: dict[str, Any]) -> None:
        """Registering a module used to be impossible; now it is the first step.

        The old wording said this was "a product change, not a configuration
        one", which was true and is no longer. A next step that still said so
        would send a caller to wait for work that has shipped.
        """

        steps = " ".join(gap["next_steps"])
        assert "Register the module" in steps


class TestWhatIsOfferedInstead:
    def test_matching_project_knowledge_is_offered(self, gap: dict[str, Any]) -> None:
        offer = gap["available_now"]

        assert offer["available"] is True
        assert offer["count"] >= 1
        texts = [s["text"] for s in offer["statements"]]
        assert "Only an authorised approver may approve a report." in texts

    def test_the_offer_is_scoped_and_captioned_as_a_term_match(self, gap: dict[str, Any]) -> None:
        """The load-bearing guard.

        Handing back statements that merely contain "approval" under a heading
        about the approval module is exactly how a term match gets mistaken for
        module membership.
        """

        offer = gap["available_now"]

        assert offer["scope"] == "project"
        assert offer["match_type"] == "name_terms"
        assert "not module membership" in offer["caveat"]

    def test_unrelated_knowledge_is_not_swept_in(self, gap: dict[str, Any]) -> None:
        """An offer padded with everything is worse than no offer."""

        texts = [s["text"] for s in gap["available_now"]["statements"]]

        assert "Ministry leaders submit monthly reports." not in texts
        assert "Identity must come from the existing organisational directory." not in texts

    def test_every_offered_statement_stays_traceable(self, gap: dict[str, Any]) -> None:
        statements = gap["available_now"]["statements"]

        assert statements
        assert all(s["knowledge_id"] for s in statements)
        assert all(s["matched_terms"] for s in statements)

    def test_the_offer_reports_itself_unavailable_without_retrieval(
        self, factory: sessionmaker[Session], seeded_project: str
    ) -> None:
        """No retrieval service means no offer — and it says so rather than lying."""

        readiness = ReadinessService(factory)
        bare = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
        )

        payload = dispatch(
            bare,
            "kae_get_module_context",
            {"project_id": seeded_project, "module": "approval workflow"},
        )

        assert payload["available_now"]["available"] is False
        assert payload["available_now"]["statements"] == []
        assert payload["error"] == "capability_unavailable"
