"""Durable deliverable identity (N20).

`assemble_context` produces a description and forgets it: `package_id` is fresh
per call, deliberately, because an assembly is a computation and a computation
should not hand out an identity that outlives it. Studio's `listDeliverables`
was blocked on exactly that — there was nothing to list.

A deliverable is the other thing. Four claims this file holds:

    it is identified by content, not by call — recording twice is one record;
    it is immutable except its lifecycle;
    it holds no bytes, and says it was neither rendered nor published;
    staleness is derived, never stored.

The last one matters more than it looks. A stored staleness flag is true until
something remembers to update it, and the write most likely to forget is the
one that made it false.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.deliverables import (
    Deliverable,
    DeliverableId,
    DeliverableState,
    InvalidDeliverableTransitionError,
    ensure_deliverable_transition,
    identity_hash,
)
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project_id(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Ministry"}).json()["id"])


def _seed(factory: sessionmaker[Session], project_id: str, text: str) -> str:
    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, f"n20-{len(text)}")
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.REQUIREMENT.value, text, "seed")]
    )
    return str(written[0].id)


def _record(client: TestClient, project_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/v1/projects/{project_id}/deliverables", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestTheDomainRules:
    def _deliverable(self, **overrides: Any) -> Deliverable:
        fields: dict[str, Any] = {
            "id": DeliverableId("d1"),
            "project_id": ProjectId("p1"),
            "purpose": "implementation",
            "scope": "project",
            "knowledge_revision": 4,
            "content_hash": "sha256:abc",
            "artifacts": (),
        }
        fields.update(overrides)
        return Deliverable(**fields)

    def test_a_deliverable_needs_a_content_hash(self) -> None:
        """Without one it cannot be compared to what was later rendered."""

        with pytest.raises(DomainInvariantError, match="content hash"):
            self._deliverable(content_hash="  ")

    def test_a_module_scoped_deliverable_names_its_module(self) -> None:
        with pytest.raises(DomainInvariantError, match="module"):
            self._deliverable(scope="module")

    def test_staleness_is_a_comparison_not_a_field(self) -> None:
        deliverable = self._deliverable(knowledge_revision=4)

        assert deliverable.is_stale_against(4) is False
        assert deliverable.is_stale_against(5) is True

    def test_identity_is_content_and_revision(self) -> None:
        """The same content at a later revision is a different claim.

        It says the project moved and the output did not.
        """

        first = identity_hash(ProjectId("p1"), "implementation", "project", None, 4, "h")
        same = identity_hash(ProjectId("p1"), "implementation", "project", None, 4, "h")
        later = identity_hash(ProjectId("p1"), "implementation", "project", None, 5, "h")

        assert first == same
        assert first != later

    def test_terminal_states_are_terminal(self) -> None:
        """Two records each claiming to be latest would both be right locally."""

        for state in (DeliverableState.SUPERSEDED, DeliverableState.WITHDRAWN):
            with pytest.raises(InvalidDeliverableTransitionError):
                ensure_deliverable_transition(state, DeliverableState.RECORDED)


class TestRecording:
    def test_it_creates_something_resolvable_by_id(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """201, unlike assembly's GET, because something durable now exists."""

        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        assert body["deliverable_id"]
        assert body["recorded"] is True
        again = client.get(f"/v1/projects/{project_id}/deliverables/{body['deliverable_id']}")
        assert again.status_code == 200

    def test_recording_the_same_output_twice_is_one_deliverable(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A second id would report a change the project did not make."""

        _seed(factory, project_id, "A report must be approved.")

        first = _record(client, project_id)
        second = _record(client, project_id)

        assert second["deliverable_id"] == first["deliverable_id"]
        assert second["recorded"] is False
        listed = client.get(f"/v1/projects/{project_id}/deliverables").json()
        assert listed["total"] == 1

    def test_the_same_content_at_a_later_revision_is_a_new_deliverable(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        first = _record(client, project_id)
        _seed(factory, project_id, "Reports are retained for seven years.")
        second = _record(client, project_id)

        assert second["deliverable_id"] != first["deliverable_id"]

    def test_an_unknown_purpose_is_refused(self, client: TestClient, project_id: str) -> None:
        response = client.post(
            f"/v1/projects/{project_id}/deliverables", json={"purpose": "whatever"}
        )

        assert response.status_code == 422


class TestItHoldsNoBytesAndClaimsNothing:
    def test_it_says_it_was_neither_rendered_nor_published(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Their absence would let a caller assume either happened."""

        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        assert body["rendered"] is False
        assert body["published"] is False

    def test_artifacts_are_described_not_contained(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A hash lets a renderer prove what it wrote matches, without the bytes."""

        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        for artifact in body["artifacts"]:
            assert artifact["content_hash"]
            assert "content" not in artifact
            assert "bytes" not in artifact

    def test_no_stored_column_holds_content(self, factory: sessionmaker[Session]) -> None:
        """Asserted against the mapping, not the payload.

        A response can omit a column the table still has, and the constraint
        N20 was given was about the database.
        """

        from kae_memory.persistence.tables import DeliverableRow

        columns = set(DeliverableRow.__table__.columns.keys())

        assert not columns & {"content", "body", "bytes", "payload", "blob", "rendered_content"}


class TestProvenanceAndOwnership:
    def test_the_source_knowledge_is_recorded(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        assert isinstance(body["source_knowledge"], list)
        assert body["content_hash"].startswith("sha256:")

    def test_a_deliverable_belongs_to_its_project(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """An id alone must not cross a project boundary."""

        _seed(factory, project_id, "A report must be approved.")
        body = _record(client, project_id)
        other = str(client.post("/v1/projects", json={"name": "Other"}).json()["id"])

        response = client.get(f"/v1/projects/{other}/deliverables/{body['deliverable_id']}")

        assert response.status_code == 404

    def test_who_recorded_it_is_kept(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id, recorded_by="cris")

        assert body["recorded_by"] == "cris"


class TestStaleness:
    def test_a_fresh_deliverable_is_not_stale(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")

        assert _record(client, project_id)["stale"] is False

    def test_it_becomes_stale_when_the_project_moves(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Still what was produced; no longer what the project now says."""

        _seed(factory, project_id, "A report must be approved.")
        recorded = _record(client, project_id)
        _seed(factory, project_id, "Reports are retained for seven years.")

        current = client.get(
            f"/v1/projects/{project_id}/deliverables/{recorded['deliverable_id']}"
        ).json()

        assert current["stale"] is True
        assert current["knowledge_revision"] == recorded["knowledge_revision"]


class TestLifecycle:
    def _two(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> tuple[str, str]:
        _seed(factory, project_id, "A report must be approved.")
        first = _record(client, project_id)["deliverable_id"]
        _seed(factory, project_id, "Reports are retained for seven years.")
        second = _record(client, project_id)["deliverable_id"]
        return first, second

    def test_a_deliverable_can_be_superseded(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        first, second = self._two(client, factory, project_id)

        response = client.post(
            f"/v1/projects/{project_id}/deliverables/{first}/supersede",
            json={"replacement_id": second},
        )

        assert response.status_code == 200
        assert response.json()["state"] == "superseded"
        assert response.json()["superseded_by"] == second

    def test_the_superseded_record_survives(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A deleted answer answers nothing, and the question is historical."""

        first, second = self._two(client, factory, project_id)
        client.post(
            f"/v1/projects/{project_id}/deliverables/{first}/supersede",
            json={"replacement_id": second},
        )

        still_there = client.get(f"/v1/projects/{project_id}/deliverables/{first}")

        assert still_there.status_code == 200
        assert still_there.json()["content_hash"]

    def test_withdrawn_is_distinct_from_superseded(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """ "There is a newer one" and "do not use this" are different facts."""

        _seed(factory, project_id, "A report must be approved.")
        recorded = _record(client, project_id)["deliverable_id"]

        response = client.post(
            f"/v1/projects/{project_id}/deliverables/{recorded}/withdraw",
            json={"reason": "the approval rule was wrong"},
        )

        assert response.json()["state"] == "withdrawn"
        assert response.json()["superseded_by"] is None
        assert "wrong" in response.json()["manifest"]["withdrawn_reason"]

    def test_a_terminal_deliverable_cannot_move_again(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        first, second = self._two(client, factory, project_id)
        client.post(
            f"/v1/projects/{project_id}/deliverables/{first}/supersede",
            json={"replacement_id": second},
        )

        refused = client.post(
            f"/v1/projects/{project_id}/deliverables/{first}/withdraw",
            json={"reason": "changed my mind"},
        )

        assert refused.status_code == 409

    def test_listing_filters_by_state(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        first, second = self._two(client, factory, project_id)
        client.post(
            f"/v1/projects/{project_id}/deliverables/{first}/supersede",
            json={"replacement_id": second},
        )

        current = client.get(
            f"/v1/projects/{project_id}/deliverables", params={"states": ["recorded"]}
        ).json()

        assert [d["deliverable_id"] for d in current["deliverables"]] == [second]


class TestTheStudioPortIsUnblocked:
    def test_deliverables_are_listable(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """`listDeliverables` had nothing to list: assembly ids are not identity."""

        _seed(factory, project_id, "A report must be approved.")
        _record(client, project_id)

        listed = client.get(f"/v1/projects/{project_id}/deliverables").json()

        assert listed["total"] == 1
        assert listed["deliverables"][0]["deliverable_id"]

    def test_an_assembly_still_hands_out_no_durable_id(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """The distinction N20 rests on, asserted rather than assumed."""

        _seed(factory, project_id, "A report must be approved.")

        first = client.get(f"/v1/projects/{project_id}/context").json()
        second = client.get(f"/v1/projects/{project_id}/context").json()

        assert first["package"]["package_id"] != second["package"]["package_id"]
        assert first["manifest"]["content_hash"] == second["manifest"]["content_hash"]
