"""Which documents a source taught KAE, over HTTP (`D-259`).

`/source-material` says a repository produced 412 documents. It cannot say which
412, and *did the include paths catch what I meant* is the question a scope or
retention decision actually turns on. The coordinate was already on every
ingestion run (`D-164`) and no route served it.

**Documents, not the statements they produced.** The response names files and
counts bodies; following a document to its knowledge is another join and another
route, and the boundary is asserted here rather than left to a docstring.
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
    return str(client.post("/v1/projects", json={"name": "What was read"}).json()["id"])


@pytest.fixture
def source(client: TestClient, project: str) -> str:
    response = client.post("/v1/projects/" + project + "/sources", json=REPOSITORY)
    assert response.status_code == 201, response.text
    return str(response.json()["source_id"])


def ingest(client: TestClient, project: str, document: str, **extra: object) -> dict[str, Any]:
    response = client.post(
        "/v1/projects/" + project + "/documents",
        json={"document": document, "text": TEXT, **extra},
    )
    assert response.status_code == 202, response.text
    ingested: dict[str, Any] = response.json()
    return ingested


def documents(client: TestClient, project: str, source: str, **params: Any) -> dict[str, Any]:
    response = client.get(
        "/v1/projects/" + project + "/sources/" + source + "/documents", params=params
    )
    assert response.status_code == 200, response.text
    listing: dict[str, Any] = response.json()
    return listing


class TestTheRouteNamesWhatWasRead:
    def test_each_document_arrives_with_its_coordinate_bodies_and_last_read(
        self, client: TestClient, project: str, source: str
    ) -> None:
        ingested = ingest(
            client,
            project,
            "kae/ministry-reporting@abc1234:README.md",
            source_id=source,
            source_type="repository",
        )

        listing = documents(client, project, source)

        assert listing["source_id"] == source
        assert listing["total_documents"] == 1
        assert listing["truncated"] is False
        entry = listing["documents"][0]
        assert entry["document"] == "kae/ministry-reporting@abc1234:README.md"
        assert entry["stored_bodies"] == ingested["chunks_recorded"]
        assert entry["last_read_at"] is not None

    def test_a_source_nobody_ingested_names_nothing(
        self, client: TestClient, project: str, source: str
    ) -> None:
        listing = documents(client, project, source)

        assert listing["documents"] == []
        assert listing["total_documents"] == 0

    def test_a_pasted_document_belongs_to_no_source_and_is_not_listed(
        self, client: TestClient, project: str, source: str
    ) -> None:
        ingest(client, project, "pasted-spec.md")

        assert documents(client, project, source)["documents"] == []

    def test_a_source_nobody_registered_is_not_found(
        self, client: TestClient, project: str
    ) -> None:
        missing = client.get(
            "/v1/projects/" + project + "/sources/00000000-0000-0000-0000-000000000000/documents"
        )

        assert missing.status_code == 404


class TestATruncatedListingSaysSo:
    def test_the_total_is_served_beside_a_short_list(
        self, client: TestClient, project: str, source: str
    ) -> None:
        """The guard: a prefix must not be able to pass for the whole set.

        Without `total_documents` and `truncated` a page would read the length
        of what it received as the number of files read, which is `AUD-009` —
        a surface stating something the system did not do.
        """

        for index in range(4):
            ingest(
                client,
                project,
                f"kae/ministry-reporting@abc1234:file{index}.md",
                source_id=source,
                source_type="repository",
            )

        listing = documents(client, project, source, limit=2)

        assert len(listing["documents"]) == 2
        assert listing["total_documents"] == 4
        assert listing["truncated"] is True

    def test_a_limit_past_the_cap_is_refused(
        self, client: TestClient, project: str, source: str
    ) -> None:
        """Refused, not quietly shrunk, so `truncated` keeps one meaning."""

        base = "/v1/projects/" + project + "/sources/" + source + "/documents"

        assert client.get(base, params={"limit": 100000}).status_code == 422
        assert client.get(base, params={"limit": 0}).status_code == 422


class TestStoppingASourceDoesNotHideWhatItTaught:
    def test_a_retired_source_still_names_its_documents(
        self, client: TestClient, project: str, source: str
    ) -> None:
        """`D-230`: stopping is not deleting, so the list stays reachable."""

        ingest(
            client,
            project,
            "kae/ministry-reporting@abc1234:README.md",
            source_id=source,
            source_type="repository",
        )
        stopped = client.post("/v1/projects/" + project + "/sources/" + source + "/retirement")
        assert stopped.status_code == 200, stopped.text

        listing = documents(client, project, source)

        assert [entry["document"] for entry in listing["documents"]] == [
            "kae/ministry-reporting@abc1234:README.md"
        ]
