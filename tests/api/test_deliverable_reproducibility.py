"""Pinned render inputs, and what happens without them (N20.1).

N20 recorded `source_knowledge` as identifiers. Assembly reads
`current_version`, so a corrected statement changes what a re-render produces
while those identifiers stay the same — the deliverable would appear
reproducible and would not be.

Knowledge versions are immutable and append-only, which is what makes a pinned
`(knowledge_id, version)` a promise rather than a hope: the version a pin names
still exists, unchanged, however far the statement has moved since.

Statements are not the only input. Purpose, proposed-inclusion, ordering
contract, generator version, package schema, and — for module scope — the graph
that decided what the scope contained all change the output, and an input that
is not recorded cannot be reproduced.

Two rules the tests hold hardest:

    the artifact hashes remain the final proof — eligibility only says the
    inputs exist to attempt reproduction;

    nothing is fabricated for a legacy record. It stays readable and is
    explicitly publication-ineligible, because a guessed pin would make an
    unprovable claim look proven.
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
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.deliverables import (
    LEGACY_INELIGIBLE,
    ORDERING_CONTRACT,
    PINS_MISSING,
    ArtifactRecord,
    Deliverable,
    DeliverableId,
    RenderInputs,
    StatementPin,
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


def _seed(factory: sessionmaker[Session], project_id: str, text_value: str) -> str:
    """Confirmed and area-assigned, because unassigned knowledge assembles to nothing.

    A deliverable over an empty assembly would pass every assertion here
    vacuously, which is the quiet way a reproducibility test proves nothing.
    """

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, f"n201-{len(text_value)}")
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, text_value, "seed")]
    )
    item = written[0]
    readiness.assign_area(ProjectId(project_id), item.id, "constraints_and_assumptions")
    memory.confirm_knowledge(item.id)
    return str(item.id)


def _propose(factory: sessionmaker[Session], project_id: str, text_value: str) -> str:
    """A candidate: area-assigned so it can be assembled, and left unconfirmed."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, f"prop-{len(text_value)}")
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, text_value, "seed")]
    )
    readiness.assign_area(ProjectId(project_id), written[0].id, "constraints_and_assumptions")
    return str(written[0].id)


