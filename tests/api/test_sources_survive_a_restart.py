"""A source configuration outlives the process that took it (`D-21`, `AUD-005`).

The finding, open since the audit: *"connections vanish on restart."* Studio's
`AcquisitionService` held `self._sources: dict`, so somebody who connected a
repository, set its include and exclude paths, and pinned a revision lost all of
it on the next deploy — and there was nothing to complain to, because no table
existed. `ADR-0004` ruled that KAE-Memory owns the source reference.

## What these hold

The **restart** itself, asserted rather than assumed: a second client, over a
fresh application, reads back what the first one wrote. That is the entire
finding, and it is the one assertion a service with a dictionary in it cannot
satisfy.

Then the three things the record must not blur: a pin is not a read, an
unclassified source is not a kept one, and re-registering a repository is not
losing its revision.
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
    return str(client.post("/v1/projects", json={"name": "Durable sources"}).json()["id"])


REPOSITORY = {
    "kind": "github",
    "location": "kae/ministry-reporting",
    "state": "configured",
    "scope": {
        "include": ["docs/", "src/"],
        "exclude": ["node_modules/"],
        "max_file_bytes": 200_000,
        "documentation_only": False,
    },
}


def register(client: TestClient, project: str, **overrides: object) -> dict[str, Any]:
    body = {**REPOSITORY, **overrides}
    response = client.post(f"/v1/projects/{project}/sources", json=body)
    assert response.status_code == 201, response.text
    registered: dict[str, Any] = response.json()
    return registered


class TestItSurvivesTheProcess:
    def test_a_second_process_reads_back_what_the_first_one_wrote(
        self, client: TestClient, project: str, factory: sessionmaker[Session]
    ) -> None:
        """`AUD-005`, as an assertion.

        A fresh application over the same database — the closest a test gets to
        the deploy that used to erase this. A service holding a dictionary
        passes every other test in this file and fails this one.
        """

        register(client, project)

        with TestClient(create_app(factory, auth=AuthPolicy())) as restarted:
            sources = restarted.get(f"/v1/projects/{project}/sources").json()

        assert [source["location"] for source in sources] == ["kae/ministry-reporting"]

    def test_the_scope_survives_with_it(
        self, client: TestClient, project: str, factory: sessionmaker[Session]
    ) -> None:
        """The part that costs a person real time to re-enter.

        A location can be re-picked from a list. Include paths, exclusions and
        a size ceiling are decisions somebody made about what KAE should read,
        and losing them is losing the thinking rather than the typing.
        """

        register(client, project)

        with TestClient(create_app(factory, auth=AuthPolicy())) as restarted:
            source = restarted.get(f"/v1/projects/{project}/sources").json()[0]

        assert source["scope"] == REPOSITORY["scope"]

    def test_a_pin_survives_with_it(
        self, client: TestClient, project: str, factory: sessionmaker[Session]
    ) -> None:
        source = register(client, project)
        client.post(
            f"/v1/projects/{project}/sources/{source['source_id']}/pin",
            json={"revision": "9f2c1ab", "digest": "sha256:abc"},
        )

        with TestClient(create_app(factory, auth=AuthPolicy())) as restarted:
            reread = restarted.get(f"/v1/projects/{project}/sources").json()[0]

        assert reread["pinned_revision"] == "9f2c1ab"
        assert reread["pinned"] is True


class TestWhatTheRecordMustNotBlur:
    def test_a_configured_source_is_not_a_pinned_one(
        self, client: TestClient, project: str
    ) -> None:
        """A branch moves and a commit does not.

        Evidence drawn from an unpinned source cannot be rechecked against what
        it actually said, so `pinned` is a fact the response states rather than
        one each caller works out.
        """

        source = register(client, project)

        assert source["pinned"] is False
        assert source["pinned_revision"] is None

    def test_a_source_nobody_classified_is_not_classified(
        self, client: TestClient, project: str
    ) -> None:
        """`null`, never `MEMORY`.

        `ADR-0004`'s five dispositions gate ingestion at volume. A default of
        "keep it here" would let a source nobody decided about pass for one
        somebody did — the more expensive of the two mistakes and the harder to
        see afterwards.
        """

        source = register(client, project)

        assert source["disposition"] is None

    def test_recording_a_refusal_keeps_the_provider_s_own_words(
        self, client: TestClient, project: str
    ) -> None:
        source = register(client, project)

        updated = client.post(
            f"/v1/projects/{project}/sources/{source['source_id']}/state",
            json={"state": "refused", "detail": "403: token lacks Contents: Read"},
        ).json()

        # Verbatim. A reason paraphrased on the way through is one nobody can
        # act on, and the caller is the only party that saw the original.
        assert updated["detail"] == "403: token lacks Contents: Read"
        assert updated["state"] == "refused"

    def test_a_source_belongs_to_its_project(self, client: TestClient, project: str) -> None:
        """A source id that resolved across projects would let a caller naming
        their own project read somebody else's configuration."""

        source = register(client, project)
        other = str(client.post("/v1/projects", json={"name": "Somebody else"}).json()["id"])

        response = client.get(f"/v1/projects/{other}/sources/{source['source_id']}")

        assert response.status_code == 404


