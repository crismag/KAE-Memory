"""The synthesized model and attention queue are HTTP-reachable, apart from extracted knowledge."""

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
from kae_memory.domain.synthesizers.unknowns import ATTENTION_BOUND


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


def _seed_unknowns(factory: sessionmaker[Session], project_id: str, count: int) -> None:
    """Write `count` distinct unresolved questions as extracted evidence."""

    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "extract-unknowns")
    memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="unknown",
                content=f"Question {index}: who owns subsystem {index}?",
                source="interview",
            )
            for index in range(count)
        ],
    )


class TestTheAttentionQueueIsProducedOverHttp:
    """`SYN-3d` filled the live queue by calling the service in-process (`D-115`).

    These assert the same thing is reachable over HTTP, because a queue that
    only a script can fill is not a surface anybody can be given.
    """

    def test_a_run_fills_the_queue_and_bounds_it(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Unknowns"}).json()["id"])
        over_bound = ATTENTION_BOUND + 2
        _seed_unknowns(factory, project, over_bound)

        response = client.post(
            f"/v1/projects/{project}/model/unknowns/runs", json={"idempotency_key": "first"}
        )

        assert response.status_code == 200, response.text
        report = response.json()
        assert report["considered"] == over_bound
        assert report["themes"] == over_bound
        assert len(report["raised"]) == ATTENTION_BOUND
        # The exclusions cross the wire. A response naming only what it raised
        # would make its own withholding unauditable from outside the process.
        assert len(report["withheld"]) == over_bound - ATTENTION_BOUND
        assert report["ranked_by_blocking"] is False

        queue = client.get(f"/v1/projects/{project}/attention")
        assert queue.status_code == 200
        assert len(queue.json()) == ATTENTION_BOUND

    def test_rerunning_raises_nothing_further(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Unknowns twice"}).json()["id"])
        _seed_unknowns(factory, project, 3)
        body = {"idempotency_key": "same"}

        first = client.post(f"/v1/projects/{project}/model/unknowns/runs", json=body)
        second = client.post(f"/v1/projects/{project}/model/unknowns/runs", json=body)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["raised"] == first.json()["raised"]
        assert len(client.get(f"/v1/projects/{project}/attention").json()) == 3

    def test_an_unknown_project_is_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/model/unknowns/runs",
            json={},
        )

        assert response.status_code == 404


class TestDecisionsAreProducedOverHttpAndInterruptNobody:
    """`SYN-5f`. The run route is the only new surface: the decisions
    themselves are read through `GET /model?domain=decision`, because the
    object's own lifecycle is the decision's state (`D-125`)."""

    def _seed(self, factory: sessionmaker[Session], project_id: str) -> None:
        memory = MemoryService(factory)
        run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "extract-decisions")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(kind="decision", content=statement, source="interview")
                for statement in (
                    "Local-first execution is the canonical environment.",
                    "In this session, skip architecture and stay on requirements.",
                )
            ],
        )

    def test_a_run_reports_what_is_unsettled_and_raises_nothing(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Decisions"}).json()["id"])
        self._seed(factory, project)

        response = client.post(
            f"/v1/projects/{project}/model/decisions/runs", json={"idempotency_key": "first"}
        )

        assert response.status_code == 200, response.text
        report = response.json()
        assert report["considered"] == 2
        assert [decision["settled"] for decision in report["decisions"]] == [False, False]
        # The statement travels with the reason: "nobody accepted it" reads the
        # same for every row, so reasons alone would name nothing.
        assert [note["statement"] for note in report["awaiting"]] == [
            "Local-first execution is the canonical environment."
        ]
        assert len(report["session_scoped"]) == 1
        assert client.get(f"/v1/projects/{project}/attention").json() == []

    def test_the_decisions_are_read_as_the_model_they_are_stored_as(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Decisions read"}).json()["id"])
        self._seed(factory, project)

        client.post(f"/v1/projects/{project}/model/decisions/runs", json={})

        listed = client.get(f"/v1/projects/{project}/model", params={"domain": "decision"})
        assert listed.status_code == 200
        assert len(listed.json()) == 2
        assert {obj["lifecycle"] for obj in listed.json()} == {"working"}

    def test_an_unknown_project_is_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/model/decisions/runs",
            json={},
        )

        assert response.status_code == 404


class TestAssumptionsAreProducedOverHttpAndSeparateRatherThanFilter:
    """`SYN-5d`. The run route is the only new surface: the beliefs are read
    through `GET /model?domain=assumption`, because there is no assumption table
    (`D-136`)."""

    _SCAFFOLDING = "KAE is the name of the system under discussion."
    _BELIEF = "Local disk is an acceptable source of repositories."

    def _seed(self, factory: sessionmaker[Session], project_id: str) -> None:
        memory = MemoryService(factory)
        run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "extract-assumptions")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(kind="assumption", content=statement, source="interview")
                for statement in (self._BELIEF, self._SCAFFOLDING)
            ],
        )

    def test_the_scaffolding_row_crosses_the_wire_named_rather_than_dropped(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        """A silent filter is indistinguishable from an extractor that never
        produced the row, which is doc 05's complaint."""

        project = str(client.post("/v1/projects", json={"name": "Assumptions"}).json()["id"])
        self._seed(factory, project)

        response = client.post(
            f"/v1/projects/{project}/model/assumptions/runs", json={"idempotency_key": "first"}
        )

        assert response.status_code == 200, response.text
        report = response.json()
        assert report["considered"] == 2
        assert [note["statement"] for note in report["scaffolding"]] == [self._SCAFFOLDING]
        assert [item["statement"] for item in report["assumptions"]] == [self._BELIEF]
        assert report["assumptions"][0]["consequence"] == "architecture"
        assert report["assumptions"][0]["needs_validation"] is True

    def test_a_material_assumption_is_reported_and_interrupts_nobody(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Assumptions queue"}).json()["id"])
        self._seed(factory, project)

        report = client.post(f"/v1/projects/{project}/model/assumptions/runs", json={}).json()

        assert [note["statement"] for note in report["needing_validation"]] == [self._BELIEF]
        assert client.get(f"/v1/projects/{project}/attention").json() == []

    def test_the_beliefs_are_read_as_the_model_they_are_stored_as(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Assumptions read"}).json()["id"])
        self._seed(factory, project)

        client.post(f"/v1/projects/{project}/model/assumptions/runs", json={})

        listed = client.get(f"/v1/projects/{project}/model", params={"domain": "assumption"})
        assert listed.status_code == 200
        assert [obj["statement"] for obj in listed.json()] == [self._BELIEF]
        assert {obj["lifecycle"] for obj in listed.json()} == {"working"}

    def test_an_unknown_project_is_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/model/assumptions/runs",
            json={},
        )

        assert response.status_code == 404


class TestConstraintsAreProducedOverHttpAndOnlyAcceptanceWrites:
    """`SYN-5e`. The run route is the only new surface: the boundaries are read
    through `GET /model?domain=constraint`, and the effects an accepted one
    imposes are the run's own output (`D-126`)."""

    def _seed(self, factory: sessionmaker[Session], project_id: str, *, accept: bool) -> None:
        memory = MemoryService(factory)
        run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "extract-constraints")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="constraint", content="Team collaboration is outside MVP.", source="i"
                ),
                WriteKnowledgeRequest(
                    kind="unknown", content="Is team collaboration in MVP?", source="i"
                ),
            ],
        )
        if accept:
            memory.confirm_knowledge(written[0].id)

    def test_an_unaccepted_boundary_sends_what_it_would_do_and_applies_none_of_it(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Constraints"}).json()["id"])
        self._seed(factory, project, accept=False)

        response = client.post(
            f"/v1/projects/{project}/model/constraints/runs", json={"idempotency_key": "first"}
        )

        assert response.status_code == 200, response.text
        report = response.json()
        assert report["considered"] == 1
        assert report["open_items"] == 1
        assert report["effects"] == []
        # The item travels with the constraint across the wire: a reason alone
        # would not name the question that would have been closed.
        assert [effect["item_statement"] for effect in report["proposed_effects"]] == [
            "Is team collaboration in MVP?"
        ]
        assert client.get(f"/v1/projects/{project}/attention").json() == []

    def test_an_accepted_boundary_applies_its_effect(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Accepted"}).json()["id"])
        self._seed(factory, project, accept=True)

        response = client.post(f"/v1/projects/{project}/model/constraints/runs", json={})

        assert response.status_code == 200, response.text
        report = response.json()
        assert report["proposed_effects"] == []
        assert [effect["kind"] for effect in report["effects"]] == ["resolves"]

        listed = client.get(f"/v1/projects/{project}/model", params={"domain": "constraint"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1

    def test_an_unknown_project_is_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/model/constraints/runs",
            json={},
        )

        assert response.status_code == 404


class TestRequirementsAreProducedOverHttpAndOnlyAPersonWritesCriteria:
    """`SYN-5b`. Three surfaces: the run, the criterion a person adds, and the
    criteria a reader lists. The requirements themselves are read through
    `GET /model?domain=requirement` (`D-131`)."""

    def _seed(self, factory: sessionmaker[Session], project_id: str, *, accept: bool) -> None:
        memory = MemoryService(factory)
        run = memory.start_run(
            ProjectId(project_id), AgentRole.REQUIREMENTS, "extract-requirements"
        )
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="requirement",
                    content="Original source notes must be preserved.",
                    source="i",
                )
            ],
        )
        if accept:
            memory.confirm_knowledge(written[0].id)

    def test_a_run_reports_a_requirement_that_nothing_can_be_built_to_yet(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Requirements"}).json()["id"])
        self._seed(factory, project, accept=True)

        response = client.post(
            f"/v1/projects/{project}/model/requirements/runs", json={"idempotency_key": "first"}
        )

        assert response.status_code == 200, response.text
        report = response.json()
        assert report["considered"] == 1
        assert report["implementation_ready"] == 0
        assert report["requirements"][0]["criteria"] == []
        assert report["requirements"][0]["accepted"] is True
        assert client.get(f"/v1/projects/{project}/attention").json() == []

    def test_a_person_adds_the_criterion_and_the_requirement_becomes_ready(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        project = str(client.post("/v1/projects", json={"name": "Ready"}).json()["id"])
        self._seed(factory, project, accept=True)
        first = client.post(f"/v1/projects/{project}/model/requirements/runs", json={}).json()
        object_id = first["requirements"][0]["synthesized_object_id"]

        added = client.post(
            f"/v1/projects/{project}/model/requirements/{object_id}/criteria",
            json={"statement": "A note is retrievable after the item it backs is updated."},
        )

        assert added.status_code == 201, added.text
        listed = client.get(f"/v1/projects/{project}/model/requirements/criteria")
        assert [one["requirement_object_id"] for one in listed.json()] == [object_id]

        second = client.post(
            f"/v1/projects/{project}/model/requirements/runs", json={"idempotency_key": "second"}
        ).json()
        assert second["implementation_ready"] == 1

    def test_a_criterion_against_something_that_is_not_a_requirement_is_refused(
        self, client: TestClient, project: str
    ) -> None:
        """The route is the only way into the table, so it is the only place
        that can keep a criterion off an actor or a constraint."""

        created = client.post(
            f"/v1/projects/{project}/model",
            json={
                "domain": "constraint",
                "identity_key": "collaboration outside mvp",
                "title": "Team collaboration is outside MVP.",
                "statement": "Team collaboration is outside MVP.",
            },
        )
        assert created.status_code in (200, 201), created.text
        object_id = created.json()["id"]

        response = client.post(
            f"/v1/projects/{project}/model/requirements/{object_id}/criteria",
            json={"statement": "Something is observable."},
        )

        assert response.status_code == 404

    def test_an_unknown_project_is_not_found(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/model/requirements/runs",
            json={},
        )

        assert response.status_code == 404


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
