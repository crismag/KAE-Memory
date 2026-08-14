"""The synthesized model and attention queue are HTTP-reachable, apart from extracted knowledge."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Layered knowledge"}).json()["id"])


class TestTheModelStartsEmpty:
    def test_a_new_project_has_no_synthesized_objects(
        self, client: TestClient, project: str
    ) -> None:
        response = client.get(f"/v1/projects/{project}/model")

        assert response.status_code == 200
        assert response.json() == []

    def test_a_new_project_has_no_attention_items(self, client: TestClient, project: str) -> None:
        response = client.get(f"/v1/projects/{project}/attention")

        assert response.status_code == 200
        assert response.json() == []


class TestWorkingModelThenHumanCorrection:
    def test_correction_is_authoritative_and_blocks_overwrite(
        self, client: TestClient, project: str
    ) -> None:
        created = client.post(
            f"/v1/projects/{project}/model",
            json={
                "domain": "goal",
                "identity_key": "identity",
                "title": "What we are building",
                "statement": "A working guess.",
            },
        )
        assert created.status_code == 201, created.text
        object_id = created.json()["id"]

        corrected = client.post(
            f"/v1/projects/{project}/model/{object_id}/correct",
            json={"title": "What we are building", "statement": "KAE, a planning product."},
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["authority"] == "human"
        assert corrected.json()["lifecycle"] == "authoritative"

        refused = client.post(
            f"/v1/projects/{project}/model",
            json={
                "domain": "goal",
                "identity_key": "identity",
                "title": "What we are building",
                "statement": "A later AI guess.",
            },
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "authoritative_override_refused"


class TestChangeEventsReplay:
    def test_the_same_key_returns_the_same_event(self, client: TestClient, project: str) -> None:
        body = {
            "idempotency_key": "cycle-1",
            "trigger": "reconciliation",
            "summary": "clustered six goals",
        }
        first = client.post(f"/v1/projects/{project}/reconciliation/events", json=body)
        second = client.post(f"/v1/projects/{project}/reconciliation/events", json=body)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["id"] == second.json()["id"]
        listed = client.get(f"/v1/projects/{project}/reconciliation/events")
        assert listed.status_code == 200
        assert len(listed.json()) == 1
