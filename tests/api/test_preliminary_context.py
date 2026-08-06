"""Preliminary context over HTTP (N44).

Parity here is **behavioural, not envelope** (ADR-0023): the two adapters need
not return the same shape, but neither may be able to say something the other
cannot. The property that matters is the one this target exists for — known,
proposed, assumed and unknown arrive as four separate things — and an adapter
that merged them would be the failure regardless of which one it was.

A GET, because composing decides nothing. That is what makes it safe at any
readiness rather than something to withhold until a project looks ready.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.assumptions import AssumptionOrigin, Consequence
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind

CANDIDATE = "Captured thoughts are stored as markdown files."


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    ReadinessService(factory).install_template()
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project_id(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Sparse Inbox"}).json()["id"])


def _propose(factory: sessionmaker[Session], project_id: str) -> str:
    """A candidate: area-assigned so it assembles, and left unconfirmed."""

    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "n44-http")
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, CANDIDATE, "seed")]
    )
    ReadinessService(factory).assign_area(
        ProjectId(project_id), written[0].id, "constraints_and_assumptions"
    )
    return str(written[0].id)


class TestItAnswersAtAnyReadiness:
    def test_an_empty_project_gets_a_context_rather_than_an_error(
        self, client: TestClient, project_id: str
    ) -> None:
        """The gate this system does not have. Nothing to say is an answer;
        declining to speak because knowledge looks thin is not."""

        response = client.get(f"/v1/projects/{project_id}/preliminary-context")

        assert response.status_code == 200
        assert response.json()["readiness_percentage"] == 0

    def test_an_unknown_project_is_still_a_404(self, client: TestClient) -> None:
        """Never refusing over readiness is not never refusing. A project that
        does not exist is a different claim from one that knows nothing."""

        response = client.get(
            "/v1/projects/2b1f2c1e-0000-4000-8000-000000000000/preliminary-context"
        )

        assert response.status_code == 404

    def test_an_unknown_purpose_is_refused(self, client: TestClient, project_id: str) -> None:
        response = client.get(
            f"/v1/projects/{project_id}/preliminary-context", params={"purpose": "vibes"}
        )

        assert response.status_code == 422


class TestTheBoundariesSurviveTheAdapter:
    def test_a_candidate_arrives_as_proposed_and_not_as_known(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _propose(factory, project_id)

        body = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        assert [s["text"] for s in body["proposed"]] == [CANDIDATE]
        assert body["known"] == []
        assert all(s["inclusion_class"] != "confirmed" for s in body["proposed"])

    def test_an_assumption_arrives_with_its_consequence(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        AssumptionService(factory).record(
            ProjectId(project_id),
            subject="storage",
            assumed_value="markdown files on local disk",
            reason="a prototype needs no database",
            origin=AssumptionOrigin.KAE_INFERRED,
            consequence=Consequence.REWORK,
        )

        body = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        assert len(body["assumed"]) == 1
        assert Consequence.REWORK.value in body["assumed"][0]["disclosure"]

    def test_an_assumption_is_not_also_a_statement(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A guess that reaches the statement list will be read as a
        requirement, and no label further down repairs that."""

        AssumptionService(factory).record(
            ProjectId(project_id),
            subject="storage",
            assumed_value="markdown files on local disk",
            reason="a prototype needs no database",
            origin=AssumptionOrigin.KAE_INFERRED,
        )

        body = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        rendered = {s["text"] for s in body["known"] + body["proposed"]}
        assert "markdown files on local disk" not in rendered

    def test_unknowns_arrive_split(self, client: TestClient, project_id: str) -> None:
        body = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        assert "material_unknowns" in body
        assert "deferrable_unknowns" in body


class TestReadingDecidesNothing:
    def test_nothing_is_confirmed_by_composing(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _propose(factory, project_id)

        client.get(f"/v1/projects/{project_id}/preliminary-context")

        body = client.get(f"/v1/projects/{project_id}/preliminary-context").json()
        assert body["known"] == []
        assert body["knowledge_changed"] is False

    def test_the_revision_does_not_move(self, client: TestClient, project_id: str) -> None:
        first = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        second = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        assert second["knowledge_revision"] == first["knowledge_revision"]

    def test_it_is_pinned_to_what_it_read(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Identifiers alone go stale the moment a statement is corrected, so a
        deliverable built from them would look reproducible while producing
        different content (N20.1)."""

        knowledge_id = _propose(factory, project_id)

        body = client.get(f"/v1/projects/{project_id}/preliminary-context").json()

        pins = {pin["knowledge_id"]: pin["version"] for pin in body["statement_pins"]}
        assert pins[knowledge_id] >= 1
