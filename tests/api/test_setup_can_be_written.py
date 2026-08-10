"""Setup has a write path over HTTP, for the first time.

`GET /setup`, `/setup/questions` and `/publication-targets` have existed since
migration `0020`. **There were no POST routes at all**, so the only way to
configure a project was to call `SetupService` from Python — and nothing did.
Read from the deployed database: `project_configuration`, `publication_targets`,
`provider_connections` and `setup_questions` held **zero rows between them**,
against 1,977 knowledge items.

Not under-used. Never written to, once, ever. Stage one of the product was
schema.

## What these assert

That a person can configure a project through the product, and that the two
things a configuration surface must never do — invent a destination, or carry a
secret — are refused at the boundary rather than deeper in.
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
    return str(client.post("/v1/projects", json={"name": "Setup over HTTP"}).json()["id"])


def _connection(client: TestClient, project: str, **overrides: Any) -> dict[str, Any]:
    body = {"provider": "github", "credential_reference": "env:KAE_GITHUB_TOKEN"}
    body.update(overrides)
    response = client.post(f"/v1/projects/{project}/connections", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestAProjectCanBeConfigured:
    def test_a_field_can_be_set_at_all(self, client: TestClient, project: str) -> None:
        """The whole finding, in one assertion."""

        response = client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={
                "field": "primary_repository",
                "value": "crismag/KAE-Studio",
                "state": "confirmed",
                "confirmed_by": "cris",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["configuration"]["primary_repository"]["value"] == (
            "crismag/KAE-Studio"
        )

    def test_it_survives_and_is_readable_afterwards(self, client: TestClient, project: str) -> None:
        """Durability is the point. A configuration held in a form is a
        configuration lost on reload, which is what Studio does today."""

        client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={
                "field": "primary_branch",
                "value": "main",
                "state": "confirmed",
                "confirmed_by": "cris",
            },
        )

        body = client.get(f"/v1/projects/{project}/setup").json()

        assert body["configuration"]["primary_branch"]["value"] == "main"
        assert body["configuration"]["primary_branch"]["in_use"] is True
        assert "primary_branch" not in body["unknown_fields"]

    def test_an_unknown_field_is_refused_and_says_what_is_valid(
        self, client: TestClient, project: str
    ) -> None:
        """A rejection that does not name what is valid is a guessing game.

        And the guard matters beyond tidiness: an unknown field written into
        `project_configuration` makes `GET /setup` unreadable for that project,
        permanently, with no route that can remove it.
        """

        response = client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={"field": "primry_repository", "value": "x", "state": "confirmed"},
        )

        assert response.status_code == 422, response.text
        assert "primary_repository" in response.text

    def test_a_confirmed_value_must_name_who_confirmed_it(
        self, client: TestClient, project: str
    ) -> None:
        """`confirmed` is a claim about a person. Unattributed, it is a guess
        wearing the word the product uses for human agreement."""

        response = client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={"field": "primary_repository", "value": "crismag/x", "state": "confirmed"},
        )

        assert response.status_code == 422, response.text

    def test_a_suggestion_must_carry_its_evidence(self, client: TestClient, project: str) -> None:
        response = client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={"field": "primary_repository", "value": "crismag/x", "state": "suggested"},
        )

        assert response.status_code == 422, response.text

    def test_a_suggestion_is_not_in_use(self, client: TestClient, project: str) -> None:
        """The distinction a setup surface renders. A suggested value is
        something to accept, not something the project is configured with."""

        client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={
                "field": "project_kind",
                "value": "web application",
                "state": "suggested",
                "evidence": "the repository has a package.json and a Dockerfile",
            },
        )

        body = client.get(f"/v1/projects/{project}/setup").json()

        assert body["configuration"]["project_kind"]["in_use"] is False
        assert body["configuration"]["project_kind"]["evidence"]


class TestTheOutputRepositoryCanBeSetAndChanged:
    def test_a_target_can_be_registered(self, client: TestClient, project: str) -> None:
        connection = _connection(client, project)["connection_id"]

        response = client.post(
            f"/v1/projects/{project}/publication-targets",
            json={
                "provider": "github",
                "name": "planning docs",
                "configuration": {"repository": "crismag/KAE-Studio", "path": "docs/"},
                "connection_id": connection,
                "make_default": True,
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["is_default"] is True
        assert response.json()["configuration"]["repository"] == "crismag/KAE-Studio"

    def test_the_default_can_be_pointed_somewhere_else(
        self, client: TestClient, project: str
    ) -> None:
        """The act that was impossible.

        `register_target(make_default=True)` refuses once a default exists, so
        a project's output destination could be chosen once and never changed.
        """

        connection = _connection(client, project)["connection_id"]
        client.post(
            f"/v1/projects/{project}/publication-targets",
            json={
                "provider": "github",
                "name": "old",
                "connection_id": connection,
                "make_default": True,
            },
        )
        second = client.post(
            f"/v1/projects/{project}/publication-targets",
            json={"provider": "github", "name": "new", "connection_id": connection},
        ).json()

        response = client.post(
            f"/v1/projects/{project}/publication-targets/default",
            json={"target_id": second["target_id"]},
        )

        assert response.status_code == 200, response.text
        listed = {
            t["name"]: t for t in client.get(f"/v1/projects/{project}/setup").json()["targets"]
        }
        assert listed["new"]["is_default"] is True
        assert listed["old"]["is_default"] is False

    def test_a_second_default_is_a_conflict_that_names_the_remedy(
        self, client: TestClient, project: str
    ) -> None:
        """409, not 422 — the request is well-formed and the state refuses it.

        A conflict that does not name the way forward leaves a caller retrying
        the thing that just failed.
        """

        connection = _connection(client, project)["connection_id"]
        for name in ("one", "two"):
            response = client.post(
                f"/v1/projects/{project}/publication-targets",
                json={
                    "provider": "github",
                    "name": name,
                    "connection_id": connection,
                    "make_default": True,
                },
            )

        assert response.status_code == 409, response.text
        assert "publication-targets/default" in response.text

    def test_an_unknown_target_is_not_found(self, client: TestClient, project: str) -> None:
        response = client.post(
            f"/v1/projects/{project}/publication-targets/default",
            json={"target_id": "00000000-0000-0000-0000-000000000000"},
        )

        assert response.status_code == 404, response.text

    def test_a_credential_in_the_coordinate_is_refused(
        self, client: TestClient, project: str
    ) -> None:
        """A target's configuration is a coordinate. A token in it would be
        returned by `GET /setup` to anybody who can read the project."""

        connection = _connection(client, project)["connection_id"]

        response = client.post(
            f"/v1/projects/{project}/publication-targets",
            json={
                "provider": "github",
                "name": "leaky",
                "configuration": {"repository": "crismag/x", "access_token": "ghp_secret"},
                "connection_id": connection,
            },
        )

        assert response.status_code == 422, response.text
        assert "ghp_secret" not in response.text

    def test_a_remote_target_needs_a_connection(self, client: TestClient, project: str) -> None:
        """Publishing somewhere nobody granted access to is not a destination
        that can be honoured, and refusing it here is cheaper than at write."""

        response = client.post(
            f"/v1/projects/{project}/publication-targets",
            json={"provider": "github", "name": "unauthorised", "configuration": {}},
        )

        assert response.status_code == 422, response.text


class TestConnectionsAreRecordedWithoutTheirSecrets:
    def test_a_connection_can_be_recorded_and_listed(
        self, client: TestClient, project: str
    ) -> None:
        _connection(client, project)

        body = client.get(f"/v1/projects/{project}/connections").json()

        assert body["total"] == 1
        assert body["results"][0]["credential_reference"] == "env:KAE_GITHUB_TOKEN"
        assert body["results"][0]["state"] == "never_granted"

    def test_a_secret_is_refused_where_a_reference_belongs(
        self, client: TestClient, project: str
    ) -> None:
        """The rule the record exists to hold. A secret that reaches a row has
        already been written somewhere readable, and deleting it does not
        unwrite it."""

        response = client.post(
            f"/v1/projects/{project}/connections",
            json={"provider": "github", "credential_reference": "ghp_abcdefghijklmnop"},
        )

        assert response.status_code == 422, response.text
        assert "ghp_abcdefghijklmnop" not in response.text

    def test_a_connection_becomes_granted_after_a_check(
        self, client: TestClient, project: str
    ) -> None:
        """`record_connection` only inserts, so this transition had no path.

        Re-recording instead would leave a second row behind on every attempt.
        """

        connection = _connection(client, project)["connection_id"]

        response = client.post(
            f"/v1/projects/{project}/connections/{connection}/authorization",
            json={"state": "granted", "authorized_by": "cris", "detail": "read access verified"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["state"] == "granted"
        assert response.json()["last_verified_at"] is not None
        assert client.get(f"/v1/projects/{project}/connections").json()["total"] == 1

    def test_granting_without_naming_who_is_refused(self, client: TestClient, project: str) -> None:
        connection = _connection(client, project)["connection_id"]

        response = client.post(
            f"/v1/projects/{project}/connections/{connection}/authorization",
            json={"state": "granted"},
        )

        assert response.status_code == 422, response.text

    def test_authorising_makes_a_target_available(self, client: TestClient, project: str) -> None:
        """The end of the chain, and the reason any of this exists.

        A target is unavailable until its connection is granted, and
        `GET /setup` reports that per target with a reason rather than a
        boolean.
        """

        connection = _connection(client, project)["connection_id"]
        client.post(
            f"/v1/projects/{project}/publication-targets",
            json={"provider": "github", "name": "docs", "connection_id": connection},
        )
        before = client.get(f"/v1/projects/{project}/setup").json()["targets"][0]
        assert before["available"] is False
        assert before["unavailable_reason"]

        client.post(
            f"/v1/projects/{project}/connections/{connection}/authorization",
            json={"state": "granted", "authorized_by": "cris"},
        )

        after = client.get(f"/v1/projects/{project}/setup").json()["targets"][0]
        assert after["available"] is True

    def test_an_unknown_connection_is_not_found(self, client: TestClient, project: str) -> None:
        response = client.post(
            f"/v1/projects/{project}/connections/"
            f"00000000-0000-0000-0000-000000000000/authorization",
            json={"state": "granted", "authorized_by": "cris"},
        )

        assert response.status_code == 404, response.text


class TestSetupStaysApartFromKnowledge:
    def test_configuring_a_project_writes_no_knowledge(
        self, client: TestClient, project: str
    ) -> None:
        """The boundary the whole service exists to hold.

        *"Publish to crismag/KAE-Studio"* is a configuration decision. Recorded
        as knowledge it would arrive in front of a reviewer as something to
        confirm about the product.
        """

        client.post(
            f"/v1/projects/{project}/setup/configuration",
            json={
                "field": "primary_repository",
                "value": "crismag/KAE-Studio",
                "state": "confirmed",
                "confirmed_by": "cris",
            },
        )

        knowledge = client.get(f"/v1/projects/{project}/knowledge").json()
        items = knowledge["results"] if isinstance(knowledge, dict) else knowledge
        assert items == []

    def test_setup_readiness_is_not_knowledge_readiness(
        self, client: TestClient, project: str
    ) -> None:
        """A project with a clear brief and no authorisation is fully
        understood and cannot publish. Two questions, two answers."""

        setup = client.get(f"/v1/projects/{project}/setup").json()
        readiness = client.get(f"/v1/projects/{project}/readiness").json()

        assert "percentage" not in setup
        assert "setup_state" not in readiness
