"""`SYN-5e` — constraints as design forces, and what a boundary may not do.

Doc 07's subject is propagation: a boundary is worth having for what it settles.
These assert that an accepted constraint reaches the open items it speaks about,
that an unaccepted one reaches nothing, and that an effect is never a verdict.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.synthesizers.constraints import (
    ConstraintCandidate,
    ConstraintFamily,
    ConstraintModelPlan,
    Effect,
    EffectKind,
    OpenItem,
    family_of,
    is_boundary,
    plan_constraint_model,
    subject_terms,
)

COLLABORATION_OUTSIDE_MVP = "Team collaboration is outside MVP."
IS_COLLABORATION_IN_MVP = "Is team collaboration in MVP?"
COLLABORATION_CAN_WAIT = "Collaboration features can wait until after MVP."


def _candidate(statement: str, *, accepted: bool = False) -> ConstraintCandidate:
    return ConstraintCandidate(
        members=(statement,),
        canonical_key=statement,
        statement=statement,
        accepted=accepted,
    )


class TestOnlyAnAcceptedBoundaryPropagates:
    """Doc 07: *"Accepted constraints must influence the rest of the model."*"""

    def test_an_accepted_constraint_reaches_the_question_it_answers(self) -> None:
        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP, accepted=True)],
            [OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP)],
        )
        assert [effect.kind for effect in plan.effects] == [EffectKind.RESOLVES]

    def test_an_unaccepted_constraint_changes_nothing(self) -> None:
        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP)],
            [OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP)],
        )
        assert plan.effects == ()

    def test_but_what_it_would_settle_is_still_reported(self) -> None:
        """Hiding it would leave the evidence's claim with no argument for reading it."""

        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP)],
            [OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP)],
        )
        assert [effect.item_key for effect in plan.proposed_effects] == ["u1"]


class TestAnEffectIsAnArgumentAndNotAVerdict:
    """Doc 07 offers *Add exception* and *Change scope* beside *Accept*."""

    def test_an_effect_carries_no_status_field(self) -> None:
        fields = Effect.__dataclass_fields__
        assert set(fields) == {"constraint_key", "item_key", "kind", "basis"}

    def test_every_effect_says_why(self) -> None:
        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP, accepted=True)],
            [
                OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP),
                OpenItem(key="a1", statement=COLLABORATION_CAN_WAIT),
            ],
        )
        assert all(effect.basis.strip() for effect in plan.effects)


class TestTheRelationSeparatesAnsweringFromBounding:
    def test_a_constraint_covering_the_whole_question_answers_it(self) -> None:
        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP, accepted=True)],
            [OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP)],
        )
        assert plan.effects[0].kind is EffectKind.RESOLVES

    def test_a_constraint_covering_part_of_it_bounds_it(self) -> None:
        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP, accepted=True)],
            [OpenItem(key="a1", statement=COLLABORATION_CAN_WAIT)],
        )
        assert plan.effects[0].kind is EffectKind.NARROWS
        assert "collaboration" in plan.effects[0].basis

    def test_one_shared_common_word_is_not_a_shared_subject(self) -> None:
        plan = plan_constraint_model(
            [_candidate(COLLABORATION_OUTSIDE_MVP, accepted=True)],
            [OpenItem(key="a2", statement="The project has a single user for MVP.")],
        )
        assert plan.effects == ()

    def test_a_statement_that_restricts_nothing_propagates_nothing(self) -> None:
        plan = plan_constraint_model(
            [_candidate("Team collaboration is part of MVP planning.", accepted=True)],
            [OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP)],
        )
        assert plan.effects == ()
        assert plan.constraints[0].restricts is False

    def test_common_words_are_not_subject_terms(self) -> None:
        assert subject_terms("Is it in the MVP?") == frozenset({"mvp"})


class TestFamiliesReadTheMostSpecificSense:
    """Doc 07's families overlap by construction, so the order is the statement."""

    @pytest.mark.parametrize(
        ("statement", "family"),
        [
            (COLLABORATION_OUTSIDE_MVP, ConstraintFamily.SCOPE_RELEASE),
            ("Original user content must not be altered.", ConstraintFamily.DATA_INTEGRITY),
            ("Progression must not be rigid.", ConstraintFamily.UX_WORKFLOW),
            ("Credentials must never be written to disk.", ConstraintFamily.SECURITY_REGULATORY),
        ],
    )
    def test_the_corpus_constraints_land_in_their_family(
        self, statement: str, family: ConstraintFamily
    ) -> None:
        assert family_of(statement) is family

    def test_a_constraint_naming_no_family_is_unclassified_rather_than_guessed(self) -> None:
        assert family_of("Keep it simple.") is ConstraintFamily.UNCLASSIFIED

    def test_a_boundary_is_read_from_the_restriction_and_not_the_family(self) -> None:
        assert is_boundary("Original user content must not be altered.") is True
        assert is_boundary("Original user content is stored verbatim.") is False


class TestTheCorpusConstraintsPlanCoherently:
    """The three golden-corpus constraints against the items doc 07 names."""

    @pytest.fixture
    def plan(self) -> ConstraintModelPlan:
        return plan_constraint_model(
            [
                _candidate(COLLABORATION_OUTSIDE_MVP, accepted=True),
                _candidate("Original user content must not be altered.", accepted=True),
                _candidate("Progression must not be rigid.", accepted=True),
            ],
            [
                OpenItem(key="u1", statement=IS_COLLABORATION_IN_MVP),
                OpenItem(
                    key="u2",
                    statement="Will more than one person confirm decisions in the first release?",
                ),
                OpenItem(key="a1", statement=COLLABORATION_CAN_WAIT),
                OpenItem(key="a2", statement="The project has a single user for MVP."),
            ],
        )

    def test_every_constraint_is_kept_and_all_three_restrict(
        self, plan: ConstraintModelPlan
    ) -> None:
        assert len(plan.constraints) == 3
        assert all(constraint.restricts for constraint in plan.constraints)

    def test_the_scope_boundary_reaches_two_of_the_four_items(
        self, plan: ConstraintModelPlan
    ) -> None:
        assert {effect.item_key for effect in plan.effects} == {"u1", "a1"}

    def test_the_two_it_does_not_reach_are_left_open_rather_than_guessed(
        self, plan: ConstraintModelPlan
    ) -> None:
        """`D-124`: `u2` asks about collaboration in MVP and shares no term with it.

        The floor of a lexical relation, stated as a measurement. Closing it is
        `SYN-3a`'s neighbourhood and not a wider word list.
        """

        reached = {effect.item_key for effect in plan.effects}
        assert "u2" not in reached
        assert "a2" not in reached