class TestRegisteringTwice:
    def test_the_same_repository_twice_is_one_source(
        self, client: TestClient, project: str
    ) -> None:
        """Idempotent by `(kind, location)`, like a project and a module.

        A caller that loses its response can retry without first asking whether
        it succeeded.
        """

        first = register(client, project)
        second = register(client, project)

        assert first["source_id"] == second["source_id"]
        assert len(client.get(f"/v1/projects/{project}/sources").json()) == 1

    def test_re_registering_does_not_lose_the_revision(
        self, client: TestClient, project: str
    ) -> None:
        """Somebody re-adding a repository has said nothing about its revision.

        Silently unpinning it would discard the one field that makes the
        evidence recheckable, and it would do so in the flow least likely to be
        looked at afterwards.
        """

        source = register(client, project)
        client.post(
            f"/v1/projects/{project}/sources/{source['source_id']}/pin",
            json={"revision": "9f2c1ab"},
        )

        reregistered = register(client, project, scope={"include": ["docs/"]})

        assert reregistered["pinned_revision"] == "9f2c1ab"
        # And the scope the caller did restate has changed, so this is not
        # passing because the write was ignored wholesale.
        assert reregistered["scope"] == {"include": ["docs/"]}

    def test_a_different_location_is_a_different_source(
        self, client: TestClient, project: str
    ) -> None:
        register(client, project)
        register(client, project, location="kae/second-repository")

        assert len(client.get(f"/v1/projects/{project}/sources").json()) == 2


class TestWhatItRefuses:
    @pytest.mark.parametrize("field", ["kind", "location", "state"])
    def test_a_source_without_its_essentials_is_refused(
        self, client: TestClient, project: str, field: str
    ) -> None:
        response = client.post(f"/v1/projects/{project}/sources", json={**REPOSITORY, field: "   "})

        assert response.status_code == 422

    def test_a_project_that_does_not_exist_is_not_a_project_with_no_sources(
        self, client: TestClient
    ) -> None:
        response = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/sources")

        assert response.status_code == 404

    def test_a_disposition_outside_the_five_is_refused(
        self, client: TestClient, project: str
    ) -> None:
        """`D-162`. A misspelt `ephemeral` is not a classification.

        Nothing reads the column yet, which is why the set closes now: the first
        reader of a free-text column inherits every value ever written to it.
        """

        source = register(client, project)

        response = client.post(
            f"/v1/projects/{project}/sources/{source['source_id']}/disposition",
            json={"disposition": "ephemral"},
        )

        assert response.status_code == 422
        # The five are named, not merely refused: a caller who mistyped one
        # needs the list, and a caller who invented one needs to know there is
        # a list.
        assert "ephemeral" in str(response.json())

    def test_registering_cannot_name_what_classifying_refuses(
        self, client: TestClient, project: str
    ) -> None:
        """The same set at both doors, or the column is free text by the other."""

        response = client.post(
            f"/v1/projects/{project}/sources",
            json={**REPOSITORY, "disposition": "keep-it-all"},
        )

        assert response.status_code == 422

    def test_the_same_decision_in_either_case_is_one_value(
        self, client: TestClient, project: str
    ) -> None:
        """`MEMORY` and `memory` are the same decision, stored one way.

        Two spellings of one disposition read back as two values to whatever
        eventually acts on them, which is the free-text failure with extra
        steps.
        """

        source = register(client, project)

        stored = client.post(
            f"/v1/projects/{project}/sources/{source['source_id']}/disposition",
            json={"disposition": " EPHEMERAL "},
        ).json()

        assert stored["disposition"] == "ephemeral"

    def test_it_stores_no_content(self, client: TestClient, project: str) -> None:
        """A source names material and never holds it.

        `ADR-0004` exists to stop a repository being copied wholesale into this
        database, and a body field that accepts file content would defeat the
        ruling while looking like progress.
        """

        response = client.post(
            f"/v1/projects/{project}/sources",
            json={**REPOSITORY, "content": "the whole file", "body": "more of it"},
        )

        assert response.status_code == 201
        assert "content" not in response.json()
        assert "body" not in response.json()
