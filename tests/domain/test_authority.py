"""What a source can establish, per claim scope — and what it deliberately cannot.

`EPI-2`, doc 17, `D-148`. The table itself and the two scopes no knowledge kind
can reach. What the rule does inside reconciliation is
`tests/domain/test_conflict_direction.py`.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.authority import (
    ClaimScope,
    SourceStanding,
    best_standing,
    scope_of,
    standing,
    standing_rank,
)
from kae_memory.domain.models import KnowledgeKind, KnowledgeSourceType


class TestScopeComesFromTheKindAndNotTheWording:
    def test_a_decision_claims_a_project_decision(self) -> None:
        assert scope_of(KnowledgeKind.DECISION.value) is ClaimScope.PROJECT_DECISION

    def test_a_rule_and_a_constraint_both_claim_policy(self) -> None:
        assert scope_of(KnowledgeKind.RULE.value) is ClaimScope.NORMATIVE_POLICY
        assert scope_of(KnowledgeKind.CONSTRAINT.value) is ClaimScope.NORMATIVE_POLICY

    def test_a_goal_and_a_requirement_both_claim_intended_behaviour(self) -> None:
        assert scope_of(KnowledgeKind.GOAL.value) is ClaimScope.INTENDED_BEHAVIOUR
        assert scope_of(KnowledgeKind.REQUIREMENT.value) is ClaimScope.INTENDED_BEHAVIOUR

    @pytest.mark.parametrize(
        "kind",
        [KnowledgeKind.ACTOR, KnowledgeKind.ASSUMPTION, KnowledgeKind.UNKNOWN],
    )
    def test_a_kind_that_claims_nothing_has_no_scope(self, kind: KnowledgeKind) -> None:
        """A participant, a provisional belief and a question assert nothing a
        source could be authoritative about, so they get no scope rather than a
        scope nobody meant."""

        assert scope_of(kind.value) is None

    def test_an_unrecognised_kind_claims_nothing_rather_than_raising(self) -> None:
        """A new kind must not make the conflict path an outage."""

        assert scope_of("telemetry") is None

    def test_the_same_wording_cannot_change_the_scope(self) -> None:
        """`scope_of` takes no statement, so this is the signature and not a rule.

        Kept as a test because `D-129`, `D-131` and `D-132` each needed one, and
        a later hand adding a text argument would pass everything else.
        """

        assert scope_of.__code__.co_varnames[: scope_of.__code__.co_argcount] == ("kind",)


class TestTwoScopesAreUnreachableAndThatIsTheFinding:
    def test_no_kind_claims_current_implementation(self) -> None:
        """No knowledge kind says *what the system does today* (`D-148`).

        So the one row where `REPOSITORY` is the authoritative source can never
        be selected, and the fix is a kind vocabulary question rather than a
        table to widen here.
        """

        reached = {scope_of(kind.value) for kind in KnowledgeKind}
        assert ClaimScope.CURRENT_IMPLEMENTATION not in reached

    def test_no_kind_claims_an_external_reference(self) -> None:
        reached = {scope_of(kind.value) for kind in KnowledgeKind}
        assert ClaimScope.EXTERNAL_REFERENCE not in reached

    def test_both_unreachable_scopes_still_have_a_table_row(self) -> None:
        """A vocabulary that omitted them would hide the gap instead of naming it."""

        for scope in (ClaimScope.CURRENT_IMPLEMENTATION, ClaimScope.EXTERNAL_REFERENCE):
            standings = {standing(source, scope) for source in KnowledgeSourceType}
            assert SourceStanding.AUTHORITATIVE in standings


class TestWhatEachSourceCanEstablish:
    def test_a_repository_settles_what_is_deployed_and_not_what_is_intended(self) -> None:
        """Doc 17's headline example, both halves."""

        assert (
            standing(KnowledgeSourceType.REPOSITORY, ClaimScope.CURRENT_IMPLEMENTATION)
            is SourceStanding.AUTHORITATIVE
        )
        assert (
            standing(KnowledgeSourceType.REPOSITORY, ClaimScope.INTENDED_BEHAVIOUR)
            is SourceStanding.INFORMATIVE
        )

    def test_a_person_settles_intent_decisions_and_policy(self) -> None:
        for scope in (
            ClaimScope.INTENDED_BEHAVIOUR,
            ClaimScope.PROJECT_DECISION,
            ClaimScope.NORMATIVE_POLICY,
        ):
            assert standing(KnowledgeSourceType.USER_STATEMENT, scope) is (
                SourceStanding.AUTHORITATIVE
            )

    def test_a_person_does_not_settle_what_the_code_does(self) -> None:
        assert (
            standing(KnowledgeSourceType.USER_STATEMENT, ClaimScope.CURRENT_IMPLEMENTATION)
            is SourceStanding.INFORMATIVE
        )

    def test_an_imported_document_settles_only_that_it_is_an_external_reference(self) -> None:
        """`D-148`: doc 17's document examples turn on document *type*, and
        `KnowledgeSourceType` has one member for an ADR, a BRD and a meeting
        note. Claiming more here would be inventing the distinction."""

        assert (
            standing(KnowledgeSourceType.IMPORTED_DOCUMENT, ClaimScope.EXTERNAL_REFERENCE)
            is SourceStanding.AUTHORITATIVE
        )
        for scope in (
            ClaimScope.CURRENT_IMPLEMENTATION,
            ClaimScope.INTENDED_BEHAVIOUR,
            ClaimScope.NORMATIVE_POLICY,
            ClaimScope.PROJECT_DECISION,
        ):
            assert standing(KnowledgeSourceType.IMPORTED_DOCUMENT, scope) is (
                SourceStanding.INFORMATIVE
            )

    def test_kae_generated_text_establishes_nothing_anywhere(self) -> None:
        """Doc 17 verbatim: no independent authority merely because KAE wrote it."""

        for scope in ClaimScope:
            assert standing(KnowledgeSourceType.KAE_INFERENCE, scope) is SourceStanding.NONE


class TestARowStandsOnItsStrongestSource:
    def test_the_owner_outweighs_a_weaker_second_source(self) -> None:
        both = frozenset({KnowledgeSourceType.REPOSITORY, KnowledgeSourceType.USER_STATEMENT})
        assert best_standing(both, ClaimScope.PROJECT_DECISION) is SourceStanding.AUTHORITATIVE

    def test_inference_beside_a_real_source_does_not_weaken_it(self) -> None:
        both = frozenset({KnowledgeSourceType.KAE_INFERENCE, KnowledgeSourceType.REPOSITORY})
        assert best_standing(both, ClaimScope.PROJECT_DECISION) is SourceStanding.INFORMATIVE

    def test_no_recorded_source_establishes_nothing(self) -> None:
        """`EPI-5b`: provenance that says nothing grounds nothing. Not informative."""

        assert best_standing(frozenset(), ClaimScope.PROJECT_DECISION) is SourceStanding.NONE

    def test_the_ranking_orders_the_three(self) -> None:
        ordered = sorted(SourceStanding, key=standing_rank)
        assert ordered == [
            SourceStanding.NONE,
            SourceStanding.INFORMATIVE,
            SourceStanding.AUTHORITATIVE,
        ]
