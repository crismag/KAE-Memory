"""`SYN-5f` — proposal versus authoritative choice, and what may never become either.

The subject is doc 08's stated failure: an item that is `proposed, not
confirmed` and `to decide` at the same time. These assert that the two states
cannot coexist here, that only a person's confirmation ends a decision, and that
a session-scoped choice is refused permanence rather than dropped.
"""

from __future__ import annotations

import pytest
from tests.synthesis.corpus import AREA_SUFFICIENT_TEXT

from kae_memory.domain.synthesis import Authority, SynthesizedLifecycle, SynthesizedObject
from kae_memory.domain.synthesizers.decisions import (
    DecisionCandidate,
    DecisionClass,
    DecisionModelPlan,
    EffectiveScope,
    area_declared_sufficient,
    class_of,
    plan_decision_model,
    scope_of,
)


def _candidate(statement: str, *, confirmed: bool = False) -> DecisionCandidate:
    return DecisionCandidate(
        members=(statement,),
        canonical_key=statement,
        statement=statement,
        confirmed_by_person=confirmed,
    )


def _plan(*statements: str, **kwargs: object) -> DecisionModelPlan:
    return plan_decision_model([_candidate(statement) for statement in statements], **kwargs)  # type: ignore[arg-type]


class TestOnlyAPersonSettlesADecision:
    """Doc 08: an accepted decision is an authoritative project choice."""

    def test_unconfirmed_evidence_stays_the_working_model_reading(self) -> None:
        plan = _plan("Use PostgreSQL as the production database.")
        assert plan.decisions[0].lifecycle is SynthesizedLifecycle.WORKING
        assert plan.decisions[0].authority is Authority.WORKING_MODEL

    def test_confirmed_evidence_becomes_authoritative_with_human_authority(self) -> None:
        plan = plan_decision_model([_candidate("Ship without collaboration.", confirmed=True)])
        assert plan.decisions[0].lifecycle is SynthesizedLifecycle.AUTHORITATIVE
        assert plan.decisions[0].authority is Authority.HUMAN

    def test_wording_that_claims_a_decision_happened_does_not_promote_it(self) -> None:
        """`D-123`: the flag is necessary and the sentence is never sufficient."""

        plan = _plan(
            "We decided to use PostgreSQL.",
            "It is agreed and settled that the runtime is local.",
        )
        assert [decision.lifecycle for decision in plan.decisions] == [
            SynthesizedLifecycle.WORKING,
            SynthesizedLifecycle.WORKING,
        ]

    def test_a_planned_authoritative_decision_is_a_legal_synthesized_object(self) -> None:
        """The promotion rule is enforced below this module, so the plan must satisfy it."""

        planned = plan_decision_model(
            [_candidate("Ship without collaboration.", confirmed=True)]
        ).decisions[0]
        obj = SynthesizedObject(
            id=None,  # type: ignore[arg-type]
            project_id=None,  # type: ignore[arg-type]
            domain="decision",
            identity_key=planned.candidate.canonical_key,
            title=planned.candidate.statement,
            statement=planned.candidate.statement,
            lifecycle=planned.lifecycle,
            authority=planned.authority,
        )
        assert obj.lifecycle is SynthesizedLifecycle.AUTHORITATIVE


class TestProposedAndToDecideCannotCoexist:
    """Doc 08's current failure, made unrepresentable rather than corrected."""

    def test_a_settled_decision_asks_nobody_for_anything(self) -> None:
        plan = plan_decision_model([_candidate("Ship without collaboration.", confirmed=True)])
        assert plan.awaiting == ()

    def test_an_unsettled_decision_asks_exactly_once(self) -> None:
        plan = _plan("Use PostgreSQL as the production database.")
        assert len(plan.awaiting) == 1
        assert plan.awaiting[0][0] == "Use PostgreSQL as the production database."

    def test_awaiting_is_derived_from_the_lifecycle_and_never_disagrees_with_it(self) -> None:
        plan = _plan(
            "Use PostgreSQL as the production database.",
            "In this session, skip architecture and stay on requirements.",
        )
        asked = {statement for statement, _ in plan.awaiting}
        working = {
            decision.candidate.statement
            for decision in plan.decisions
            if decision.lifecycle is SynthesizedLifecycle.WORKING
            and decision.scope is EffectiveScope.PROJECT
        }
        assert asked == working


class TestTemporaryDoesNotBecomeGovernance:
    """Doc 08: *"temporary workflow decisions should not silently become permanent."*"""

    def test_a_session_decision_is_never_authoritative_even_when_confirmed(self) -> None:
        statement = "In this session, skip architecture and stay on requirements."
        plan = plan_decision_model([_candidate(statement, confirmed=True)])
        assert plan.decisions[0].scope is EffectiveScope.SESSION
        assert plan.decisions[0].lifecycle is SynthesizedLifecycle.WORKING
        assert plan.decisions[0].authority is Authority.WORKING_MODEL

    def test_the_refusal_is_reported_rather_than_dropped(self) -> None:
        statement = "For now, review requirements before architecture."
        plan = _plan(statement)
        assert [reported for reported, _ in plan.session_scoped] == [statement]
        assert plan.decisions[0].scope is EffectiveScope.SESSION

    def test_a_session_decision_does_not_occupy_the_queue(self) -> None:
        plan = _plan("For now, review requirements before architecture.")
        assert plan.awaiting == ()

    def test_scope_is_read_from_the_wording(self) -> None:
        assert scope_of("Temporarily accept the slower path.") is EffectiveScope.SESSION
        assert scope_of("Accept the slower path.") is EffectiveScope.PROJECT


