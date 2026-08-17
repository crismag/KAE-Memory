"""What a decision about a source would apply to, over HTTP (`D-170`).

A run records which source its text was read out of (`D-164`) and
`project_sources` records what somebody decided about that source (`D-168`).
Nothing joined them, so *what would a decision about this repository reach* had
no answer — and every reading of `ADR-0004` step 3 in `D-169` needs that answer
before it can do anything.

**The route reports and enforces nothing**, which is asserted here rather than
inferred from the absence of a deletion: material under a source classified
`ephemeral` is counted exactly like material under one classified `memory`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy

REPOSITORY = {
    "kind": "github",
    "location": "kae/ministry-reporting",
    "state": "configured",
}
TEXT = "Ministries file monthly reports for their programmes. " * 20


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Retention scope"}).json()["id"])


def register(client: TestClient, project: str) -> dict[str, Any]:
    response = client.post("/v1/projects/" + project + "/sources", json=REPOSITORY)
    assert response.status_code == 201, response.text
    registered: dict[str, Any] = response.json()
    return registered


def ingest(client: TestClient, project: str, document: str, **extra: object) -> dict[str, Any]:
    response = client.post(
        "/v1/projects/" + project + "/documents",
        json={"document": document, "text": TEXT, **extra},
    )
    assert response.status_code == 202, response.text
    ingested: dict[str, Any] = response.json()
    return ingested


def classify(client: TestClient, project: str, source_id: str, disposition: str) -> None:
    response = client.post(
        "/v1/projects/" + project + "/sources/" + source_id + "/disposition",
        json={"disposition": disposition},
    )
    assert response.status_code == 200, response.text


def material(client: TestClient, project: str) -> dict[str, Any]:
    response = client.get("/v1/projects/" + project + "/source-material")
    assert response.status_code == 200, response.text
    report: dict[str, Any] = response.json()
    return report


class TestItSaysWhatStandsBehindEachSource:
    def test_the_disposition_and_the_material_arrive_together(
        self, client: TestClient, project: str
    ) -> None:
        """The whole point of the read: one answer instead of two lookups."""

        source = register(client, project)
        classify(client, project, source["source_id"], "ephemeral")
        ingested = ingest(
            client,
            project,
            "kae/ministry-reporting@abc1234:README.md",
            source_id=source["source_id"],
            source_type="repository",
        )

        entry = material(client, project)["sources"][0]

        assert entry["source_id"] == source["source_id"]
        assert entry["location"] == "kae/ministry-reporting"
        assert entry["disposition"] == "ephemeral"
        assert entry["documents"] == 1
        assert entry["stored_bodies"] == ingested["chunks_recorded"]

    def test_a_source_nobody_ingested_is_listed_at_zero(
        self, client: TestClient, project: str
    ) -> None:
        register(client, project)

        entry = material(client, project)["sources"][0]

        assert entry["documents"] == 0
        assert entry["stored_bodies"] == 0

    def test_a_project_nobody_created_is_not_found(self, client: TestClient) -> None:
        missing = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/source-material")

        assert missing.status_code == 404


class TestItEnforcesNothing:
    def test_material_under_an_ephemeral_source_is_still_there(
        self, client: TestClient, project: str
    ) -> None:
        """`D-169` is the owner's ruling, so nothing here discards a body.

        A route that reported an `ephemeral` source as holding nothing would be
        the rule appearing to be in force while no code applies it.
        """

        source = register(client, project)
        ingested = ingest(
            client,
            project,
            "kae/ministry-reporting@abc1234:src/api.py",
            source_id=source["source_id"],
            source_type="repository",
        )
        classify(client, project, source["source_id"], "ephemeral")

        entry = material(client, project)["sources"][0]

        assert entry["stored_bodies"] == ingested["chunks_recorded"]
        assert entry["stored_bodies"] > 0


class TestMaterialNoDecisionCanReach:
    def test_a_pasted_document_is_reported_apart_from_every_source(
        self, client: TestClient, project: str
    ) -> None:
        """Its own number, not a share of a total and not silently dropped."""

        register(client, project)
        pasted = ingest(client, project, "spec.md")

        report = material(client, project)

        assert report["sources"][0]["stored_bodies"] == 0
        assert report["unattributed_documents"] == 1
        assert report["unattributed_bodies"] == pasted["chunks_recorded"]
