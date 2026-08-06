"""Assumptions reachable from an adapter (N45).

N35 built the model — provenance, materiality, reversibility, revisit trigger,
who accepted — and no adapter exposed any of it. Manual testing hit the
consequence twice, most sharply when a user answered a clarification with *"I
don't know yet. Recommend something reasonable for a prototype, but don't make
it a permanent project decision."* KAE had nowhere to put that: answering the
question would have closed it, and the record designed for exactly this case was
unreachable.

What these tests hold is that reaching it did not weaken it:

    an assumption is recorded proposed, whoever asked;
    accepting names a person and is not confirming;
    nothing here creates knowledge or moves readiness.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        assumptions=AssumptionService(factory),
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Sparse", key="n45-sparse").id)


def _record(context: tools.ToolContext, project_id: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": project_id,
        "subject": "tenancy",
        "assumed_value": "single user",
        "reason": "nothing in the idea mentions sharing",
    }
    body.update(extra)
    return dispatch(context, "kae_record_assumption", body)


class TestTheAnswerThatHadNowhereToGo:
    def test_a_recommendation_can_be_recorded_without_being_decided(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """ "I don't know yet, recommend something" now has a home."""

        payload = _record(
            context,
            project_id,
            consequence="architectural",
            revisit="before_production",
        )

        assert payload["state"] == "proposed"
        assert payload["accepted_by"] is None
        assert payload["material"] is True

    def test_recording_creates_no_knowledge(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _record(context, project_id)

        assert context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()

    def test_recording_does_not_move_readiness(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        before = context.readiness.knowledge_revision(ProjectId(project_id))

        _record(context, project_id)

        assert context.readiness.knowledge_revision(ProjectId(project_id)) == before


class TestAcceptanceIsNotConfirmation:
    def test_accepting_names_a_person(self, context: tools.ToolContext, project_id: str) -> None:
        recorded = _record(context, project_id)

        accepted = dispatch(
            context,
            "kae_accept_assumption",
            {
                "project_id": project_id,
                "assumption_id": recorded["assumption_id"],
                "actor": "cris",
            },
        )

        assert accepted["state"] == "accepted"
        assert accepted["accepted_by"] == "cris"

    def test_an_anonymous_acceptance_is_refused(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Responsibility nobody is named for is none."""

        recorded = _record(context, project_id)

        refused = dispatch(
            context,
            "kae_accept_assumption",
            {
                "project_id": project_id,
                "assumption_id": recorded["assumption_id"],
                "actor": "  ",
            },
        )

        assert refused["error"] == "invalid_argument"

    def test_accepting_still_creates_no_knowledge(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The promotion FR-005 forbids, checked across the adapter seam."""

        recorded = _record(context, project_id)
        dispatch(
            context,
            "kae_accept_assumption",
            {
                "project_id": project_id,
                "assumption_id": recorded["assumption_id"],
                "actor": "cris",
            },
        )

        assert context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()

    def test_the_response_says_accepted_is_not_confirmed(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        recorded = _record(context, project_id)

        accepted = dispatch(
            context,
            "kae_accept_assumption",
            {
                "project_id": project_id,
                "assumption_id": recorded["assumption_id"],
                "actor": "cris",
            },
        )

        assert "not confirmed" in accepted["note"]
        assert accepted["knowledge_changed"] is False


class TestListing:
    def test_active_assumptions_are_listed_with_their_materiality(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _record(context, project_id, consequence="architectural")
        _record(context, project_id, subject="storage", consequence="cosmetic")

        page = dispatch(context, "kae_list_assumptions", {"project_id": project_id})

        assert page["total"] == 2
        assert page["material_count"] == 1

    def test_a_material_assumption_cannot_be_never_revisited(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """How a prototype default becomes a production commitment."""

        refused = _record(context, project_id, consequence="unsafe", revisit="never")

        assert refused["error"] == "invalid_argument"

    def test_an_unknown_project_is_reported(self, context: tools.ToolContext) -> None:
        payload = _record(context, "00000000-0000-0000-0000-000000000000")

        assert payload["error"] == "project_not_found"

    def test_the_capability_gap_is_reported_when_unwired(
        self, factory: sessionmaker[Session]
    ) -> None:
        readiness = ReadinessService(factory)
        readiness.install_template()
        bare = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
        )
        project = bare.memory.create_project("Bare", key="n45-bare")

        payload = dispatch(bare, "kae_list_assumptions", {"project_id": str(project.id)})

        assert payload["error"] == "capability_unavailable"
