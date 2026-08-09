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
                    # Nulling the inputs is the whole story now: eligibility is
                    # derived from them, so there is no second field to keep in
                    # step (revision 0018).
                    "UPDATE deliverables SET statement_pins = NULL, "
                    "render_inputs = NULL WHERE deliverable_id = :id"
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


class TestTheHeartbeat:
    """Talk → KAE understands → the model changes → the change is visible.

    The loop the product *is*, walked without touching a service method by hand.
    A dogfooding session measured what happens when a link in it is missing: 42
    messages of genuine planning work, 178 accurate statements extracted, and a
    product reporting `0% · not_started` with all ten areas empty.

    Three links were broken and each was invisible from the others. Nothing
    triggered review, so knowledge was never assigned to an area. Nothing
    recalculated readiness, so the snapshot stayed at revision 0 of 25.
    Confirmation worked one item at a time, so a person's agreement to a
    synthesis had nothing to act on.

    This walks all three. It asserts the *loop*, not the parts: every subsystem
    below is covered elsewhere, and what was never covered is that they hand
    each other what the next one needs.
    """

    def test_a_message_becomes_visible_project_progress(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        from kae_memory.agents.deterministic import DeterministicExtractionAdapter
        from kae_memory.agents.review_adapter import DeterministicReviewAdapter
        from kae_memory.worker.execution import AgentStepExecutor
        from kae_memory.worker.runner import Worker, WorkerConfig

        ReadinessService(factory).install_template()
        project_id = str(client.post("/v1/projects", json={"name": "Heartbeat"}).json()["id"])
        session_id = client.post(
            f"/v1/projects/{project_id}/sessions", json={"session_type": "discovery"}
        ).json()["id"]

        # 1 · Someone says something about their project.
        client.post(
            f"/v1/sessions/{session_id}/messages",
            json={
                "content": (
                    "Ministry leaders submit monthly reports. Approval must happen "
                    "before publication, and reports are published within a week."
                )
            },
        )

        before = client.post(
            f"/v1/projects/{project_id}/readiness/calculate", json={}
        ).json()
        assert before["percentage"] == 0, "nothing has been derived yet"

        # 2 · The worker drains whatever that queued. Nothing here enqueues a
        # review: extraction asks for one itself once it is the last run
        # standing, which is the link whose absence produced 0%.
        # With a reviewer that classifies, which is what a deployment has
        # (`KAE_REVIEW=bedrock`).
        #
        # It has to be supplied here. `DeterministicReviewAdapter`'s bundled
        # fixture applies the same unambiguous-only rule as the offline path, so
        # it stands in for the *shipped fixture reviewer* rather than for a
        # model — and with it this test would prove only that the loop turns
        # without moving, which is the state it exists to rule out.
        #
        # Without any reviewer the loop still turns and readiness still cannot
        # move: only `actor` and `assumption` map to a single area, so ordinary
        # knowledge is declined. That is a property of the template rather than
        # of this corpus, and `TestTheOfflineClassifierIsStructurallyLimited`
        # below pins it.
        def judges(request: Any) -> object:
            """The judgement a model is for, faked by taking the first fit.

            Not a classifier anybody should ship: it reads the kind and ignores
            the statement. What it stands in for is only *that a decision was
            reached* — the part of the loop under test here.
            """

            from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

            findings = []
            for statement in request.statements:
                fits = [a.key for a in SOFTWARE_TEMPLATE.areas if statement.kind in a.kinds]
                if not fits:
                    continue  # `unknown` belongs to no area, which is correct
                findings.append(
                    {
                        "kind": "area_classification",
                        "statement_quote": statement.text,
                        "area_key": fits[0],
                        "confidence": "medium",
                        "rationale": "test stand-in for a model's judgement",
                    }
                )
            return {"findings": findings}

        worker = Worker(
            factory,
            AgentStepExecutor(
                factory, DeterministicExtractionAdapter(), DeterministicReviewAdapter(judges)
            ),
            WorkerConfig(worker_id="heartbeat", idle_poll_seconds=0.01),
        )
        for _ in range(8):
            if worker.run_once() is None:
                break

        runs = client.get(f"/v1/projects/{project_id}/runs").json()
        assert any(run["role"] == "review" for run in runs), (
            "extraction must ask for the review that assigns knowledge to areas"
        )

        # 3 · Readiness moved without anyone asking it to. The review run
        # recalculates, so the number a person sees describes the project as it
        # is rather than as it was before they spoke.
        current = client.get(f"/v1/projects/{project_id}/readiness").json()
        assert current["knowledge_revision"] == current["current_knowledge_revision"]
        assert not current["is_stale"]

        # 4 · A synthesis is agreed to in one act. This is what "yes, that
        # holds" does now — it used to have nothing to act on, so the
        # interviewer said "Confirmed" and the panel said "0 of 1 confirmed".
        proposed = client.get(
            f"/v1/projects/{project_id}/knowledge", params={"lifecycle": "proposed"}
        ).json()
        assert proposed, "the message should have produced candidate knowledge"

        confirmed = client.post(
            f"/v1/projects/{project_id}/knowledge/confirm",
            json={"item_ids": [item["id"] for item in proposed]},
        )
        assert confirmed.status_code == 200
        assert {item["lifecycle"] for item in confirmed.json()} == {"validated"}

        # 5 · And the project is visibly further along than it was.
        after = client.post(f"/v1/projects/{project_id}/readiness/calculate", json={}).json()
        assert after["percentage"] > before["percentage"], (
            "twenty minutes of real work must leave the product saying something changed"
        )


class TestTheOfflineClassifierIsStructurallyLimited:
    """Why a deployment reported two areas of ten, and why the number is exact.

    The register recorded that the shipped reviewer "classifies only where a
    knowledge kind leaves no choice", and inferred that eight of ten areas could
    never populate. The mechanism is sharper than that, and worth stating
    precisely because it decides whether the offline path is a degraded mode or
    no mode at all.

    Across `SOFTWARE_TEMPLATE`, exactly **two of eight knowledge kinds** map to a
    single area. Everything a planning conversation mostly produces — goals,
    requirements, rules, constraints, decisions — maps to between two and five,
    so the offline classifier declines all of it. Correctly: guessing would be
    worse. But it means a project without a review model does not get partial
    coverage, it gets coverage of two areas and only where those two kinds
    happen to appear.

    This is a fact about the template, not about any corpus. Rebalancing the
    template would change it, which is why the assertion names the kinds rather
    than counting them.
    """

    def test_only_actor_and_assumption_can_be_classified_without_a_model(self) -> None:
        from kae_memory.domain.models import KnowledgeKind
        from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

        unambiguous = {
            kind.value: [area.key for area in SOFTWARE_TEMPLATE.areas if kind in area.kinds]
            for kind in KnowledgeKind
        }
        single = {k: v[0] for k, v in unambiguous.items() if len(v) == 1}

        assert single == {
            "actor": "users_and_stakeholders",
            "assumption": "constraints_and_assumptions",
        }

    def test_the_kinds_a_planning_conversation_produces_are_all_ambiguous(self) -> None:
        """Which is why `KAE_REVIEW` is not optional for a real project.

        A conversation about what to build produces goals and requirements. If
        those cannot be classified, readiness describes a project by what it
        said about its users and its assumptions, and nothing else.
        """

        from kae_memory.domain.models import KnowledgeKind
        from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

        for kind in (KnowledgeKind.GOAL, KnowledgeKind.REQUIREMENT, KnowledgeKind.RULE):
            areas = [area.key for area in SOFTWARE_TEMPLATE.areas if kind in area.kinds]
            assert len(areas) > 1, f"{kind.value} would be classifiable offline"


class TestWhatTheTurnMachineryRecords:
    """The four slices built dispositions. This is what they leave behind.

    Every piece below is unit-tested where it lives. What was never checked is
    that the records they write mean, *together*, what the product claims: that
    KAE's advice stays distinguishable from what a person said, that a deferred
    question stays open, and that a material assumption is findable among the
    routine ones.

    This is as close to the replay test as can run without a deployment. It
    proves the mechanism, which is not the same as proving the product — the
    qualitative check still needs a person and a live system.
    """

    def test_accepted_advice_never_reads_as_something_the_customer_said(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """The distinction that makes advice safe to give.

        `kae_recommended_accepted` separates "KAE suggested this and I agreed"
        from "I said this". Without it, being opinionated would mean putting
        words in the customer's mouth — which is why R1 records recommendations
        as assumptions with a KAE origin and never as user-stated knowledge.
        """

        accepted = client.post(
            f"/v1/projects/{sparse_project}/assumptions",
            json={
                "origin": "kae_recommended_accepted",
                "subject": "scope_and_boundaries",
                "assumed_value": "Mobile is deferred to a second release",
                "reason": "KAE recommended it and the operator accepted",
                "consequence": "architectural",
                "revisit": "before_build",
            },
        )
        assert accepted.status_code == 201

        listed = client.get(f"/v1/projects/{sparse_project}/assumptions").json()
        origins = {entry["origin"] for entry in listed["assumptions"]}

        assert "kae_recommended_accepted" in origins
        assert "user_stated" not in origins, (
            "nothing on this path may claim the customer said it"
        )

    def test_a_material_assumption_is_findable_among_the_routine_ones(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """"A material assumption must be disclosed wherever the output it
        shaped is disclosed. Everything else may be summarised."

        The policy is only worth having if the two are distinguishable after the
        fact — a reader looking for what the project is quietly resting on has
        to be able to find it without reading everything.
        """

        for value, consequence in (
            ("Reports are weekly", "cosmetic"),
            ("Single tenant for the first release", "architectural"),
        ):
            client.post(
                f"/v1/projects/{sparse_project}/assumptions",
                json={
                    "subject": "scope_and_boundaries",
                    "assumed_value": value,
                    "reason": "concluded by KAE during a planning turn",
                    "consequence": consequence,
                    "revisit": "before_build",
                },
            )

        listed = client.get(f"/v1/projects/{sparse_project}/assumptions").json()
        material = [
            a for a in listed["assumptions"] if a["consequence"] in {"architectural", "unsafe"}
        ]

        assert [a["assumed_value"] for a in material] == ["Single tenant for the first release"]
        # The listing counts them itself, so a reader does not have to know
        # which consequences are material to ask "what is this resting on".
        assert listed["material_count"] == 1

    def test_every_assumption_says_when_it_should_be_looked_at_again(
        self, client: TestClient, sparse_project: str
    ) -> None:
        """A conclusion nobody revisits is a guess with tenure.

        `RevisitTrigger` is what separates a working assumption from a
        commitment nobody remembers making, and it only does that if it is
        actually recorded on the way in.
        """

        client.post(
            f"/v1/projects/{sparse_project}/assumptions",
            json={
                "subject": "scope_and_boundaries",
                "assumed_value": "Weekly cadence",
                "reason": "concluded by KAE during a planning turn",
                "consequence": "rework",
                "revisit": "before_build",
            },
        )

        listed = client.get(f"/v1/projects/{sparse_project}/assumptions").json()["assumptions"]

        assert listed
        assert all(entry["revisit"] for entry in listed), "an absent trigger means 'never'"

    def test_a_deferred_question_stays_open_and_an_answered_one_does_not(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        """The distinction the whole disposition vocabulary exists for.

        "I don't know yet, pick something reasonable" is a real answer that
        settles nothing. Recording it as answered closes a question nobody
        decided; recording nothing loses the instruction. Both were wrong, which
        is why `deferred` is not in SETTLES.

        And it is why Studio's "Bring back" sending `answered` was a defect
        rather than a shortcut: it closed the question it existed to reopen.
        """

        from kae_memory.domain.dispositions import Disposition, settles

        assert not settles(Disposition.DEFERRED), "a deferral leaves the question owed"
        assert not settles(Disposition.OPEN), "reopening cannot close"
        assert settles(Disposition.ANSWERED)
