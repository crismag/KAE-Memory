"""Removing a source stops KAE reading it and erases nothing (`SRC-ACT`, `D-254`).

The owner's ruling, asked and answered: *"Does removing a source remove its
knowledge — No."* (`D-230`).

Three designs satisfy that sentence and only one survives reading the code, so
these tests hold the reasoning rather than the wording. A `DELETE` of the row
would in fact leave the knowledge — nothing cascades from `project_sources` to
`knowledge_items` or `messages` — and would still be wrong, because `D-164`
carries `source_id` on every ingestion run and `material` (`D-170`) groups
documents by it. The knowledge would outlive the deletion and the answer to
*where did this come from* would not.

So retirement is a nullable timestamp, orthogonal to `state`, and reversible.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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
    return str(client.post("/v1/projects", json={"name": "Retiring sources"}).json()["id"])


REPOSITORY = {
    "kind": "github",
    "location": "kae/ministry-reporting",
    "state": "configured",
    "scope": {"include": ["src/"], "exclude": [], "documentation_only": False},
}


def register(client: TestClient, project: str, **overrides: object) -> dict[str, Any]:
    response = client.post(f"/v1/projects/{project}/sources", json={**REPOSITORY, **overrides})
    assert response.status_code == 201, response.text
    registered: dict[str, Any] = response.json()
    return registered


def retire(client: TestClient, project: str, source_id: str) -> dict[str, Any]:
    response = client.post(f"/v1/projects/{project}/sources/{source_id}/retirement")
    assert response.status_code == 200, response.text
    retired: dict[str, Any] = response.json()
    return retired


class TestWhatRetirementDoes:
    def test_a_new_source_is_not_retired(self, client: TestClient, project: str) -> None:
        # `null` is the answer, not a flag defaulted to false somewhere else.
        assert register(client, project)["retired_at"] is None

    def test_retiring_records_when(self, client: TestClient, project: str) -> None:
        # A timestamp rather than a boolean, because *when* is the question
        # anybody asks second and a boolean cannot be made to answer it later.
        source = register(client, project)

        assert retire(client, project, source["source_id"])["retired_at"] is not None

    def test_the_source_is_still_there_to_read(self, client: TestClient, project: str) -> None:
        """The whole ruling, as the assertion a `DELETE` route could not pass."""
        source = register(client, project)
        retire(client, project, source["source_id"])

        listed = client.get(f"/v1/projects/{project}/sources").json()

        assert [entry["source_id"] for entry in listed] == [source["source_id"]]

    def test_retiring_does_not_unpin(self, client: TestClient, project: str) -> None:
        # Retirement is orthogonal to the progression, which is why it is not a
        # fifth `state`. Stopping reading a pinned repository never unpinned it,
        # and *what was this fixed to* stays answerable afterwards.
        source = register(client, project)
        client.post(
            f"/v1/projects/{project}/sources/{source['source_id']}/pin",
            json={"revision": "a" * 40, "digest": "sha256:beef", "state": "pinned"},
        )

        retired = retire(client, project, source["source_id"])

        assert retired["pinned_revision"] == "a" * 40
        assert retired["pinned"] is True
        assert retired["state"] == "pinned"


class TestItIsReversible:
    def test_restoring_clears_the_timestamp(self, client: TestClient, project: str) -> None:
        source = register(client, project)
        retire(client, project, source["source_id"])

        response = client.delete(f"/v1/projects/{project}/sources/{source['source_id']}/retirement")

        assert response.status_code == 200, response.text
        assert response.json()["retired_at"] is None

    def test_registering_the_same_repository_again_brings_it_back(
        self, client: TestClient, project: str
    ) -> None:
        """Identity is `(project, kind, location)`, so this is the only way back
        for somebody who does not know the source id — and without it, retiring
        a source would permanently forbid adding that repository again."""
        source = register(client, project)
        retire(client, project, source["source_id"])

        again = register(client, project)

        assert again["source_id"] == source["source_id"]
        assert again["retired_at"] is None


class TestTheFirstRetirementIsTheOneThatCounts:
    def test_retiring_twice_keeps_the_original_timestamp(
        self, client: TestClient, project: str
    ) -> None:
        # A repeated call is a caller that lost its response, not a second
        # decision, and *when did we stop reading this* has one true answer.
        source = register(client, project)
        first = retire(client, project, source["source_id"])

        assert retire(client, project, source["source_id"])["retired_at"] == first["retired_at"]

    def test_restoring_one_nobody_retired_is_not_an_error(
        self, client: TestClient, project: str
    ) -> None:
        source = register(client, project)

        response = client.delete(f"/v1/projects/{project}/sources/{source['source_id']}/retirement")

        assert response.status_code == 200, response.text
        assert response.json()["retired_at"] is None


class TestItIsScopedToItsProject:
    def test_another_project_cannot_retire_this_source(
        self, client: TestClient, project: str
    ) -> None:
        # The same rule `_require` already holds for every other write: a source
        # id that resolved across projects would let a caller naming their own
        # project change somebody else's configuration.
        source = register(client, project)
        other = str(client.post("/v1/projects", json={"name": "Somebody else"}).json()["id"])

        response = client.post(f"/v1/projects/{other}/sources/{source['source_id']}/retirement")

        assert response.status_code == 404, response.text
