"""What an unknown blocks, how much that weighs, and what the plan refuses to claim.

`SYN-11a`/`D-149`, `SYN-11`/`D-152`, `D-154` and `D-157`. The relation is derived
from two things the estate already holds — the areas a question's wording names,
and the areas the last readiness snapshot leaves short of coverage, with the
weights, contradiction flags and counts that snapshot recorded — so these tests
pin the derivation and, more importantly, pin the ways it must decline: a
question standing in front of a covered area, a project with no snapshot at all,
and a shortfall the counts cannot explain.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
#: Two rows a vector space would put on top of each other, so one theme holds both.
SAME_QUESTION_TWICE = lambda _left, _right: 0.0  # noqa: E731


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


class TestConflictBreaksTheTiesMaterialityLeaves:
    """`D-154`. A blocked area whose statements disagree cannot be closed by one
    more answer, so the question in front of it leads — below weight, above
    repetition."""

    CONTESTED = UncoveredArea(MODEL.key, MODEL.name, MODEL.weight, True, contradicted=True)

    def _theme(self, name: str, *blocks: UncoveredArea, asked: int = 1) -> UnknownTheme:
        members = tuple(_item(f"{name}{n}") for n in range(asked))
        return UnknownTheme(members, members[0], ACCEPTANCE, "minor", blocks)

    def test_a_contested_area_outranks_a_quiet_one_of_the_same_weight(self) -> None:
        quiet = UncoveredArea(CRITERIA.key, CRITERIA.name, MODEL.weight, True)

        assert theme_priority(self._theme("a", self.CONTESTED)) > theme_priority(
            self._theme("b", quiet)
        )

    def test_conflict_never_outranks_a_heavier_blocked_area(self) -> None:
        """It is a condition on what is blocked, not a measure of consequence."""

        heavier = UncoveredArea("functional_requirements", "Functional requirements", 2.0, True)

        assert theme_priority(self._theme("a", heavier)) > theme_priority(
            self._theme("b", self.CONTESTED)
        )

    def test_conflict_outranks_any_amount_of_repetition(self) -> None:
        quiet = UncoveredArea(CRITERIA.key, CRITERIA.name, MODEL.weight, True)

        assert theme_priority(self._theme("a", self.CONTESTED)) > theme_priority(
            self._theme("b", quiet, asked=20_000)
        )

    def test_no_achievable_materiality_reaches_the_required_band(self) -> None:
        """`D-152`'s lesson one band up: a term with something underneath it is a
        band only if it is capped. Every area the software template defines,
        blocked at once and none of them required, must still lose to one
        required area."""

        every_optional = tuple(
            UncoveredArea(f"a{n}", f"A{n}", 5.0, required=False) for n in range(40)
        )
        required_one = UncoveredArea("users_and_stakeholders", "Users", 0.5, required=True)

        assert theme_priority(self._theme("a", required_one)) > theme_priority(
            self._theme("b", *every_optional)
        )

    def test_a_contested_area_leads_the_areas_the_reader_is_shown(self) -> None:
        quiet = UncoveredArea(CRITERIA.key, CRITERIA.name, MODEL.weight, True)

        assert blocked_areas(BOTH, (quiet, self.CONTESTED)) == (self.CONTESTED, quiet)


class TestInformationGainIsTheDistanceToTheAreaOwnMinimum:
    """`D-157`. The shortfall is the arithmetic `evaluate_area` performs, read
    back off the snapshot row — not a heuristic about the question."""

    NEAR = UncoveredArea(CRITERIA.key, CRITERIA.name, CRITERIA.weight, True, shortfall=1)
    FAR = UncoveredArea(MODEL.key, MODEL.name, CRITERIA.weight, True, shortfall=3)

    def _theme(self, name: str, *blocks: UncoveredArea, asked: int = 1) -> UnknownTheme:
        members = tuple(_item(f"{name}{n}") for n in range(asked))
        return UnknownTheme(members, members[0], ACCEPTANCE, "minor", blocks)

    def test_one_answer_away_outranks_an_area_that_stays_short_afterwards(self) -> None:
        assert theme_priority(self._theme("a", self.NEAR)) > theme_priority(
            self._theme("b", self.FAR)
        )

    def test_a_shortfall_of_zero_is_not_maximal_gain(self) -> None:
        """Zero means the count threshold is met and the area is short for
        another reason — the divided area, whose claims the counts cannot see.
        Reading it as *closed* would put it at the top of the queue."""

        met = UncoveredArea(MODEL.key, MODEL.name, CRITERIA.weight, True, shortfall=0)

        assert not met.one_answer_away
        assert theme_priority(self._theme("a", self.NEAR)) > theme_priority(self._theme("b", met))

    def test_an_unread_shortfall_claims_nothing(self) -> None:
        assert not CRITERIA.one_answer_away

    def test_a_contested_area_is_never_one_answer_away(self) -> None:
        """`D-154` says a contested area is not closed by adding one more, so the
        two dimensions cannot assert opposite things about the same area."""

        contested = UncoveredArea(
            CRITERIA.key, CRITERIA.name, CRITERIA.weight, True, contradicted=True, shortfall=1
        )

        assert not contested.one_answer_away

    def test_gain_never_outranks_conflict(self) -> None:
        contested = UncoveredArea(
            MODEL.key, MODEL.name, CRITERIA.weight, True, contradicted=True, shortfall=3
        )

        assert theme_priority(self._theme("a", contested)) > theme_priority(
            self._theme("b", self.NEAR)
        )

    def test_gain_outranks_any_amount_of_repetition(self) -> None:
        assert theme_priority(self._theme("a", self.NEAR)) > theme_priority(
            self._theme("b", self.FAR, asked=20_000)
        )

    def test_the_nearer_area_leads_the_areas_the_reader_is_shown(self) -> None:
        near = UncoveredArea(MODEL.key, MODEL.name, CRITERIA.weight, True, shortfall=1)
        far = UncoveredArea(CRITERIA.key, CRITERIA.name, CRITERIA.weight, True, shortfall=4)

        assert blocked_areas(BOTH, (far, near)) == (near, far)

    def test_the_card_says_the_shortfall_without_promising_it_closes(self) -> None:
        theme = self._theme("a", self.NEAR)
        sentence = explain(theme, ranked_by_blocking=True)

        assert "one confirmed statement short of what it asks for" in sentence
        assert "answering" not in sentence.lower()

    def test_a_far_area_is_not_described_as_nearly_covered(self) -> None:
        assert "one confirmed statement short" not in explain(
            self._theme("a", self.FAR), ranked_by_blocking=True
        )


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

    def test_a_contested_area_says_so_and_says_why_it_is_not_one_answer_away(self) -> None:
        """`D-154`. Otherwise the card offers an area that looks empty when what
        is actually there is two statements that disagree."""

        contested = UncoveredArea(CRITERIA.key, CRITERIA.name, 1.5, True, contradicted=True)
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (contested,))

        assert "statements there already contradict each other" in explain(
            theme, ranked_by_blocking=True
        )

    def test_an_optional_contested_area_says_both_things(self) -> None:
        contested = UncoveredArea(
            DELIVERY.key, DELIVERY.name, DELIVERY.weight, False, contradicted=True
        )
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (contested,))
        sentence = explain(theme, ranked_by_blocking=True)

        assert "not required for readiness" in sentence
        assert "contradict each other" in sentence

    def test_a_quiet_area_is_not_described_as_contested(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical", (CRITERIA,))

        assert "contradict" not in explain(theme, ranked_by_blocking=True)

    def test_it_refuses_the_claim_without_a_snapshot(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")

        assert "not by what it blocks" in explain(theme, ranked_by_blocking=False)

    def test_blocking_nothing_is_said_rather_than_implied(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")

        assert "blocks nothing measured" in explain(theme, ranked_by_blocking=True)


class TestNoveltyIsMeasuredAgainstTheLastMeasurement:
    """`D-160`. A question first asked after coverage was last measured is one
    that measurement never saw. Not a clock reading, and not a diff against KAE's
    own earlier output — both of those reorder the queue without the project
    changing."""

    MEASURED = datetime(2026, 8, 10, tzinfo=UTC)
    BEFORE = datetime(2026, 8, 9, tzinfo=UTC)
    AFTER = datetime(2026, 8, 11, tzinfo=UTC)

    def _theme(
        self, name: str, *blocks: UncoveredArea, asked: int = 1, novel: bool
    ) -> UnknownTheme:
        members = tuple(_item(f"{name}{n}") for n in range(asked))
        return UnknownTheme(members, members[0], ACCEPTANCE, "minor", blocks, novel=novel)

    def _plan(
        self,
        times: dict[KnowledgeItemId, datetime],
        measured: datetime | None,
        distance: object = NO_VECTORS,
    ) -> UnknownPlan:
        ids = list(times)
        return plan_unknowns(
            ids,
            dict.fromkeys(ids, ACCEPTANCE),
            dict.fromkeys(ids, "critical"),
            dict.fromkeys(ids, None),
            distance,  # type: ignore[arg-type]
            uncovered_areas=(CRITERIA,),
            first_asked=times,
            measured_at=measured,
        )

    def test_a_newer_question_outranks_an_older_one_blocking_the_same_area(self) -> None:
        assert theme_priority(self._theme("a", CRITERIA, novel=True)) > theme_priority(
            self._theme("b", CRITERIA, novel=False)
        )

    def test_novelty_never_outranks_information_gain(self) -> None:
        """*Not yet accounted for* says nothing about consequence."""

        near = UncoveredArea(CRITERIA.key, CRITERIA.name, CRITERIA.weight, True, shortfall=1)

        assert theme_priority(self._theme("a", near, novel=False)) > theme_priority(
            self._theme("b", CRITERIA, novel=True)
        )

    def test_novelty_outranks_any_amount_of_repetition(self) -> None:
        assert theme_priority(self._theme("a", CRITERIA, novel=True)) > theme_priority(
            self._theme("b", CRITERIA, asked=20_000, novel=False)
        )

    def test_every_wording_must_postdate_the_measurement(self) -> None:
        """A question asked again is not a new question, however recent its
        newest wording is."""

        older, newer = _item("older"), _item("newer")
        plan = self._plan(
            {older: self.BEFORE, newer: self.AFTER}, self.MEASURED, SAME_QUESTION_TWICE
        )

        assert len(plan.themes) == 1
        assert plan.themes[0].asked == 2
        assert not plan.themes[0].novel

    def test_a_question_asked_after_the_measurement_is_novel(self) -> None:
        plan = self._plan({_item("a"): self.AFTER}, self.MEASURED)

        assert plan.themes[0].novel

    def test_a_missing_timestamp_is_not_evidence_of_novelty(self) -> None:
        plan = plan_unknowns(
            [_item("a")],
            {_item("a"): ACCEPTANCE},
            {_item("a"): "critical"},
            {_item("a"): None},
            NO_VECTORS,
            uncovered_areas=(CRITERIA,),
            first_asked={},
            measured_at=self.MEASURED,
        )

        assert not plan.themes[0].novel

    def test_a_project_with_no_snapshot_claims_no_novelty(self) -> None:
        """One path, not two: with no measurement there is nothing to be newer
        than, exactly as there is nothing to be blocked by."""

        plan = self._plan({_item("a"): self.AFTER}, None)

        assert not plan.themes[0].novel

    def test_the_card_says_the_question_is_newer_than_the_measurement(self) -> None:
        sentence = explain(self._theme("a", CRITERIA, novel=True), ranked_by_blocking=True)

        assert "first asked after coverage was last measured" in sentence

    def test_an_older_question_is_not_described_as_new(self) -> None:
        sentence = explain(self._theme("a", CRITERIA, novel=False), ranked_by_blocking=True)

        assert "coverage was last measured" not in sentence
