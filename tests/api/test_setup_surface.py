"""The setup surface, over HTTP and MCP (N24-N28).

Two properties matter more than the payload shapes, and both are about what a
caller could conclude from a response:

**Setup readiness is never readable as knowledge readiness.** They are separate
routes returning separate objects, and neither carries a field that could be
mistaken for the other. A client that merged them would tell a person that a
well-understood project can publish.

**No credential appears, on either adapter.** Not because a response redacts
one, but because none is stored: a target carries provider configuration and a
connection carries a reference to where a credential lives.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.setup_service import SetupService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.publication_targets import Provider
from kae_memory.domain.setup_questions import SetupPurpose


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    ReadinessService(factory).install_template()
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project_id(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Sparse Inbox"}).json()["id"])


@pytest.fixture
def setup(factory: sessionmaker[Session]) -> SetupService:
    return SetupService(factory)


class TestSetupIsReportedApartFromKnowledge:
    def test_a_new_project_gets_a_setup_state(self, client: TestClient, project_id: str) -> None:
        response = client.get(f"/v1/projects/{project_id}/setup")

        assert response.status_code == 200
        assert response.json()["setup_state"] == "not_started"

    def test_it_carries_no_readiness_percentage(self, client: TestClient, project_id: str) -> None:
        """A client that found one here would use it, and would then be
        reporting knowledge completeness as configuration."""

        body = client.get(f"/v1/projects/{project_id}/setup").json()

        assert "readiness_percentage" not in body
        assert "percentage" not in body

    def test_readiness_carries_no_setup_state(self, client: TestClient, project_id: str) -> None:
        """The other direction, which matters as much."""

        body = client.get(f"/v1/projects/{project_id}/readiness").json()

        assert "setup_state" not in body

    def test_a_sparse_project_is_not_reported_as_blocked(
        self, client: TestClient, project_id: str
    ) -> None:
        """Zero confirmed knowledge, and setup blocks nothing that has been
        asked for."""

        body = client.get(f"/v1/projects/{project_id}/setup").json()

        assert body["setup_state"] != "needs_input"

    def test_every_gap_says_what_to_do(self, client: TestClient, project_id: str) -> None:
        body = client.get(f"/v1/projects/{project_id}/setup").json()

        assert all(gap["next_action"].strip() for gap in body["gaps"])

    def test_no_gap_blames_sparse_knowledge(self, client: TestClient, project_id: str) -> None:
        """The rejected readiness gate would reappear here first, and it would
        look reasonable: "not enough is known to publish"."""

        body = client.get(f"/v1/projects/{project_id}/setup").json()

        assert all("know" not in gap["reason"].lower() for gap in body["gaps"])


class TestTheQuestionQueuesStaySeparate:
    def test_setup_questions_have_their_own_route(
        self, client: TestClient, setup: SetupService, project_id: str
    ) -> None:
        setup.ask(
            ProjectId(project_id),
            SetupPurpose.PUBLICATION,
            "Where should deliverables go?",
            "default_publication_target",
        )

        body = client.get(f"/v1/projects/{project_id}/setup/questions").json()

        assert body["count"] == 1
        assert body["questions"][0]["field"] == "default_publication_target"

    def test_a_setup_question_never_appears_as_a_clarification(
        self, client: TestClient, setup: SetupService, project_id: str
    ) -> None:
        setup.ask(
            ProjectId(project_id),
            SetupPurpose.PUBLICATION,
            "Where should deliverables go?",
            "default_publication_target",
        )

        body = client.post(f"/v1/projects/{project_id}/clarifications").json()

        assert all("deliverables go" not in question["question"] for question in body["questions"])

    def test_answering_a_setup_question_creates_no_knowledge(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        setup: SetupService,
        project_id: str,
    ) -> None:
        asked = setup.ask(
            ProjectId(project_id),
            SetupPurpose.PUBLICATION,
            "Where should deliverables go?",
            "default_publication_target",
        )

        setup.answer(ProjectId(project_id), str(asked.id), "local files", actor="cris")

        assert (
            MemoryService(factory).retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()
        )

    def test_a_suggestion_arrives_with_its_evidence(
        self, client: TestClient, setup: SetupService, project_id: str
    ) -> None:
        setup.ask(
            ProjectId(project_id),
            SetupPurpose.ACQUISITION,
            "Which repository?",
            "primary_repository",
            suggested_answer="crismag/KAE-Studio",
            suggestion_evidence="the git remote in the working directory",
        )

        question = client.get(f"/v1/projects/{project_id}/setup/questions").json()["questions"][0]

        assert question["suggested_answer"]
        assert question["suggestion_evidence"]


class TestTargetsAreVisibleEvenWhenUnusable:
    def test_an_unauthorised_target_is_listed_with_a_reason(
        self, client: TestClient, setup: SetupService, project_id: str
    ) -> None:
        """Hiding it would take the decision with it, and a person would be
        asked to choose a destination they already chose."""

        connection = setup.record_connection(ProjectId(project_id), Provider.GITHUB)
        setup.register_target(
            ProjectId(project_id),
            Provider.GITHUB,
            "studio",
            connection_id=str(connection.id),
        )

        body = client.get(f"/v1/projects/{project_id}/publication-targets").json()

        assert body["total"] == 1
        assert body["results"][0]["available"] is False
        assert "authorised" in body["results"][0]["unavailable_reason"]

    def test_a_local_target_is_available_with_no_connection(
        self, client: TestClient, setup: SetupService, project_id: str
    ) -> None:
        setup.register_target(ProjectId(project_id), Provider.LOCAL, "local files")

        body = client.get(f"/v1/projects/{project_id}/publication-targets").json()

        assert body["results"][0]["available"] is True

    def test_no_credential_appears_anywhere_in_the_response(
        self, client: TestClient, setup: SetupService, project_id: str
    ) -> None:
        """None is stored, so none can leak. Asserted on the serialised body
        because that is the thing that actually travels."""

        connection = setup.record_connection(
            ProjectId(project_id),
            Provider.GITHUB,
            credential_reference="env:KAE_GITHUB_TOKEN",
        )
        setup.register_target(
            ProjectId(project_id),
            Provider.GITHUB,
            "studio",
            configuration={"repository": "crismag/KAE-Studio"},
            connection_id=str(connection.id),
        )

        text = client.get(f"/v1/projects/{project_id}/publication-targets").text

        assert "credential_reference" not in text
        assert "ghp_" not in text
        assert "token" not in text.lower()


class TestTheMcpAdapterSaysTheSameThings:
    def test_the_setup_tool_reports_the_same_state(
        self, factory: sessionmaker[Session], client: TestClient, project_id: str
    ) -> None:
        """Behavioural parity, not envelope parity (ADR-0023): neither adapter
        may be able to say something the other cannot."""

        from kae_memory.application.blueprint_service import BlueprintService
        from kae_memory.application.review_service import ReviewService
        from kae_memory.mcp import tools
        from kae_memory.mcp.server import dispatch

        context = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=ReadinessService(factory),
            review=ReviewService(factory),
            setup=SetupService(factory),
        )

        payload = dispatch(context, "kae_get_setup_state", {"project_id": project_id})
        body = client.get(f"/v1/projects/{project_id}/setup").json()

        assert payload["setup_state"] == body["setup_state"]
        assert payload["blocks_anything"] == body["blocks_anything"]

    def test_the_tool_says_setup_is_not_knowledge(self) -> None:
        """An agent reads this before deciding what an unavailable capability
        means."""

        from kae_memory.mcp.server import TOOL_DEFINITIONS

        declaration = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_get_setup_state")

        assert "knowledge" in declaration["description"].lower()
        assert "sparsity never appears" in declaration["description"]
