"""A deliverable reproduces the claim it made, not only the bytes (N20.2).

N20.1 pinned the statements and the render inputs, which makes a package
re-render identically. That is not enough to reproduce what it *said*. A package
generated with two open questions and an unaccepted assumption rested on
guesswork; the identical bytes, read after those were settled, read as a settled
document. Nothing recorded the difference.

The property under test is the one the register states: **historical
reproduction never consults current knowledge.** So every assertion here follows
the same shape — record a deliverable, then change the world, then read the
deliverable back and require it to be unmoved.

What is deliberately *not* asserted is that a pre-N20.2 record becomes
unpublishable. It can still be re-rendered byte for byte, and withdrawing that
would be a capability lost to a bookkeeping change.
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
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.assumptions import AssumptionOrigin, Consequence
from kae_memory.domain.dispositions import Disposition
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import MessageId, ProjectId
from kae_memory.domain.models import KnowledgeKind

CANDIDATE = "Captured thoughts are stored as markdown files."


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    ReadinessService(factory).install_template()
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project_id(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Sparse Inbox"}).json()["id"])


def _propose(factory: sessionmaker[Session], project_id: str) -> str:
    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "n202-propose")
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, CANDIDATE, "seed")]
    )
    ReadinessService(factory).assign_area(
        ProjectId(project_id), written[0].id, "constraints_and_assumptions"
    )
    return str(written[0].id)


def _assume(factory: sessionmaker[Session], project_id: str) -> str:
    return str(
        AssumptionService(factory)
        .record(
            ProjectId(project_id),
            subject="storage",
            assumed_value="markdown files on local disk",
            reason="a prototype needs no database",
            origin=AssumptionOrigin.KAE_INFERRED,
            consequence=Consequence.REWORK,
        )
        .id
    )


def _record(client: TestClient, project_id: str, **body: Any) -> dict[str, Any]:
    body.setdefault("include_proposed", True)
    response = client.post(f"/v1/projects/{project_id}/deliverables", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _message_count(factory: sessionmaker[Session], project_id: str) -> int:
    with factory() as session:
        return int(
            session.execute(
                text("SELECT count(*) FROM messages WHERE project_id = :p"),
                {"p": project_id},
            ).scalar_one()
        )


def _read(client: TestClient, project_id: str, deliverable_id: str) -> dict[str, Any]:
    response = client.get(f"/v1/projects/{project_id}/deliverables/{deliverable_id}")
    assert response.status_code == 200, response.text
    return dict(response.json())


class TestTheUncertaintyIsCaptured:
    def test_a_recorded_deliverable_carries_its_provisional_context(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """The gap N20.1 left. Every deliverable shipped with this field null,
        which is the same "exists with no caller" failure this repository has
        now hit three times — so the constructor lives in the service rather
        than in each adapter."""

        _propose(factory, project_id)

        body = _record(client, project_id)

        assert body["provisional_context"] is not None
        assert body["reproduces_uncertainty"] is True

    def test_it_records_the_confirmation_split(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _propose(factory, project_id)

        body = _record(client, project_id)

        assert body["provisional_context"]["proposed"] == 1
        assert body["provisional_context"]["confirmed"] == 0

    def test_it_pins_the_assumption_at_the_state_it_was_in(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A package resting on a guess nobody had taken responsibility for is
        a weaker claim than the same package after someone accepted it."""

        assumption_id = _assume(factory, project_id)
        _propose(factory, project_id)

        body = _record(client, project_id)

        pins = {
            p["assumption_id"]: p["state"] for p in body["provisional_context"]["assumption_pins"]
        }
        assert pins[assumption_id] == "proposed"

    def test_it_pins_the_open_questions(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _propose(factory, project_id)

        body = _record(client, project_id)

        assert body["provisional_context"]["question_pins"]

    def test_it_says_it_rested_on_uncertainty(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _propose(factory, project_id)

        body = _record(client, project_id)

        assert body["rested_on_uncertainty"] is True


class TestReproductionNeverConsultsCurrentKnowledge:
    def test_accepting_the_assumption_later_does_not_change_the_record(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """The acceptance criterion, stated as an event. A record that reported
        "accepted" here would be saying the package rested on something firmer
        than it did."""

        assumption_id = _assume(factory, project_id)
        _propose(factory, project_id)
        recorded = _record(client, project_id)

        AssumptionService(factory).accept(ProjectId(project_id), assumption_id, actor="cris")

        body = _read(client, project_id, recorded["deliverable_id"])
        pins = {
            p["assumption_id"]: p["state"] for p in body["provisional_context"]["assumption_pins"]
        }
        assert pins[assumption_id] == "proposed"

    def test_answering_a_question_later_does_not_change_the_record(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """The question is asked explicitly first, which it did not used to be.

        This test previously answered a pin that recording the deliverable had
        materialised — generation created the question, and the test then
        replied to it. D-13 ends that: describing a project's uncertainty is a
        read. So the setup now does what a person does, and asks.
        """

        _propose(factory, project_id)
        asked = client.post(f"/v1/projects/{project_id}/clarifications", params={"limit": 1})
        question_id = asked.json()["questions"][0]["clarification_id"]

        recorded = _record(client, project_id)
        pinned = recorded["provisional_context"]["question_pins"]
        assert question_id in [p["clarification_id"] for p in pinned]

        ClarificationService(factory).answer(
            ProjectId(project_id),
            MessageId(question_id),
            "Markdown files on disk.",
        )

        body = _read(client, project_id, recorded["deliverable_id"])
        assert body["provisional_context"]["question_pins"] == pinned

    def test_an_unasked_question_is_pinned_by_its_candidate_key(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Two kinds of unknown, and the record distinguishes them.

        A package generated while nobody had been asked rested on something
        different from one generated after somebody said "I don't know yet".
        Before D-13 both looked identical in the record, because generating the
        package asked the question — so every pin was a message id and the
        never-asked case could not arise.
        """

        _propose(factory, project_id)

        body = _record(client, project_id)

        pins = body["provisional_context"]["question_pins"]
        assert pins
        assert all(pin["clarification_id"].startswith("question:") for pin in pins)
        assert all(pin["disposition"] == "open" for pin in pins)

    def test_recording_a_deliverable_asks_nobody_anything(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """D-13's invariant, at the boundary that broke it worst.

        A deliverable's provisional context reads the project's uncertainty in
        order to describe it. Describing must not create it — otherwise a
        package's own provenance manufactures the records it cites, and which
        id a question carries depends on whether anybody generated a package.
        """

        _propose(factory, project_id)
        before = _message_count(factory, project_id)

        _record(client, project_id)
        _record(client, project_id)

        assert _message_count(factory, project_id) == before

    def test_a_deferred_question_is_pinned_with_its_disposition(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A question someone could not answer is part of what the package
        rested on. It is held back from the asking list, not from the record
        (N36)."""

        _propose(factory, project_id)
        listed = client.post(
            f"/v1/projects/{project_id}/clarifications", params={"limit": 1}
        ).json()
        question_id = listed["questions"][0]["clarification_id"]
        ClarificationService(factory).answer(
            ProjectId(project_id),
            MessageId(question_id),
            "I don't know yet.",
            disposition=Disposition.UNKNOWN_BY_USER,
        )

        body = _record(client, project_id)

        pins = {
            p["clarification_id"]: p["disposition"]
            for p in body["provisional_context"]["question_pins"]
        }
        assert pins[question_id] == "unknown_by_user"

    def test_confirming_knowledge_later_does_not_change_the_split(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """The clearest form of the failure: a package that was almost entirely
        unconfirmed would otherwise read, a week later, as one that was not."""

        knowledge_id = _propose(factory, project_id)
        recorded = _record(client, project_id)

        MemoryService(factory).confirm_knowledge(
            next(
                item.id
                for item in MemoryService(factory).retrieve_knowledge(
                    ProjectId(project_id), lifecycle=None
                )
                if str(item.id) == knowledge_id
            )
        )

        body = _read(client, project_id, recorded["deliverable_id"])
        assert body["provisional_context"]["proposed"] == 1
        assert body["provisional_context"]["confirmed"] == 0


class TestAnImprovedPackageIsANewDeliverable:
    def test_recording_after_confirmation_mints_a_new_identity(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Never overwrites an old identity. The old record keeps saying what it
        said, which is the only reason it is worth keeping."""

        knowledge_id = _propose(factory, project_id)
        first = _record(client, project_id)

        memory = MemoryService(factory)
        memory.confirm_knowledge(
            next(
                item.id
                for item in memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
                if str(item.id) == knowledge_id
            )
        )
        second = _record(client, project_id)

        assert second["deliverable_id"] != first["deliverable_id"]
        assert (
            _read(client, project_id, first["deliverable_id"])["provisional_context"]["confirmed"]
            == 0
        )


class TestByteReproductionIsNotWithdrawn:
    def test_capturing_uncertainty_is_reported_apart_from_eligibility(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Two different questions: can this be re-rendered identically, and can
        it say how much of itself was guesswork. Folding the second into the
        first would make a bookkeeping change look like a rendering failure."""

        _propose(factory, project_id)

        body = _record(client, project_id)

        assert body["publication_eligible"] is True
        assert body["reproduces_uncertainty"] is True
        assert body["uncertainty_gap_reason"] is None
