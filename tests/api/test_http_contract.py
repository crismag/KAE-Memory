"""The HTTP contract, over the real database.

TestClient drives the same application `python -m kae_memory.api` serves; only
the session factory differs.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """Return a client over an empty schema."""

    with TestClient(create_app(factory)) as test_client:
        yield test_client


def _project(client: TestClient, name: str = "Discovery") -> str:
    response = client.post("/v1/projects", json={"name": name})
    assert response.status_code == 201
    return str(response.json()["id"])


def test_health_reports_the_database_and_applied_revision(client: TestClient) -> None:
    """FR-017, and never a connection string — the URL contains the password."""

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert body["version"]
    assert "password" not in str(body).lower()


def test_health_is_unversioned(client: TestClient) -> None:
    """An operational probe should not move when the business contract does."""

    assert client.get("/health").status_code == 200
    assert client.get("/v1/health").status_code == 404


def test_a_project_round_trips(client: TestClient) -> None:
    project_id = _project(client, "Round trip")

    fetched = client.get(f"/v1/projects/{project_id}").json()
    listed = client.get("/v1/projects").json()

    assert fetched["name"] == "Round trip"
    assert [entry["id"] for entry in listed] == [project_id]


def test_an_unknown_project_is_404_with_a_machine_readable_code(client: TestClient) -> None:
    response = client.get("/v1/projects/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "project_not_found"


def test_listing_under_an_unknown_project_is_404_not_an_empty_list(client: TestClient) -> None:
    """An empty collection and a wrong identifier are different answers."""

    response = client.get("/v1/projects/11111111-1111-1111-1111-111111111111/knowledge")

    assert response.status_code == 404


def test_an_unknown_enum_value_returns_the_permitted_set(client: TestClient) -> None:
    """A client that guessed wrong should learn the answer from the response."""

    project_id = _project(client)

    response = client.post(f"/v1/projects/{project_id}/sessions", json={"session_type": "chat"})

    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "invalid_session_type"
    assert "discovery" in body["detail"]["permitted"]


def test_an_invalid_body_returns_the_validation_envelope(client: TestClient) -> None:
    response = client.post("/v1/projects", json={"name": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


def test_messages_are_recorded_verbatim_and_ordered(client: TestClient) -> None:
    project_id = _project(client)
    session_id = client.post(
        f"/v1/projects/{project_id}/sessions", json={"session_type": "discovery"}
    ).json()["id"]

    for text in ("  Leading space matters.  ", "Second."):
        assert (
            client.post(f"/v1/sessions/{session_id}/messages", json={"content": text}).status_code
            == 201
        )

    messages = client.get(f"/v1/sessions/{session_id}/messages").json()

    assert [entry["sequence_number"] for entry in messages] == [1, 2]
    assert messages[0]["content"] == "  Leading space matters.  "


def test_enqueueing_a_run_returns_202_and_does_not_start_it(client: TestClient) -> None:
    """The browser does not own the run (ADR-0009)."""

    project_id = _project(client)

    response = client.post(
        f"/v1/projects/{project_id}/runs",
        json={"role": "requirements", "idempotency_key": "extract-1"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "pending"


def test_a_replayed_enqueue_converges_on_one_run(client: TestClient) -> None:
    project_id = _project(client)
    body = {"role": "requirements", "idempotency_key": "extract-1"}

    first = client.post(f"/v1/projects/{project_id}/runs", json=body).json()
    second = client.post(f"/v1/projects/{project_id}/runs", json=body).json()

    assert first["id"] == second["id"]
    assert len(client.get(f"/v1/projects/{project_id}/runs").json()) == 1


def test_an_unknown_role_is_rejected_before_anything_is_written(client: TestClient) -> None:
    """FR-009 authorises exactly three roles."""

    project_id = _project(client)

    response = client.post(
        f"/v1/projects/{project_id}/runs",
        json={"role": "reviewer", "idempotency_key": "x"},
    )

    assert response.status_code == 422
    assert sorted(response.json()["error"]["detail"]["permitted"]) == [
        "architecture",
        "requirements",
        "review",
    ]
    assert client.get(f"/v1/projects/{project_id}/runs").json() == []


def test_readiness_reports_the_areas_not_only_a_number(client: TestClient) -> None:
    """A percentage a user cannot interrogate misrepresents project state."""

    project_id = _project(client)

    body = client.get(f"/v1/projects/{project_id}/readiness").json()

    assert body["percentage"] == 0
    assert body["status"] == "not_started"
    assert not body["implementation_eligible"]
    assert len(body["areas"]) == 10
    assert body["missing_mandatory_areas"]


def test_a_critical_blocker_blocks_and_resolving_it_unblocks(client: TestClient) -> None:
    project_id = _project(client)
    # Covered knowledge first. `blocked` claims coverage would otherwise permit
    # generation, so a project with nothing assigned to any area stays
    # `not_started` even with a blocker against it — reporting blocked there
    # would overstate progress. Note that knowledge alone is not enough: an
    # item contributes only once it is linked to an area.
    item_id = _write_two_items(client, project_id)[0]
    assert (
        client.post(
            f"/v1/projects/{project_id}/readiness/areas",
            json={"knowledge_item_id": item_id, "area_key": "functional_requirements"},
        ).status_code
        == 204
    )

    blocker = client.post(
        f"/v1/projects/{project_id}/blockers",
        json={"summary": "Licensing unresolved.", "severity": "critical"},
    )
    assert blocker.status_code == 201

    blocked = client.post(f"/v1/projects/{project_id}/readiness/calculate", json={}).json()
    assert blocked["status"] == "blocked"
    assert blocked["critical_blocker_count"] == 1

    resolved = client.post(
        f"/v1/projects/{project_id}/blockers/{blocker.json()['id']}/resolve",
        json={"note": "Cleared."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    after = client.post(f"/v1/projects/{project_id}/readiness/calculate", json={}).json()
    assert after["status"] != "blocked"


def test_readiness_history_is_append_only(client: TestClient) -> None:
    project_id = _project(client)

    client.post(f"/v1/projects/{project_id}/readiness/calculate", json={})
    client.post(f"/v1/projects/{project_id}/readiness/calculate", json={})

    history = client.get(f"/v1/projects/{project_id}/readiness/history").json()

    assert len(history) == 2


def test_assigning_an_unknown_area_is_rejected(client: TestClient) -> None:
    project_id = _project(client)

    response = client.post(
        f"/v1/projects/{project_id}/readiness/areas",
        json={"knowledge_item_id": "whatever", "area_key": "vibes"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"


def test_resolving_a_contradiction_twice_is_safe(client: TestClient) -> None:
    """A retried resolution must not fail; the edge is never deleted."""

    project_id = _project(client)
    run = client.post(
        f"/v1/projects/{project_id}/runs",
        json={"role": "requirements", "idempotency_key": "k"},
    ).json()
    assert run["status"] == "pending"

    first = _write_two_items(client, project_id)
    contradiction = client.post(
        f"/v1/projects/{project_id}/contradictions",
        json={
            "source_knowledge_item_id": first[0],
            "target_knowledge_item_id": first[1],
        },
    )
    assert contradiction.status_code == 201
    path = f"/v1/projects/{project_id}/contradictions/{contradiction.json()['id']}/resolve"

    assert client.post(path, json={}).json() == {"resolved": True}
    assert client.post(path, json={}).json() == {"resolved": False}


def test_confirming_twice_is_a_409_not_a_500(client: TestClient) -> None:
    """A state conflict the client could resolve by re-reading."""

    project_id = _project(client)
    item_id = _write_two_items(client, project_id)[0]

    assert client.post(f"/v1/knowledge/{item_id}/confirm").status_code == 200
    second = client.post(f"/v1/knowledge/{item_id}/confirm")

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "invalid_lifecycle_transition"


def test_knowledge_carries_its_full_version_history(client: TestClient) -> None:
    project_id = _project(client)
    item_id = _write_two_items(client, project_id)[0]

    item = next(
        entry
        for entry in client.get(f"/v1/projects/{project_id}/knowledge").json()
        if entry["id"] == item_id
    )

    assert item["versions"][0]["number"] == 1
    assert item["versions"][0]["source"]
    assert item["current_content"] == item["versions"][-1]["content"]


def test_the_openapi_document_is_generated(client: TestClient) -> None:
    """ADR-0009 requires a generated client, which requires a schema."""

    schema = client.get("/openapi.json").json()

    assert "/v1/projects" in schema["paths"]
    assert "/health" in schema["paths"]
    assert schema["info"]["version"]


def _write_two_items(client: TestClient, project_id: str) -> tuple[str, str]:
    """Write two knowledge items through the application layer.

    There is no HTTP endpoint for writing knowledge: knowledge is produced by
    agent runs, not posted by clients, and this slice does not execute runs.
    """

    from kae_memory.application import MemoryService, WriteKnowledgeRequest
    from kae_memory.domain.execution import AgentRole
    from kae_memory.domain.identifiers import ProjectId

    memory = MemoryService(client.app.state.session_factory)  # type: ignore[attr-defined]
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "seed")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind="requirement", content="First.", source="test"),
            WriteKnowledgeRequest(kind="requirement", content="Second.", source="test"),
        ],
    )
    return str(items[0].id), str(items[1].id)
