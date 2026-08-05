"""Assumptions as durable records (N35).

`StatementLabel.ASSUMPTION` was a label on an assembled statement. A label
cannot be pinned, disclosed, accepted, revisited, or reversed — it lives as long
as the payload that carried it. So a package generated from thin knowledge
disclosed its assumptions once, to whoever read that response, and then forgot
them.

The rule everything here protects:

    a material assumption is never silently promoted to a confirmed requirement.

FR-005 already says a person confirms what becomes project knowledge. An
assumption that could quietly become one would route around that rule while
looking like a convenience — so the enforcement is structural rather than
procedural, and the last test in this file is the one that checks it.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.assumption_service import (
    AssumptionNotFoundError,
    AssumptionService,
)
from kae_memory.domain.assumptions import (
    MATERIAL,
    Assumption,
    AssumptionId,
    AssumptionOrigin,
    AssumptionState,
    Consequence,
    InvalidAssumptionTransitionError,
    RevisitTrigger,
    disclosure,
    ensure_assumption_transition,
)
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import ProjectId


def _assumption(**overrides: object) -> Assumption:
    fields: dict[str, object] = {
        "id": AssumptionId("a1"),
        "project_id": ProjectId("p1"),
        "subject": "tenancy",
        "assumed_value": "single tenant",
        "reason": "no requirement mentions more than one organisation",
        "origin": AssumptionOrigin.KAE_INFERRED,
    }
    fields.update(overrides)
    return Assumption(**fields)  # type: ignore[arg-type]


class TestAnAssumptionMustBeJudgeable:
    def test_it_must_say_why(self) -> None:
        """An unjudgeable assumption is a guess with a record attached."""

        with pytest.raises(DomainInvariantError, match="why it was made"):
            _assumption(reason="  ")

    def test_it_must_name_the_gap_it_covers(self) -> None:
        with pytest.raises(DomainInvariantError, match="name the gap"):
            _assumption(subject="")

    def test_it_must_state_what_was_assumed(self) -> None:
        with pytest.raises(DomainInvariantError, match="what it assumed"):
            _assumption(assumed_value="")

    def test_confidence_is_a_probability(self) -> None:
        with pytest.raises(DomainInvariantError, match="probability"):
            _assumption(confidence=1.4)


class TestMateriality:
    def test_architectural_and_unsafe_are_material(self) -> None:
        """ "We assumed PostgreSQL" and "we assumed single-tenant" are not the
        same risk, and a list treating them alike buries the second."""

        assert {Consequence.ARCHITECTURAL, Consequence.UNSAFE} == MATERIAL

    def test_an_irreversible_assumption_is_material_whatever_its_consequence(self) -> None:
        assert _assumption(reversible=False, consequence=Consequence.COSMETIC).material is True

    def test_a_material_assumption_cannot_be_never_revisit(self) -> None:
        """How a prototype default becomes a production commitment."""

        with pytest.raises(DomainInvariantError, match="never-revisit"):
            _assumption(consequence=Consequence.ARCHITECTURAL, revisit=RevisitTrigger.NEVER)

    def test_a_cosmetic_reversible_assumption_may_never_be_revisited(self) -> None:
        assert _assumption(consequence=Consequence.COSMETIC, revisit=RevisitTrigger.NEVER)


class TestAcceptanceNamesSomeone:
    def test_an_accepted_assumption_names_who_accepted_it(self) -> None:
        """Responsibility nobody is named for is none."""

        with pytest.raises(DomainInvariantError, match="who accepted it"):
            _assumption(state=AssumptionState.ACCEPTED)

    def test_naming_the_actor_is_enough(self) -> None:
        assert _assumption(state=AssumptionState.ACCEPTED, accepted_by="cris").is_active


class TestTransitions:
    def test_a_proposal_can_be_accepted_rejected_or_superseded(self) -> None:
        for target in (
            AssumptionState.ACCEPTED,
            AssumptionState.REJECTED,
            AssumptionState.SUPERSEDED,
        ):
            ensure_assumption_transition(AssumptionState.PROPOSED, target)

    def test_an_accepted_assumption_can_be_retired(self) -> None:
        """The healthy end: the gap it covered was answered."""

        ensure_assumption_transition(AssumptionState.ACCEPTED, AssumptionState.RETIRED)

    def test_terminal_states_are_terminal(self) -> None:
        for state in (
            AssumptionState.REJECTED,
            AssumptionState.SUPERSEDED,
            AssumptionState.RETIRED,
        ):
            with pytest.raises(InvalidAssumptionTransitionError):
                ensure_assumption_transition(state, AssumptionState.ACCEPTED)


class TestDisclosure:
    def test_it_carries_the_consequence(self) -> None:
        """ "We assumed single-tenant" invites a nod. Adding the consequence
        invites a decision."""

        line = disclosure(_assumption(consequence=Consequence.ARCHITECTURAL))

        assert "single tenant" in line
        assert "architectural" in line
        assert "no requirement mentions" in line

    def test_it_names_who_accepted_when_someone_did(self) -> None:
        line = disclosure(_assumption(state=AssumptionState.ACCEPTED, accepted_by="cris"))

        assert "accepted by cris" in line


class TestAgainstTheDatabase:
    @pytest.fixture
    def service(self, factory: sessionmaker[Session]) -> AssumptionService:
        return AssumptionService(factory)

    @pytest.fixture
    def project_id(self, factory: sessionmaker[Session]) -> ProjectId:
        return MemoryService(factory).create_project("Sparse", key="n35-sparse").id

    def test_a_recorded_assumption_is_proposed_whoever_asked(
        self, service: AssumptionService, project_id: ProjectId
    ) -> None:
        """A caller that could record one already accepted would be recording a
        decision nobody made."""

        recorded = service.record(
            project_id, "tenancy", "single tenant", "nothing mentions more than one org"
        )

        assert recorded.state is AssumptionState.PROPOSED
        assert recorded.accepted_by is None

    def test_acceptance_requires_an_actor(
        self, service: AssumptionService, project_id: ProjectId
    ) -> None:
        recorded = service.record(project_id, "tenancy", "single tenant", "no evidence otherwise")

        with pytest.raises(ValueError, match="actor is required"):
            service.accept(project_id, str(recorded.id), "  ")

    def test_acceptance_records_who(
        self, service: AssumptionService, project_id: ProjectId
    ) -> None:
        recorded = service.record(project_id, "tenancy", "single tenant", "no evidence otherwise")

        accepted = service.accept(project_id, str(recorded.id), "cris")

        assert accepted.state is AssumptionState.ACCEPTED
        assert accepted.accepted_by == "cris"

    def test_retiring_is_distinct_from_rejecting(
        self, service: AssumptionService, project_id: ProjectId
    ) -> None:
        """Retired means the question was settled; rejected means the guess was
        wrong. A reader needs to tell those apart."""

        first = service.record(project_id, "db", "postgres", "the repo already uses it")
        second = service.record(project_id, "cache", "none", "no latency requirement exists")
        service.accept(project_id, str(first.id), "cris")

        retired = service.retire(project_id, str(first.id))
        rejected = service.reject(project_id, str(second.id), "cris")

        assert retired.state is AssumptionState.RETIRED
        assert rejected.state is AssumptionState.REJECTED

    def test_listing_defaults_to_what_is_still_live(
        self, service: AssumptionService, project_id: ProjectId
    ) -> None:
        live = service.record(project_id, "db", "postgres", "the repo already uses it")
        dead = service.record(project_id, "cache", "none", "no latency requirement exists")
        service.reject(project_id, str(dead.id), "cris")

        active = service.list_for_project(project_id)
        everything = service.list_for_project(project_id, active_only=False)

        assert [str(a.id) for a in active] == [str(live.id)]
        assert len(everything) == 2

    def test_another_projects_assumption_is_not_reachable(
        self, factory: sessionmaker[Session], service: AssumptionService, project_id: ProjectId
    ) -> None:
        recorded = service.record(project_id, "tenancy", "single tenant", "no evidence otherwise")
        other = MemoryService(factory).create_project("Other", key="n35-other").id

        with pytest.raises(AssumptionNotFoundError):
            service.accept(other, str(recorded.id), "cris")


class TestPromotionIsStructurallyImpossible:
    """The rule this model exists for, checked where it can actually be enforced."""

    def test_the_service_imports_nothing_that_writes_knowledge(self) -> None:
        """Procedural rules get worked around; structural ones do not.

        Checked against the module namespace rather than its text, because the
        text includes prose that names what it must not import — and a test
        that reads its own explanation is a test that fails for the wrong
        reason.

        Someone asked to "just promote accepted assumptions" would have to add
        a dependency first, which is a visible change rather than a quiet one.
        """

        from kae_memory.application import assumption_service

        imported = {
            name for name, value in vars(assumption_service).items() if not name.startswith("__")
        }

        assert "MemoryService" not in imported
        assert "KnowledgeItem" not in imported
        assert not [name for name in imported if "knowledge" in name.lower()]

    def test_the_service_exposes_no_way_to_confirm(self) -> None:
        """Accepted is a person proceeding on a guess. Confirmed is a person
        saying it is true. One service offering both would eventually be asked
        to blur them."""

        operations = {name for name in dir(AssumptionService) if not name.startswith("_")}

        assert not [name for name in operations if "confirm" in name]
        assert "accept" in operations

    def test_assumptions_are_their_own_table(self) -> None:
        """One table would put the forbidden promotion a single UPDATE away."""

        from kae_memory.persistence.tables import AssumptionRow, KnowledgeItemRow

        assert AssumptionRow.__tablename__ != KnowledgeItemRow.__tablename__
        assert AssumptionRow.__tablename__ == "assumptions"

    def test_accepted_is_the_furthest_an_assumption_goes(self) -> None:
        """There is no state meaning "became knowledge", deliberately."""

        assert {state.value for state in AssumptionState} == {
            "proposed",
            "accepted",
            "rejected",
            "superseded",
            "retired",
        }
