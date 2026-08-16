"""What an unknown blocks, and what the plan refuses to claim about it.

`SYN-11a`/`D-149`. The relation is derived from two things the estate already
holds — the areas a question's wording names, and the areas the last readiness
snapshot leaves short of coverage — so these tests pin the derivation and, more
importantly, pin the two ways it must decline: a question standing in front of a
covered area, and a project with no snapshot at all.
"""

from __future__ import annotations

from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.synthesizers.unknowns import (
    UnknownPlan,
    UnknownTheme,
    blocked_areas,
    explain,
    plan_unknowns,
    theme_priority,
)

ACCEPTANCE = "How do we verify this? Nothing says which tests must pass."
DATA = "What does the payload contain, and which schemas apply?"

NO_VECTORS = lambda _left, _right: None  # noqa: E731


def _item(name: str) -> KnowledgeItemId:
    return KnowledgeItemId(name)


class TestNamingAnAreaIsNotBlockingIt:
    def test_a_question_blocks_the_area_it_names_when_that_area_is_short(self) -> None:
        assert blocked_areas(ACCEPTANCE, {"acceptance_criteria", "domain_model_and_data"}) == (
            "acceptance_criteria",
        )

    def test_a_question_blocks_nothing_when_the_area_it_names_is_covered(self) -> None:
        """The project answered it somewhere else, whatever the wording says."""

        assert blocked_areas(ACCEPTANCE, {"domain_model_and_data"}) == ()

    def test_a_question_that_names_no_area_blocks_nothing(self) -> None:
        assert blocked_areas("Who is joining the call?", {"acceptance_criteria"}) == ()


class TestRankingLeadsWithBlockingImpact:
    def test_one_blocked_area_outranks_a_question_asked_far_more_often(self) -> None:
        blocking = UnknownTheme(
            members=(_item("a"),),
            canonical_id=_item("a"),
            question=ACCEPTANCE,
            severity="minor",
            blocks=("acceptance_criteria",),
        )
        corroborated = UnknownTheme(
            members=tuple(_item(f"b{n}") for n in range(9)),
            canonical_id=_item("b0"),
            question=DATA,
            severity="critical",
        )

        assert theme_priority(blocking) > theme_priority(corroborated)

    def test_without_blocks_the_ranking_is_what_it_was(self) -> None:
        """One function, not a second code path for projects without readiness."""

        once = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")
        twice = UnknownTheme((_item("b"), _item("c")), _item("b"), DATA, "minor")

        assert theme_priority(twice) > theme_priority(once)


class TestThePlanNeverClaimsARankingItDidNotPerform:
    def _plan(self, incomplete: set[str] | None) -> UnknownPlan:
        ids = [_item("a"), _item("b")]
        return plan_unknowns(
            ids,
            {ids[0]: ACCEPTANCE, ids[1]: DATA},
            dict.fromkeys(ids, "critical"),
            dict.fromkeys(ids, None),
            NO_VECTORS,
            incomplete_areas=incomplete,
        )

    def test_no_snapshot_means_no_blocking_claim(self) -> None:
        plan = self._plan(None)

        assert not plan.ranked_by_blocking
        assert all(theme.blocks == () for theme in plan.themes)

    def test_a_snapshot_with_every_area_covered_still_ranks_by_blocking(self) -> None:
        """Empty is not absent: this project has coverage, and it blocks nothing."""

        plan = self._plan(set())

        assert plan.ranked_by_blocking
        assert all(theme.blocks == () for theme in plan.themes)

    def test_the_blocking_theme_leads_the_queue(self) -> None:
        plan = self._plan({"acceptance_criteria"})

        assert plan.ranked_by_blocking
        assert plan.themes[0].question == ACCEPTANCE
        assert plan.themes[0].blocks == ("acceptance_criteria",)


class TestTheSentenceFollowsTheFlag:
    def test_it_names_the_areas_when_the_ranking_used_them(self) -> None:
        theme = UnknownTheme(
            (_item("a"),), _item("a"), ACCEPTANCE, "critical", ("acceptance_criteria",)
        )

        sentence = explain(theme, ranked_by_blocking=True)

        assert "acceptance_criteria" in sentence
        assert "not by what it blocks" not in sentence

    def test_it_refuses_the_claim_without_a_snapshot(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")

        assert "not by what it blocks" in explain(theme, ranked_by_blocking=False)

    def test_blocking_nothing_is_said_rather_than_implied(self) -> None:
        theme = UnknownTheme((_item("a"),), _item("a"), ACCEPTANCE, "critical")

        assert "blocks nothing measured" in explain(theme, ranked_by_blocking=True)