class TestTheClassPrefersTheReadingThatClaimsLess:
    """`D-123`: manufacturing governance is the failure; understating it is not."""

    def test_a_session_instruction_naming_architecture_is_a_workflow_decision(self) -> None:
        assert (
            class_of("In this session, skip architecture and stay on requirements.")
            is DecisionClass.WORKFLOW
        )

    def test_a_process_instruction_is_not_read_as_authority(self) -> None:
        assert class_of("Use Confirm or Reject on each extracted candidate.") is (
            DecisionClass.WORKFLOW
        )

    def test_a_statement_about_how_the_system_runs_is_architecture(self) -> None:
        assert class_of("Local-first execution is the canonical environment.") is (
            DecisionClass.ARCHITECTURE
        )

    def test_a_statement_about_who_may_decide_is_governance(self) -> None:
        assert class_of("Only the project owner may override an accepted choice.") is (
            DecisionClass.GOVERNANCE
        )

    def test_a_decision_naming_no_subject_is_unclassified_rather_than_guessed(self) -> None:
        assert class_of("Yes, do that one.") is DecisionClass.UNCLASSIFIED


class TestAreaSufficiencyIsCheckedAgainstTheProjectState:
    """Doc 08's `conflicting-state` case, and the corpus row that carries it."""

    def test_the_corpus_declaration_names_its_area(self) -> None:
        assert area_declared_sufficient(AREA_SUFFICIENT_TEXT) == "problem_and_value"

    def test_sufficiency_alone_names_nothing(self) -> None:
        assert area_declared_sufficient("This is good enough.") is None

    def test_naming_an_area_without_declaring_it_sufficient_names_nothing(self) -> None:
        assert area_declared_sufficient("Problem and value needs more work.") is None

    def test_an_accepted_sufficiency_over_open_candidates_is_a_conflict(self) -> None:
        plan = plan_decision_model(
            [_candidate(AREA_SUFFICIENT_TEXT, confirmed=True)],
            {"problem_and_value": 47},
        )
        assert len(plan.conflicts) == 1
        assert "47 undecided candidates" in plan.conflicts[0][1]

    def test_the_same_declaration_over_a_settled_area_is_not_a_conflict(self) -> None:
        plan = plan_decision_model(
            [_candidate(AREA_SUFFICIENT_TEXT, confirmed=True)],
            {"problem_and_value": 0},
        )
        assert plan.conflicts == ()

    def test_an_unaccepted_sufficiency_claim_is_a_proposal_and_not_a_conflict(self) -> None:
        """Nothing was contradicted, because nothing was accepted."""

        plan = plan_decision_model([_candidate(AREA_SUFFICIENT_TEXT)], {"problem_and_value": 47})
        assert plan.conflicts == ()
        assert len(plan.awaiting) == 1


class TestTheCorpusDecisionsPlanCoherently:
    """The four golden-corpus decisions, planned together."""

    @pytest.fixture
    def plan(self) -> DecisionModelPlan:
        return plan_decision_model(
            [
                _candidate(AREA_SUFFICIENT_TEXT, confirmed=True),
                _candidate("Use Confirm or Reject on each extracted candidate."),
                _candidate("In this session, skip architecture and stay on requirements."),
                _candidate("Local-first execution is the canonical environment."),
            ],
            {"problem_and_value": 47},
        )

    def test_every_decision_is_kept(self, plan: DecisionModelPlan) -> None:
        assert len(plan.decisions) == 4

    def test_exactly_one_is_the_projects_own_choice(self, plan: DecisionModelPlan) -> None:
        settled = [
            decision
            for decision in plan.decisions
            if decision.lifecycle is SynthesizedLifecycle.AUTHORITATIVE
        ]
        assert [decision.candidate.statement for decision in settled] == [AREA_SUFFICIENT_TEXT]

    def test_two_ask_for_a_decision_and_the_session_one_does_not(
        self, plan: DecisionModelPlan
    ) -> None:
        assert {statement for statement, _ in plan.awaiting} == {
            "Use Confirm or Reject on each extracted candidate.",
            "Local-first execution is the canonical environment.",
        }

    def test_nothing_is_both_asked_about_and_conflicting(self, plan: DecisionModelPlan) -> None:
        asked = {statement for statement, _ in plan.awaiting}
        conflicting = {statement for statement, _ in plan.conflicts}
        assert asked.isdisjoint(conflicting)
