"""What an unknown blocks, how much that weighs, and what the plan refuses to claim.

`SYN-11a`/`D-149` and `SYN-11`/`D-152`. The relation is derived from two things
the estate already holds — the areas a question's wording names, and the areas
the last readiness snapshot leaves short of coverage, with the weights that
snapshot recorded — so these tests pin the derivation and, more importantly, pin
the two ways it must decline: a question standing in front of a covered area, and
a project with no snapshot at all.
"""

from __future__ import annotations

from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.synthesizers.unknowns import (
    UncoveredArea,
    UnknownPlan,
    UnknownTheme,
    blocked_areas,
    explain,
    plan_unknowns,
    theme_priority,
)

ACCEPTANCE = "How do we verify this? Nothing says which tests must pass."
DATA = "What does the payload contain, and which schemas apply?"
#: Names both of the areas above, so ordering can be read off one question.
BOTH = "How do we verify this, and what does the payload contain? Which schemas apply?"

#: The software template's own values, so the fixtures cannot drift from it.
CRITERIA = UncoveredArea("acceptance_criteria", "Acceptance criteria", 1.5, required=True)
MODEL = UncoveredArea("domain_model_and_data", "Domain model and data", 1.5, required=True)
DELIVERY = UncoveredArea(
    "delivery_and_operations", "Delivery and operational context", 1.0, required=False
)

NO_VECTORS = lambda _left, _right: None  # noqa: E731


def _item(name: str) -> KnowledgeItemId:
    return KnowledgeItemId(name)


class TestNamingAnAreaIsNotBlockingIt:
    def test_a_question_blocks_the_area_it_names_when_that_area_is_short(self) -> None:
        assert blocked_areas(ACCEPTANCE, (CRITERIA, MODEL)) == (CRITERIA,)

    def test_a_question_blocks_nothing_when_the_area_it_names_is_covered(self) -> None:
        """The project answered it somewhere else, whatever the wording says."""

        assert blocked_areas(ACCEPTANCE, (MODEL,)) == ()

    def test_a_question_that_names_no_area_blocks_nothing(self) -> None:
        assert blocked_areas("Who is joining the call?", (CRITERIA,)) == ()


class TestRankingLeadsWithBlockingImpact:
    def test_one_blocked_area_outranks_a_question_asked_far_more_often(self) -> None:
        blocking = UnknownTheme(
            members=(_item("a"),),
            canonical_id=_item("a"),
            question=ACCEPTANCE,
            severity="minor",
            blocks=(CRITERIA,),
        )
        corroborated = UnknownTheme(
            members=tuple(_item(f"b{n}") for n in range(9)),
            canonical_id=_item("b0"),
            question=DATA,
            severity="critical",
        )

        assert theme_priority(blocking) > theme_priority(corroborated)

    def test_repetition_can_never_climb_into_the_band_above_it(self) -> None:
        """`D-152`. The terms were bands in intent and not in arithmetic — an
        uncapped `asked * 10` climbs into any band placed above it. Pinned at the
        finest weight difference the ranking can express, which is where an
        unbounded term reaches first."""

        heavier = UncoveredArea("a", "A", 1.01, required=False)
        lighter = UncoveredArea("b", "B", 1.00, required=False)
        once = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "minor", (heavier,))
        repeated = UnknownTheme(
            tuple(_item(f"b{n}") for n in range(20_000)), _item("b0"), DATA, "critical", (lighter,)
        )

        assert theme_priority(once) > theme_priority(repeated)

    def test_without_blocks_the_ranking_is_what_it_was(self) -> None:
        """One function, not a second code path for projects without readiness."""

        once = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")
        twice = UnknownTheme((_item("b"), _item("c")), _item("b"), DATA, "minor")

        assert theme_priority(twice) > theme_priority(once)


