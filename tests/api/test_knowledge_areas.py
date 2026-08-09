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
