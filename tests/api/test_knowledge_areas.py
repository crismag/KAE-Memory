"""What each statement is about, not only what it says.

Memory has always held a statement's discovery areas and the knowledge listing
did not return them. So a consumer could see *what* a project knows and not
*what any of it is about*.

The visible cost was a Definition page reporting the problem statement as
uncomputable for every project in existence: "the problem" is the statements
linked to `problem_and_value`, and nothing else identifies them.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


def test_a_statement_says_what_it_is_about(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """Memory held the areas; the listing did not return them.

    So a consumer could see what a project knows and not what any of it was
    about — which left Studio reporting the problem statement as uncomputable
    for every project in existence, because "the problem" is the statements
    linked to `problem_and_value` and nothing else identifies them.
    """

    readiness = ReadinessService(factory)
    readiness.install_template()
    memory = MemoryService(factory)
    project = client.post("/v1/projects", json={"name": "Areas"}).json()
    run = memory.start_run(ProjectId(project["id"]), AgentRole.REQUIREMENTS, "seed-areas")
    written = memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="goal", content="People lose track of tasks.", source="s")],
    )
    readiness.assign_area(ProjectId(project["id"]), written[0].id, "problem_and_value")

    listed = client.get(f"/v1/projects/{project['id']}/knowledge").json()

    assert listed[0]["areas"] == ["problem_and_value"]


def test_an_unclassified_statement_belongs_to_no_area(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """Empty, not absent.

    Before review runs a statement genuinely belongs nowhere, and that is a
    fact about the project rather than a missing field.
    """

    memory = MemoryService(factory)
    project = client.post("/v1/projects", json={"name": "Unclassified"}).json()
    run = memory.start_run(ProjectId(project["id"]), AgentRole.REQUIREMENTS, "seed-unclassified")
    memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="goal", content="Something.", source="s")]
    )

    listed = client.get(f"/v1/projects/{project['id']}/knowledge").json()

    assert listed[0]["areas"] == []


class TestAssumptionOrigin:
    """Where an assumption came from, and the one origin a caller may not claim.

    `AssumptionService.record` has always taken an origin and the HTTP schema
    did not expose it, so `kae_recommended_accepted` and
    `unresolved_alternative` could not be written over HTTP at all — the two
    origins that exist precisely to record what a person did with KAE's advice.
    Built and unused, for the same structural reason as the other four.
    """

    def test_an_accepted_recommendation_is_recorded_as_one(self, client: TestClient) -> None:
        """Accepting advice is not the same as having said it.

        `kae_recommended_accepted` is the difference between "KAE suggested
        this and I agreed" and "I said this", and a Definition page that could
        not tell them apart would present KAE's view as the customer's.
        """

        project = client.post("/v1/projects", json={"name": "Advice"}).json()

        response = client.post(
            f"/v1/projects/{project['id']}/assumptions",
            json={
                "origin": "kae_recommended_accepted",
                "subject": "scope_and_boundaries",
                "assumed_value": "Mobile is deferred to a second release",
                "reason": "KAE recommended it and the operator accepted",
                "consequence": "architectural",
                "revisit": "before_build",
            },
        )

        assert response.status_code == 201
        assert response.json()["origin"] == "kae_recommended_accepted"

    def test_an_option_nobody_chose_can_be_kept_open(self, client: TestClient) -> None:
        """ "Keep open" is an outcome, not a refusal to answer."""

        project = client.post("/v1/projects", json={"name": "Open"}).json()

        response = client.post(
            f"/v1/projects/{project['id']}/assumptions",
            json={
                "origin": "unresolved_alternative",
                "subject": "scope_and_boundaries",
                "assumed_value": "Mobile in the first release, or the second",
                "reason": "the operator wanted both options kept",
                "consequence": "architectural",
                "revisit": "before_build",
            },
        )

        assert response.status_code == 201
        assert response.json()["origin"] == "unresolved_alternative"

    def test_a_caller_cannot_claim_a_person_said_something(self, client: TestClient) -> None:
        """The one origin this route refuses.

        Everything reaching it is KAE's. A caller that could write
        `user_stated` would be manufacturing the single distinction the origin
        exists to make — directive principle 8, arriving through the door
        marked "assumption".
        """

        project = client.post("/v1/projects", json={"name": "Claimed"}).json()

        response = client.post(
            f"/v1/projects/{project['id']}/assumptions",
            json={
                "origin": "user_stated",
                "subject": "scope",
                "assumed_value": "The customer definitely said this",
                "reason": "-",
            },
        )

        assert response.status_code == 422
        assert "user_stated" in response.json()["error"]["message"]