class TestMaterialityWeighsWhatIsBlocked:
    def _theme(self, name: str, *blocks: UncoveredArea) -> UnknownTheme:
        return UnknownTheme((_item(name),), _item(name), ACCEPTANCE, "minor", blocks)

    def test_a_heavier_area_outranks_a_lighter_one(self) -> None:
        heavy = UncoveredArea("functional_requirements", "Functional requirements", 2.0, True)
        light = UncoveredArea("quality_attributes", "Quality attributes", 1.0, True)

        assert theme_priority(self._theme("a", heavy)) > theme_priority(self._theme("b", light))

    def test_blocking_anything_required_outranks_any_amount_of_optional(self) -> None:
        """A mandatory area is what makes readiness unreachable; an optional one
        only moves the score, however much of it there is."""

        optional_pair = (
            DELIVERY,
            UncoveredArea("interfaces_and_integrations", "Interfaces", 1.0, required=False),
        )
        required_one = UncoveredArea("users_and_stakeholders", "Users", 1.0, required=True)

        assert theme_priority(self._theme("a", required_one)) > theme_priority(
            self._theme("b", *optional_pair)
        )

    def test_blocked_areas_are_ordered_heaviest_first(self) -> None:
        heavier = UncoveredArea(MODEL.key, MODEL.name, 2.0, required=True)

        assert blocked_areas(BOTH, (CRITERIA, heavier)) == (heavier, CRITERIA)

    def test_a_required_area_leads_a_heavier_optional_one(self) -> None:
        optional = UncoveredArea(MODEL.key, MODEL.name, 2.0, required=False)

        assert blocked_areas(BOTH, (optional, CRITERIA)) == (CRITERIA, optional)


class TestThePlanNeverClaimsARankingItDidNotPerform:
    def _plan(self, uncovered: tuple[UncoveredArea, ...] | None) -> UnknownPlan:
        ids = [_item("a"), _item("b")]
        return plan_unknowns(
            ids,
            {ids[0]: ACCEPTANCE, ids[1]: DATA},
            dict.fromkeys(ids, "critical"),
            dict.fromkeys(ids, None),
            NO_VECTORS,
            uncovered_areas=uncovered,
        )

    def test_no_snapshot_means_no_blocking_claim(self) -> None:
        plan = self._plan(None)

        assert not plan.ranked_by_blocking
        assert all(theme.blocks == () for theme in plan.themes)

    def test_a_snapshot_with_every_area_covered_still_ranks_by_blocking(self) -> None:
        """Empty is not absent: this project has coverage, and it blocks nothing."""

        plan = self._plan(())

        assert plan.ranked_by_blocking
        assert all(theme.blocks == () for theme in plan.themes)

    def test_the_blocking_theme_leads_the_queue(self) -> None:
        plan = self._plan((CRITERIA,))

        assert plan.ranked_by_blocking
        assert plan.themes[0].question == ACCEPTANCE
        assert plan.themes[0].blocks == (CRITERIA,)


class TestTheSentenceFollowsTheFlag:
    def test_it_names_the_areas_when_the_ranking_used_them(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (CRITERIA,))

        sentence = explain(theme, ranked_by_blocking=True)

        assert "Acceptance criteria" in sentence
        assert "not by what it blocks" not in sentence

    def test_it_names_an_area_the_way_a_person_says_it_and_not_by_its_key(self) -> None:
        """`D-151`. This sentence is read on a card, so a key in it is a defect."""

        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (CRITERIA,))

        sentence = explain(theme, ranked_by_blocking=True)

        assert "acceptance_criteria" not in sentence
        assert "_" not in sentence

    def test_a_label_is_not_case_folded_on_its_way_to_the_reader(self) -> None:
        """The whole basis used to be `str.capitalize()`d, which lower-cases the
        rest of the string — a label the function was handed, not composed."""

        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (CRITERIA, MODEL))

        sentence = explain(theme, ranked_by_blocking=True)

        for area in theme.blocks:
            assert area.name in sentence

    def test_an_area_readiness_does_not_require_says_so(self) -> None:
        """`D-152`. Otherwise the card reads as something the project cannot
        proceed without, which the template denies."""

        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (DELIVERY,))

        assert "not required for readiness" in explain(theme, ranked_by_blocking=True)

    def test_a_required_area_is_not_qualified(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (CRITERIA,))

        assert "not required" not in explain(theme, ranked_by_blocking=True)

    def test_it_refuses_the_claim_without_a_snapshot(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")

        assert "not by what it blocks" in explain(theme, ranked_by_blocking=False)

    def test_blocking_nothing_is_said_rather_than_implied(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")

        assert "blocks nothing measured" in explain(theme, ranked_by_blocking=True)
