"""The HTTP trust boundary (N5, ADR-0024).

ADR-0014 accepted "no authentication" on the reasoning that the API sat behind a
network boundary. N3 put search, ingestion, clarification, assembly, and
classification behind that same surface, and ADR-0023 made HTTP the transport a
browser speaks. The reasoning no longer holds.

The assertion that matters most is not that a token works. It is that a process
which would expose an unauthenticated API **refuses to start**:

    a warning about an unauthenticated public API is a line in a log a
    deployment scrolls past; a refusal to start is a deployment that does not
    happen.

The second is that authentication and authorisation stay separate. A token
proves who is calling; whether they may read a given project is a different
question, and answering both with one lookup is how a convenience quietly
becomes a security control.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import (
    MAX_BODY_BYTES,
    REQUEST_ID_HEADER,
    AuthPolicy,
    InsecureDeploymentError,
    Principal,
    generate_token,
    resolve_policy,
)

TOKEN = "test-token-value"
OTHER = "other-token-value"


def _policy(**principals: Principal) -> AuthPolicy:
    return AuthPolicy(tokens=dict(principals.items()))


@pytest.fixture
def open_client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """A loopback development process: no tokens, no authentication."""

    with TestClient(create_app(factory, auth=AuthPolicy())) as client:
        yield client


@pytest.fixture
def secured(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    policy = _policy(**{TOKEN: Principal(name="studio")})
    with TestClient(create_app(factory, auth=policy)) as client:
        yield client


class TestExposureFailsClosed:
    def test_binding_off_loopback_without_tokens_refuses_to_start(self) -> None:
        """The assertion this whole file exists for."""

        with pytest.raises(InsecureDeploymentError) as raised:
            resolve_policy({}, host="0.0.0.0")

        message = str(raised.value)
        assert "0.0.0.0" in message
        assert "KAE_API_TOKENS" in message

    def test_loopback_without_tokens_is_refused(self) -> None:
        """This asserted the opposite, and the belief behind it was the defect.

        "A developer's laptop is not a deployment" is true and does not follow
        from the bind address: nginx in front of a loopback listener is a public
        API, and the process cannot tell that apart from a laptop. A laptop now
        says so explicitly — see `tests/api/test_auth_cannot_fail_open.py`."""

        with pytest.raises(InsecureDeploymentError):
            resolve_policy({}, host="127.0.0.1")

    def test_binding_off_loopback_with_tokens_is_allowed(self) -> None:
        policy = resolve_policy({"KAE_API_TOKENS": f"studio:{TOKEN}"}, host="0.0.0.0")

        assert policy.enabled is True

    def test_a_malformed_token_entry_is_refused_rather_than_ignored(self) -> None:
        """A token that silently failed to parse is an API with one fewer credential."""

        with pytest.raises(InsecureDeploymentError):
            resolve_policy({"KAE_API_TOKENS": "no-token-here:"}, host="0.0.0.0")


class TestAuthentication:
    def test_an_unauthenticated_request_is_refused(self, secured: TestClient) -> None:
        response = secured.get("/v1/projects")

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"

    def test_a_valid_token_is_accepted(self, secured: TestClient) -> None:
        response = secured.get("/v1/projects", headers={"Authorization": f"Bearer {TOKEN}"})

        assert response.status_code == 200

    def test_a_wrong_token_is_refused(self, secured: TestClient) -> None:
        response = secured.get("/v1/projects", headers={"Authorization": f"Bearer {OTHER}"})

        assert response.status_code == 401

    def test_the_scheme_must_be_bearer(self, secured: TestClient) -> None:
        response = secured.get("/v1/projects", headers={"Authorization": f"Basic {TOKEN}"})

        assert response.status_code == 401

    def test_the_refusal_says_nothing_useful_to_an_attacker(self, secured: TestClient) -> None:
        """ "Unknown token" and "expired token" are different facts.

        Telling them apart helps an attacker and nobody else.
        """

        unknown = secured.get("/v1/projects", headers={"Authorization": "Bearer nope"}).json()
        absent = secured.get("/v1/projects").json()

        assert unknown["error"]["message"] == absent["error"]["message"]

    def test_health_answers_without_a_token(self, secured: TestClient) -> None:
        """FR-017. A health check needing a credential fails for two reasons a
        monitor most needs to tell apart."""

        response = secured.get("/health")

        assert response.status_code == 200

    def test_an_unauthenticated_process_lets_everything_through(
        self, open_client: TestClient
    ) -> None:
        assert open_client.get("/v1/projects").status_code == 200


class TestAuthorisationIsSeparate:
    def test_a_scoped_token_reaches_its_own_project(self, factory: sessionmaker[Session]) -> None:
        with TestClient(create_app(factory, auth=AuthPolicy())) as setup:
            mine = setup.post("/v1/projects", json={"name": "Mine"}).json()["id"]

        policy = _policy(**{TOKEN: Principal(name="studio", projects=frozenset({str(mine)}))})
        with TestClient(create_app(factory, auth=policy)) as client:
            response = client.get(
                f"/v1/projects/{mine}/readiness", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code == 200

    def test_a_scoped_token_cannot_reach_another_project(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Authentication succeeded. Authorisation is the second question."""

        with TestClient(create_app(factory, auth=AuthPolicy())) as setup:
            mine = setup.post("/v1/projects", json={"name": "Mine"}).json()["id"]
            theirs = setup.post("/v1/projects", json={"name": "Theirs"}).json()["id"]

        policy = _policy(**{TOKEN: Principal(name="studio", projects=frozenset({str(mine)}))})
        with TestClient(create_app(factory, auth=policy)) as client:
            response = client.get(
                f"/v1/projects/{theirs}/readiness", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code == 404, "a 403 would confirm the project exists"

    def test_an_unscoped_token_reaches_every_project(self, factory: sessionmaker[Session]) -> None:
        """The restriction is opt-in: a token scoped to nothing would
        authenticate and do nothing, which is a configuration mistake."""

        with TestClient(create_app(factory, auth=AuthPolicy())) as setup:
            project = setup.post("/v1/projects", json={"name": "Any"}).json()["id"]

        policy = _policy(**{TOKEN: Principal(name="studio")})
        with TestClient(create_app(factory, auth=policy)) as client:
            response = client.get(
                f"/v1/projects/{project}/readiness", headers={"Authorization": f"Bearer {TOKEN}"}
            )

        assert response.status_code == 200

    def test_scoping_covers_routes_added_later(self, factory: sessionmaker[Session]) -> None:
        """Applied by path rather than in each router.

        A route added tomorrow under `/v1/projects/{id}/` is covered the day it
        is added, not the day someone remembers to add a check to it.
        """

        with TestClient(create_app(factory, auth=AuthPolicy())) as setup:
            mine = setup.post("/v1/projects", json={"name": "Mine"}).json()["id"]
            theirs = setup.post("/v1/projects", json={"name": "Theirs"}).json()["id"]

        policy = _policy(**{TOKEN: Principal(name="studio", projects=frozenset({str(mine)}))})
        headers = {"Authorization": f"Bearer {TOKEN}"}
        with TestClient(create_app(factory, auth=policy)) as client:
            for path in (
                f"/v1/projects/{theirs}/knowledge/search?query=x",
                f"/v1/projects/{theirs}/context",
                f"/v1/projects/{theirs}/operational-state",
                f"/v1/projects/{theirs}/classifications",
            ):
                assert client.get(path, headers=headers).status_code == 404, path


class TestRequestBounds:
    def test_an_oversized_body_is_refused_before_it_is_read(self, secured: TestClient) -> None:
        response = secured.post(
            "/v1/projects",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "content-length": str(MAX_BODY_BYTES + 1),
            },
            json={"name": "Big"},
        )

        assert response.status_code == 413

    def test_an_ordinary_body_passes(self, secured: TestClient) -> None:
        response = secured.post(
            "/v1/projects", headers={"Authorization": f"Bearer {TOKEN}"}, json={"name": "Small"}
        )

        assert response.status_code == 201