def _record(client: TestClient, project_id: str, **body: Any) -> dict[str, Any]:
    response = client.post(f"/v1/projects/{project_id}/deliverables", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestPinsArePromises:
    def test_a_pin_names_a_version_not_only_a_statement(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        knowledge_id = _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        pins = {pin["knowledge_id"]: pin["version"] for pin in body["statement_pins"]}
        assert knowledge_id in pins
        assert pins[knowledge_id] >= 1

    def test_a_pin_survives_a_later_correction(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """The property the whole target rests on.

        Versions are append-only, so the version a pin names still exists after
        the statement moves on. Without the pin, the identifier would resolve to
        the new wording and the deliverable would silently mean something else.
        """

        knowledge_id = _seed(factory, project_id, "A report must be approved.")
        recorded = _record(client, project_id)
        pinned = next(
            pin["version"]
            for pin in recorded["statement_pins"]
            if pin["knowledge_id"] == knowledge_id
        )

        memory = MemoryService(factory)
        item = memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)[0]
        memory.review_correct(
            ProjectId(project_id),
            item.id,
            expected_version=item.current_version.number,
            content="A report must be approved by the board before publication.",
            actor_id="cris",
        )

        after = client.get(
            f"/v1/projects/{project_id}/deliverables/{recorded['deliverable_id']}"
        ).json()
        current = memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)[0]

        assert after["statement_pins"] == recorded["statement_pins"]
        assert current.current_version.number > pinned, "the statement moved"
        assert after["content_hash"] == recorded["content_hash"], "the record did not"

    def test_a_pin_refuses_a_version_that_is_not_one(self) -> None:
        with pytest.raises(DomainInvariantError):
            StatementPin(knowledge_id="k1", version=0)

    def test_a_pin_needs_a_statement(self) -> None:
        with pytest.raises(DomainInvariantError):
            StatementPin(knowledge_id="  ", version=1)


class TestEveryRenderInputIsCaptured:
    def test_the_inputs_that_change_output_are_recorded(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")

        inputs = _record(client, project_id)["render_inputs"]

        assert set(inputs) >= {
            "purpose",
            "scope",
            "include_proposed",
            "ordering_contract",
            "generator_version",
            "package_schema",
            "knowledge_revision",
        }
        assert inputs["ordering_contract"] == ORDERING_CONTRACT

    def test_include_proposed_is_part_of_the_record(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """It changes what is assembled, so it changes the output — when there
        is something proposed to include.

        With nothing proposed, both settings assemble the same statements and
        produce the same content, so they are **one** deliverable recorded
        twice. That is identity working as designed: a flag that changed
        nothing did not make a second output.
        """

        _seed(factory, project_id, "A report must be approved.")
        _propose(factory, project_id, "Retention may be seven years.")

        without = _record(client, project_id, include_proposed=False)
        with_proposed = _record(client, project_id, include_proposed=True)

        assert without["deliverable_id"] != with_proposed["deliverable_id"]
        assert without["render_inputs"]["include_proposed"] is False
        assert with_proposed["render_inputs"]["include_proposed"] is True
        assert len(with_proposed["statement_pins"]) > len(without["statement_pins"])

    def test_structural_fingerprint_is_absent_rather_than_empty_for_project_scope(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """ "No structure involved" and "structure not captured" differ."""

        _seed(factory, project_id, "A report must be approved.")

        inputs = _record(client, project_id)["render_inputs"]

        assert inputs["structural_fingerprint"] is None
        assert inputs["module_key"] is None

    def test_a_partial_input_set_is_treated_as_absent(self) -> None:
        """Reproduction needs every input; a subset would claim more than it has."""

        assert RenderInputs.from_dict({"purpose": "implementation"}) is None
        assert RenderInputs.from_dict({}) is None


class TestEligibility:
    def test_a_newly_recorded_deliverable_is_eligible(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        assert body["publication_eligible"] is True
        assert body["ineligibility_reason"] is None

    def test_eligibility_needs_inputs_and_pins_for_what_was_rendered(self) -> None:
        """Corrected by manual testing.

        The first rule was `pins AND inputs`, which marked an **empty** package
        unprovable — it has nothing to pin and is trivially reproducible, since
        rendering nothing twice produces nothing twice. The rule conflated "we
        did not capture the pins" with "there was nothing to pin".

        What is genuinely unprovable is a package that rendered artifacts and
        pinned none of them.
        """

        base: dict[str, Any] = {
            "id": DeliverableId("d1"),
            "project_id": ProjectId("p1"),
            "purpose": "implementation",
            "scope": "project",
            "knowledge_revision": 3,
            "content_hash": "sha256:abc",
        }
        inputs = RenderInputs(
            purpose="implementation",
            scope="project",
            include_proposed=False,
            ordering_contract=ORDERING_CONTRACT,
            generator_version="1.0.0",
            package_schema="kae.package.v1",
            knowledge_revision=3,
        )
        artifact = ArtifactRecord(
            path="requirements.md",
            area_key="functional_requirements",
            title="Requirements",
            statement_count=1,
            confirmed_count=1,
            content_hash="sha256:def",
        )

        empty = Deliverable(**base, artifacts=(), render_inputs=inputs)
        unpinned = Deliverable(**base, artifacts=(artifact,), render_inputs=inputs)
        pinned = Deliverable(
            **base,
            artifacts=(artifact,),
            statement_pins=(StatementPin("k1", 1),),
            render_inputs=inputs,
        )
        legacy = Deliverable(**base, artifacts=(artifact,))

        assert empty.publication_eligible is True, "nothing to pin, and reproducible"
        assert unpinned.publication_eligible is False
        assert pinned.publication_eligible is True
        assert legacy.publication_eligible is False

    def test_the_two_ineligible_causes_have_two_reasons(self) -> None:
        """A reason that is only usually true is a reason nobody can act on.

        Reporting an un-pinned deliverable as predating N20.1 sent a reader
        looking for a migration problem that did not exist.
        """

        base: dict[str, Any] = {
            "id": DeliverableId("d1"),
            "project_id": ProjectId("p1"),
            "purpose": "implementation",
            "scope": "project",
            "knowledge_revision": 3,
            "content_hash": "sha256:abc",
            "artifacts": (ArtifactRecord("a.md", "area", "A", 1, 1, "sha256:def"),),
        }
        inputs = RenderInputs(
            purpose="implementation",
            scope="project",
            include_proposed=False,
            ordering_contract=ORDERING_CONTRACT,
            generator_version="1.0.0",
            package_schema="kae.package.v1",
            knowledge_revision=3,
        )

        assert Deliverable(**base).ineligibility_reason == LEGACY_INELIGIBLE
        assert Deliverable(**base, render_inputs=inputs).ineligibility_reason == PINS_MISSING

    def test_the_hash_remains_the_final_proof(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Eligibility says the inputs exist; only the hash says it worked."""

        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        assert body["publication_eligible"] is True
        assert body["content_hash"].startswith("sha256:")
        for artifact in body["artifacts"]:
            assert artifact["content_hash"]


class TestLegacyRecordsAreReadableAndRefused:
    """Nothing is fabricated. A guessed pin would make an unprovable claim proven."""

    def _legacy(self, client: TestClient, factory: sessionmaker[Session], project_id: str) -> str:
        """Record normally, then strip what a pre-N20.1 row would not have had."""

        deliverable_id = _record(client, project_id)["deliverable_id"]
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

    def test_a_legacy_deliverable_is_still_readable(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """What it was and when is still true, and still worth keeping."""

        _seed(factory, project_id, "A report must be approved.")
        legacy = self._legacy(client, factory, project_id)

        response = client.get(f"/v1/projects/{project_id}/deliverables/{legacy}")

        assert response.status_code == 200
        assert response.json()["content_hash"]
        assert response.json()["artifacts"] is not None

    def test_it_is_explicitly_publication_ineligible(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")
        legacy = self._legacy(client, factory, project_id)

        body = client.get(f"/v1/projects/{project_id}/deliverables/{legacy}").json()

        assert body["publication_eligible"] is False
        assert body["ineligibility_reason"] == LEGACY_INELIGIBLE

    def test_the_reason_says_what_is_missing_and_why_it_matters(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """ "Ineligible" alone leaves a caller unable to act or to trust it."""

        _seed(factory, project_id, "A report must be approved.")
        legacy = self._legacy(client, factory, project_id)

        reason = client.get(f"/v1/projects/{project_id}/deliverables/{legacy}").json()[
            "ineligibility_reason"
        ]

        assert "cannot be proven" in reason
        assert "different content" in reason

    def test_nothing_was_invented_to_fill_the_gap(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed(factory, project_id, "A report must be approved.")
        legacy = self._legacy(client, factory, project_id)

        body = client.get(f"/v1/projects/{project_id}/deliverables/{legacy}").json()

        assert body["statement_pins"] == []
        assert body["render_inputs"] is None


class TestTheMigrationDoesNotBackfill:
    # `test_the_column_defaults_to_ineligible` lived here. It asserted that
    # `publication_eligible` defaulted to false so a legacy row could not claim
    # provability it did not have. Revision 0018 removed the column — the fact
    # it protected is now structural rather than defaulted, because a value
    # derived from the render inputs cannot disagree with them.
    # `TestEligibilityHasOneSourceOfTruth` holds what remains.

    def test_the_pin_columns_are_nullable(self, factory: sessionmaker[Session]) -> None:
        """A row that cannot have them must be allowed not to."""

        with factory() as session:
            rows = session.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'deliverables' "
                    "AND column_name IN ('statement_pins', 'render_inputs')"
                )
            ).all()
            nullable = {str(row[0]): str(row[1]) for row in rows}

        assert nullable == {"statement_pins": "YES", "render_inputs": "YES"}


class TestQualificationSortsGapsByWhatTheyAre:
    """Found by manual testing: every gap was being called a contradiction.

    A project with no knowledge reported four contradictions — with nothing to
    disagree with itself. A missing area is an absence; calling it a conflict
    sends a reader looking for two sources that never existed.
    """

    def test_an_empty_project_reports_zero_contradictions(
        self, client: TestClient, project_id: str
    ) -> None:
        """The regression this class exists for.

        Nothing is recorded, so nothing can contradict anything.
        """

        qualification = _record(client, project_id)["qualification"]

        assert qualification["contradictions"] == []

    def test_missing_areas_are_limitations_not_contradictions(
        self, client: TestClient, project_id: str
    ) -> None:
        qualification = _record(client, project_id)["qualification"]

        limitations = " ".join(qualification["limitations"])
        assert "no confirmed knowledge" in limitations.lower()
        assert qualification["contradictions"] == []

    def test_the_three_buckets_stay_separate(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Disagreement, unresolved choice, and absence answer different
        questions and need different remedies."""

        _seed(factory, project_id, "A report must be approved.")

        qualification = _record(client, project_id)["qualification"]

        assert isinstance(qualification["contradictions"], list)
        assert isinstance(qualification["open_decisions"], list)
        assert isinstance(qualification["limitations"], list)
        assert not set(qualification["contradictions"]) & set(qualification["limitations"])

    def test_an_unrecognised_gap_kind_understates_rather_than_inventing_conflict(
        self,
    ) -> None:
        """Exhaustive by exclusion, deliberately.

        A finding kind added later lands in limitations, which understates it,
        rather than in contradictions, which would invent a conflict that does
        not exist.
        """

        from kae_memory.application.deliverable_service import _sort_gaps

        class _Gap:
            def __init__(self, kind: str, summary: str) -> None:
                self.kind = kind
                self.summary = summary

        contradictions, decisions, absences = _sort_gaps(
            [
                _Gap("unresolved_contradiction", "two sources disagree"),
                _Gap("open_question", "who approves"),
                _Gap("missing_area", "nothing here yet"),
                _Gap("a_kind_invented_next_year", "unknown"),
            ]
        )

        assert contradictions == ("two sources disagree",)
        assert decisions == ("who approves",)
        assert absences == ("nothing here yet", "unknown")


class TestEligibilityHasOneSourceOfTruth:
    def test_the_stored_column_is_gone(self, factory: sessionmaker[Session]) -> None:
        """Written and read by nothing, and it drifted within a day.

        A pre-fix row held `false` while the derived property reported `true`,
        so the table and the API disagreed about one deliverable.
        """

        from kae_memory.persistence.tables import DeliverableRow

        assert "publication_eligible" not in DeliverableRow.__table__.columns

    def test_eligibility_is_still_reported(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """Removing the column must not remove the answer."""

        _seed(factory, project_id, "A report must be approved.")

        body = _record(client, project_id)

        assert body["publication_eligible"] is True
        assert body["ineligibility_reason"] is None
