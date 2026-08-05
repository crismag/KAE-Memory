"""A sparse project travelling the whole pipeline (thin vertical proof).

Every subsystem below is unit- and contract-tested. None of them had ever met.
1,235 tests proved each piece and nothing proved the seams, and the risk a suite
like that hides is not a broken part — it is six correct parts that disagree
about what they hand each other.

The journey, deliberately without publication:

    sparse project -> current knowledge -> assemble -> record deliverable
    -> verify reproduction and publication eligibility

What it exists to prove is the product principle rather than the plumbing:

    sparse knowledge is valid input;
    proposed knowledge participates when the generation policy allows it;
    missing information produces qualifications, not global failure;
    the user may accept the current knowledge boundary as sufficient;
    assembly and recording work with no publication target at all;
    only reproduction, integrity, and publication are blocked, each for its
    own reason and without spreading.

**This file is meant to be extended, not replaced.** N20.2 and N36 add stages
to the same journey; a second integration fixture would let the two drift and
would double the cost of every future change to the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.capability_readiness_service import CapabilityReadinessService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.acquisition import CapabilityState
from kae_memory.domain.assumptions import AssumptionOrigin, Consequence, RevisitTrigger
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind

IDEA = "Build a simple personal inbox that turns thoughts into organized tasks."


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def sparse_project(client: TestClient, factory: sessionmaker[Session]) -> str:
    """A project with one idea's worth of unconfirmed knowledge.

    Deliberately minimal and deliberately *unconfirmed*: two statements nobody
    has ruled on, which is what a project looks like ten minutes after someone
    described what they want.
    """

    ReadinessService(factory).install_template()
    project_id = str(client.post("/v1/projects", json={"name": "Personal inbox"}).json()["id"])

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "thin-proof")
    written = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                KnowledgeKind.CONSTRAINT.value,
                "A thought is captured in one step, without choosing a project first.",
                "interview",
            ),
            WriteKnowledgeRequest(
                KnowledgeKind.CONSTRAINT.value,
                "Nothing is deleted; completed items stay readable.",
                "interview",
            ),
        ],
    )
    for item in written:
        readiness.assign_area(ProjectId(project_id), item.id, "constraints_and_assumptions")
    return project_id


def _assemble(client: TestClient, project_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/v1/projects/{project_id}/context", params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestStageOneSparseKnowledgeIsValidInput:
    def test_the_project_exists_with_almost_nothing_in_it(
        self, client: TestClient, sparse_project: str
    ) -> None:
        readiness = client.get(f"/v1/projects/{sparse_project}/readiness").json()

        assert readiness["percentage"] < 40, "this proof is worthless on a mature project"

    def test_every_generative_capability_is_available(
        self, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """The principle, checked before anything is generated.

        A global readiness gate would fail here, which is exactly why this is
        the first assertion rather than a footnote.
        """

        report = CapabilityReadinessService(factory).report(ProjectId(sparse_project))

        assert report.permits("acquisition.continue")
        assert report.permits("knowledge.assemble")
        assert report.permits("deliverable.record")
        assert report.permits("deliverable.render")

    def test_thin_knowledge_warns_rather_than_refuses(
        self, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        entry = (
            CapabilityReadinessService(factory)
            .report(ProjectId(sparse_project))
            .for_capability("knowledge.assemble")
        )

        assert entry is not None
        assert entry.state is CapabilityState.AVAILABLE_WITH_WARNINGS
        assert entry.permitted is True


class TestStageTwoMissingInformationBecomesAnAssumption:
    def test_a_gap_is_recorded_rather_than_raised(
        self, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """The alternative to an assumption is a question nobody answered and a
        blank space nobody noticed."""

        assumption = AssumptionService(factory).record(
            ProjectId(sparse_project),
            subject="tenancy",
            assumed_value="single user",
            reason="nothing in the idea mentions sharing or more than one person",
            origin=AssumptionOrigin.KAE_INFERRED,
            consequence=Consequence.ARCHITECTURAL,
            revisit=RevisitTrigger.BEFORE_PRODUCTION,
        )

        assert assumption.material is True
        assert assumption.state.value == "proposed"

    def test_accepting_it_is_a_person_taking_responsibility(
        self, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        service = AssumptionService(factory)
        assumption = service.record(
            ProjectId(sparse_project),
            "storage",
            "a local database",
            "no deployment target has been discussed",
        )

        accepted = service.accept(ProjectId(sparse_project), str(assumption.id), "cris")

        assert accepted.accepted_by == "cris"
        assert accepted.state.value == "accepted"

    def test_an_assumption_never_becomes_knowledge(
        self, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """Checked across the seam, not only inside the service.

        Accepting an assumption must leave the knowledge count untouched — that
        is the promotion FR-005 forbids, and the place it would show up is
        here.
        """

        memory = MemoryService(factory)
        before = len(memory.retrieve_knowledge(ProjectId(sparse_project), lifecycle=None))

        service = AssumptionService(factory)
        assumption = service.record(
            ProjectId(sparse_project), "sync", "no sync in the first version", "not discussed"
        )
        service.accept(ProjectId(sparse_project), str(assumption.id), "cris")

        after = len(memory.retrieve_knowledge(ProjectId(sparse_project), lifecycle=None))
        assert after == before


class TestStageThreeAssemblyAcceptsUnconfirmedKnowledge:
    def test_confirmed_only_assembly_is_honest_about_being_empty(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """Nothing is confirmed yet, so nothing confirmed assembles.

        Empty is the correct answer and is not a failure — the response says so
        rather than erroring.
        """

        assembled = _assemble(client, sparse_project)

        assert assembled["manifest"]["statement_count"] == 0
        assert assembled["manifest"]["warnings"]

    def test_proposed_knowledge_participates_when_the_policy_allows_it(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """The generation policy decides, not the confirmation state."""

        assembled = _assemble(client, sparse_project, include_proposed=True)

        assert assembled["manifest"]["statement_count"] > 0
        assert assembled["manifest"]["confirmation_state"]["proposed"] > 0
        assert assembled["manifest"]["confirmation_state"]["confirmed"] == 0

    def test_every_statement_still_declares_what_it_is(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """Permissive about inclusion, strict about labelling.

        An implementer who cannot tell a candidate from a decision builds
        whichever they read first.
        """

        assembled = _assemble(client, sparse_project, include_proposed=True)

        for section in assembled["sections"]:
            for statement in section["statements"]:
                assert statement["lifecycle"]
                assert statement["label"]

    def test_the_gaps_travel_with_the_output(self, client: TestClient, sparse_project: str) -> None:
        assembled = _assemble(client, sparse_project, include_proposed=True)

        assert "unresolved_critical_gaps" in assembled["manifest"]
        joined = " ".join(assembled["guidance"]).lower()
        assert "candidates" in joined or "proposed" in joined


class TestStageFourRecordingNeedsNoPublicationTarget:
    def test_a_deliverable_records_from_sparse_proposed_knowledge(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """The seam this proof exists for: assembly to durable identity."""

        response = client.post(
            f"/v1/projects/{sparse_project}/deliverables",
            json={"include_proposed": True, "recorded_by": "cris"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["recorded"] is True

    def test_no_publication_target_exists_and_recording_did_not_care(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """Recording and publishing are different acts with different
        prerequisites, and only one of them is available in this version."""

        client.post(f"/v1/projects/{sparse_project}/deliverables", json={"include_proposed": True})

        report = CapabilityReadinessService(factory).report(ProjectId(sparse_project))
        publish = report.for_capability("deliverable.publish")

        assert publish is not None
        assert publish.state is CapabilityState.UNSUPPORTED
        assert report.permits("deliverable.record") is True

    def test_the_user_may_accept_this_knowledge_boundary(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """ "Generate now" with two unconfirmed statements and one open
        assumption is a legitimate request, and the record shows what was
        accepted rather than pretending the project was complete.
        """

        recorded = client.post(
            f"/v1/projects/{sparse_project}/deliverables",
            json={"include_proposed": True, "recorded_by": "cris"},
        ).json()

        assert recorded["recorded_by"] == "cris"
        assert recorded["render_inputs"]["include_proposed"] is True
        assert recorded["manifest"]["confirmation_state"]["confirmed"] == 0


class TestStageFiveReproductionIsProvable:
    def _record(self, client: TestClient, project_id: str) -> dict[str, Any]:
        return dict(
            client.post(
                f"/v1/projects/{project_id}/deliverables",
                json={"include_proposed": True, "recorded_by": "cris"},
            ).json()
        )

    def test_a_provisional_deliverable_is_publication_eligible(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """Provisional is about evidence, not permission.

        A package built from two unconfirmed statements is still exactly
        reproducible, which is the only thing eligibility claims.
        """

        recorded = self._record(client, sparse_project)

        assert recorded["publication_eligible"] is True
        assert recorded["ineligibility_reason"] is None
        assert recorded["statement_pins"]

    def test_the_pins_survive_the_project_moving_on(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """Acquisition continues after generation, and the earlier package does
        not quietly change meaning."""

        recorded = self._record(client, sparse_project)

        memory = MemoryService(factory)
        item = memory.retrieve_knowledge(ProjectId(sparse_project), lifecycle=None)[0]
        memory.review_correct(
            ProjectId(sparse_project),
            item.id,
            expected_version=item.current_version.number,
            content="A thought is captured in one step, from anywhere.",
            actor_id="cris",
        )

        after = client.get(
            f"/v1/projects/{sparse_project}/deliverables/{recorded['deliverable_id']}"
        ).json()

        assert after["statement_pins"] == recorded["statement_pins"]
        assert after["content_hash"] == recorded["content_hash"]
        assert after["stale"] is True, "the project moved, and the record says so"

    def test_a_later_generation_is_a_new_deliverable(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """Progressive improvement without rewriting history."""

        first = self._record(client, sparse_project)

        memory = MemoryService(factory)
        readiness = ReadinessService(factory)
        run = memory.start_run(ProjectId(sparse_project), AgentRole.REQUIREMENTS, "thin-more")
        more = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    KnowledgeKind.CONSTRAINT.value, "Tasks carry a due date.", "interview"
                )
            ],
        )
        readiness.assign_area(ProjectId(sparse_project), more[0].id, "constraints_and_assumptions")

        second = self._record(client, sparse_project)

        assert second["deliverable_id"] != first["deliverable_id"]
        assert (
            client.get(
                f"/v1/projects/{sparse_project}/deliverables/{first['deliverable_id']}"
            ).json()["content_hash"]
            == first["content_hash"]
        )


class TestStageSixOnlyIntegrityBlocks:
    """The last claim: a block exists, is real, and does not spread."""

    def _unprovable(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> str:
        """A deliverable whose inputs cannot be proven, as a pre-N20.1 row was."""

        deliverable_id = client.post(
            f"/v1/projects/{project_id}/deliverables", json={"include_proposed": True}
        ).json()["deliverable_id"]
        with factory() as session:
            session.execute(
                text(
                    "UPDATE deliverables SET statement_pins = NULL, render_inputs = NULL, "
                    "publication_eligible = false WHERE deliverable_id = :id"
                ),
                {"id": deliverable_id},
            )
            session.commit()
        return str(deliverable_id)

    def test_an_unprovable_deliverable_is_refused_publication(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        unprovable = self._unprovable(client, factory, sparse_project)

        body = client.get(f"/v1/projects/{sparse_project}/deliverables/{unprovable}").json()

        assert body["publication_eligible"] is False
        assert "cannot be proven" in body["ineligibility_reason"]

    def test_it_stays_readable(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """What it was and when is still true, and still worth keeping."""

        unprovable = self._unprovable(client, factory, sparse_project)

        response = client.get(f"/v1/projects/{sparse_project}/deliverables/{unprovable}")

        assert response.status_code == 200
        assert response.json()["content_hash"]

    def test_the_integrity_block_does_not_spread(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """The claim a blocker must never make: that the project has failed.

        One unprovable historical record must leave acquisition, assembly, and
        recording exactly where they were.
        """

        self._unprovable(client, factory, sparse_project)

        report = CapabilityReadinessService(factory).report(ProjectId(sparse_project))

        assert report.permits("acquisition.continue") is True
        assert report.permits("knowledge.assemble") is True
        assert report.permits("deliverable.record") is True
        assert report.permits("deliverable.render") is True
        assert report.permits("deliverable.republish_historical") is False

    def test_the_block_names_its_reason_and_the_way_forward(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        self._unprovable(client, factory, sparse_project)

        entry = (
            CapabilityReadinessService(factory)
            .report(ProjectId(sparse_project))
            .for_capability("deliverable.republish_historical")
        )

        assert entry is not None
        assert entry.state is CapabilityState.BLOCKED_BY_INTEGRITY
        assert "record a new deliverable" in entry.next_action

    def test_a_fresh_deliverable_is_still_recordable_afterwards(
        self, client: TestClient, factory: sessionmaker[Session], sparse_project: str
    ) -> None:
        """The remedy the block points at actually works."""

        self._unprovable(client, factory, sparse_project)

        response = client.post(
            f"/v1/projects/{sparse_project}/deliverables",
            json={"include_proposed": True, "purpose": "discovery"},
        )

        assert response.status_code == 201
        assert response.json()["publication_eligible"] is True