class TestCorrelation:
    def test_every_response_carries_a_request_id(self, secured: TestClient) -> None:
        """An error a caller cannot correlate to a log line is undiagnosable."""

        response = secured.get("/v1/projects", headers={"Authorization": f"Bearer {TOKEN}"})

        assert response.headers[REQUEST_ID_HEADER]

    def test_a_supplied_request_id_is_kept(self, secured: TestClient) -> None:
        """A caller that already correlates its own work should not be renamed."""

        response = secured.get(
            "/v1/projects",
            headers={"Authorization": f"Bearer {TOKEN}", REQUEST_ID_HEADER: "abc-123"},
        )

        assert response.headers[REQUEST_ID_HEADER] == "abc-123"

    def test_a_refusal_carries_one_too(self, secured: TestClient) -> None:
        response = secured.get("/v1/projects")

        assert response.status_code == 401
        assert response.headers[REQUEST_ID_HEADER]


class TestTokenConfiguration:
    def test_tokens_parse_with_project_scopes(self) -> None:
        policy = resolve_policy(
            {"KAE_API_TOKENS": f"studio:{TOKEN}:p1,p2; agent:{OTHER}"}, host="0.0.0.0"
        )

        assert policy.tokens[TOKEN].projects == frozenset({"p1", "p2"})
        assert policy.tokens[OTHER].projects == frozenset()
        assert policy.tokens[OTHER].name == "agent"

    def test_a_generated_token_is_not_guessable(self) -> None:
        """Provided so that "make one up" is not the documented instruction."""

        first, second = generate_token(), generate_token()

        assert first != second
        assert len(first) >= 32
