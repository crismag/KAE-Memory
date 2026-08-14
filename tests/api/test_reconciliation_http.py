"""Deterministic reconciliation is reachable over HTTP without minting a model."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


def _seed_support_pair(
    factory: sessionmaker[Session], project_id: str
) -> tuple[KnowledgeItem, KnowledgeItem]:
    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "extract-support")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="goal",
                content="Retain original source notes for every project.",
                source="interview",
            ),
            WriteKnowledgeRequest(
                kind="goal",
                content="Retain original source notes for every project after decode.",
                source="interview",
            ),
        ],
    )
    return items[0], items[1]


class TestReconciliationRun:
    def test_run_is_idempotent_and_leaves_the_model_empty(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Reconcile"}).json()["id"])
        _seed_support_pair(factory, project)

        first = client.post(
            f"/v1/projects/{project}/reconciliation/runs",
            json={"idempotency_key": "full"},
        )
        second = client.post(
            f"/v1/projects/{project}/reconciliation/runs",
            json={"idempotency_key": "full"},
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["replayed"] is False
        assert second.json()["replayed"] is True
        assert second.json()["event"]["id"] == first.json()["event"]["id"]
        assert second.json()["edges_written"] == 0
        assert client.get(f"/v1/projects/{project}/model").json() == []
        assert client.get(f"/v1/projects/{project}/attention").json() == []

    def test_neighborhood_returns_related_evidence(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Neighbourhood"}).json()["id"])
        first, _second = _seed_support_pair(factory, project)
        client.post(
            f"/v1/projects/{project}/reconciliation/runs",
            json={"idempotency_key": "full"},
        )

        response = client.get(f"/v1/projects/{project}/reconciliation/neighborhoods/{first.id}")
        assert response.status_code == 200, response.text
        neighbors = response.json()["neighbors"]
        assert neighbors
        assert neighbors[0]["knowledge_item_id"] != str(first.id)
