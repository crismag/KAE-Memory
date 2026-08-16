"""`SYN-5a` — the responsibility relation, and the invariants doc 03 states.

The subject of these tests is not *are the labels nice*. It is that the four
invariants `03-ACTORS-STAKEHOLDERS.md` writes as prose are enforced by code:
Accountable is human, at most one Accountable per subject, a role with no
responsibility is a persona, and an unassigned cell is written nowhere.
"""

from __future__ import annotations

from kae_memory.domain.area_classification import areas_named_by, classify_by_content
from kae_memory.domain.synthesizers.actors import (
    Responsibility,
    RoleCandidate,
    RoleKind,
    RoleModelPlan,
    kind_of,
    letter_of,
    plan_role_model,
    subject_of,
)


def _candidate(statement: str) -> RoleCandidate:
    return RoleCandidate(members=(statement,), canonical_key=statement, statement=statement)


def _plan(*statements: str) -> RoleModelPlan:
    return plan_role_model([_candidate(statement) for statement in statements])


class TestThePersonaSplitIsTheRelation:
    """Doc 03: *"a role with no responsibility anywhere is a persona."*

    `D-119` refused to build the taxonomy without the relation because this
    sentence is the discriminator. These assert it is implemented, not restated.
    """

    def test_a_description_that_owns_an_area_is_a_project_role(self) -> None:
        plan = _plan("The person who approves the deployment runbook")
        ((_, kind),) = plan.roles
        assert kind is RoleKind.PROJECT_ROLE
        assert len(plan.assignments) == 1

    def test_the_same_person_noun_owning_nothing_is_a_persona(self) -> None:
        plan = _plan("A person who likes the product")
        ((_, kind),) = plan.roles
        assert kind is RoleKind.PERSONA
        assert plan.assignments == ()

    def test_docs_three_named_personas_are_personas(self) -> None:
        """The three doc 03 names in its own text, all owning nothing."""

        plan = _plan("First-time founder", "Aspiring developer", "Experienced developer")
        assert [kind for _, kind in plan.roles] == [RoleKind.PERSONA] * 3


class TestAccountableIsAlwaysHuman:
    """Invariant 1 — the governance line, stated structurally."""

    def test_an_ai_claiming_authority_is_recorded_as_doing_the_work(self) -> None:
        plan = _plan("An AI agent that approves the deployment runbook")
        ((_, kind),) = plan.roles
        assert kind is RoleKind.AI_ROLE
        (assignment,) = plan.assignments
        assert assignment.letter is Responsibility.RESPONSIBLE

    def test_the_refused_claim_is_reported_rather_than_dropped(self) -> None:
        """Silently dropping it would hide that the evidence claimed authority."""

        plan = _plan("An AI agent that approves the deployment runbook")
        assert len(plan.downgraded) == 1
        assert "never Accountable" in plan.downgraded[0][1]

    def test_a_human_keeps_the_letter_the_wording_carries(self) -> None:
        plan = _plan("The person who approves the deployment runbook")
        (assignment,) = plan.assignments
        assert assignment.letter is Responsibility.ACCOUNTABLE


class TestAtMostOneAccountablePerSubject:
    """Invariant 2 — *"two accountable parties means nobody is."*"""

    def test_a_second_claimant_becomes_a_conflict_not_a_second_row(self) -> None:
        plan = _plan(
            "The owner who approves the deployment runbook",
            "The lead who approves the deployment runbook as well",
        )
        accountable = [
            assignment
            for assignment in plan.assignments
            if assignment.letter is Responsibility.ACCOUNTABLE
        ]
        assert len(accountable) == 1
        assert len(plan.conflicts) == 1

    def test_the_conflict_names_the_party_already_holding_it(self) -> None:
        plan = _plan(
            "The owner who approves the deployment runbook",
            "The lead who approves the deployment runbook as well",
        )
        assert "The owner who approves the deployment runbook" in plan.conflicts[0][1]


class TestAnUnassignedCellIsWrittenNowhere:
    """Invariant 5 — eighty empty cells surfaced as work is the flood in 2D."""

    def test_naming_no_area_writes_no_assignment(self) -> None:
        assert subject_of("Project owner") is None
        assert _plan("Project owner").assignments == ()

    def test_naming_no_letter_writes_no_assignment(self) -> None:
        assert letter_of("Somebody near the deployment") is None
        assert _plan("Somebody near the deployment").assignments == ()

    def test_two_areas_tied_is_a_refusal_not_a_coin_flip(self) -> None:
        tied = "Owner of the deployment and the API"
        assert areas_named_by(tied) == ("delivery_and_operations", "interfaces_and_integrations")
        assert subject_of(tied) is None
        assert _plan(tied).assignments == ()


class TestSystemsAndAiAreNotHumanStakeholders:
    """Doc 03 keeps three models and connects them; it does not flatten them."""

    def test_an_mcp_server_is_a_system(self) -> None:
        assert kind_of("GitHub MCP", holds_responsibility=False) is RoleKind.SYSTEM

    def test_a_bare_proper_noun_is_not_guessed_into_the_human_model(self) -> None:
        """`Ollama` names no function. The corpus tags it `ai-as-actor`; the
        wording supports neither that nor a human role, and inventing one would
        put a model provider in the responsibility model."""

        assert kind_of("Ollama", holds_responsibility=False) is RoleKind.UNCLASSIFIED

    def test_a_human_using_a_tool_is_still_a_human(self) -> None:
        """The AI marker is what the person *uses*, not what they are."""

        assert kind_of("A person using KAE", holds_responsibility=False) is RoleKind.PERSONA
        assert (
            kind_of("Administrator of credentials and providers", holds_responsibility=False)
            is RoleKind.PROJECT_ROLE
        )


class TestTheSubjectAxisIsScoredOverTheWholeTemplate:
    """`D-120` — the reason `classify_by_content` could not be used as it is."""

    def test_only_one_area_accepts_an_actor(self) -> None:
        placement = classify_by_content("actor", "Operator of the local deployment")
        assert placement is not None
        assert placement.area_key == "users_and_stakeholders"

    def test_but_the_wording_names_a_different_area_entirely(self) -> None:
        """Every role would own `users_and_stakeholders` — the flattening again."""

        assert subject_of("Operator of the local deployment") == "delivery_and_operations"


class TestAcceptanceCriteriaIsNotAnActOfAccepting:
    """Found by probing the corpus before this landed.

    ``accept\\w*`` matched *acceptance criteria*, so the tester who verifies
    them was read as holding decision authority over them.
    """

    def test_a_tester_verifies_and_does_not_approve(self) -> None:
        assert letter_of("Tester who validates acceptance criteria") is Responsibility.RESPONSIBLE

    def test_a_person_accepting_something_still_reads_as_authority(self) -> None:
        assert letter_of("The user accepting consequential decisions") is Responsibility.ACCOUNTABLE
