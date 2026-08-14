"""The golden corpus is internally consistent and matches the documented baseline.

These checks do not need a database. They freeze the fixture so later phases
cannot quietly drop a named pathology or change a headline count without
noticing.
"""

from __future__ import annotations

from kae_memory.domain.models import KnowledgeKind
from tests.synthesis.corpus import (
    AREA_SUFFICIENT_TEXT,
    ATTENTION_BOUND,
    HEADLINE_COUNTS,
    HOLD_MOON,
    HOLD_MOON_TEXT,
    OBSERVATIONS,
    PROJECT_IDENTITY_TEXT,
    WHAT_ARE_WE_BUILDING,
    collapse_key,
    count_by_kind,
    observations_for,
)


class TestHeadlineCounts:
    def test_extracted_counts_match_the_documented_corpus(self) -> None:
        assert count_by_kind() == {
            **HEADLINE_COUNTS,
            KnowledgeKind.CONSTRAINT.value: 3,
            KnowledgeKind.DECISION.value: 4,
        }


class TestNamedPathologiesArePresent:
    def test_hold_moon_is_an_extracted_goal(self) -> None:
        goals = observations_for(HOLD_MOON)
        assert any(
            item.kind is KnowledgeKind.GOAL and item.content == HOLD_MOON_TEXT for item in goals
        )

    def test_hold_moon_also_appears_as_an_unknown(self) -> None:
        assert any(
            item.kind is KnowledgeKind.UNKNOWN
            and HOLD_MOON_TEXT.casefold() in item.content.casefold()
            for item in observations_for(HOLD_MOON)
        )

    def test_what_are_we_building_is_stale_relative_to_project_identity(self) -> None:
        """The same corpus that asks what we are building also states it."""

        assert any(item.content == PROJECT_IDENTITY_TEXT for item in OBSERVATIONS)
        stale = observations_for(WHAT_ARE_WE_BUILDING)
        assert stale
        assert all(item.kind is KnowledgeKind.UNKNOWN for item in stale)

    def test_an_area_is_marked_sufficient_while_candidates_remain(self) -> None:
        sufficient = [item for item in OBSERVATIONS if item.content == AREA_SUFFICIENT_TEXT]
        assert len(sufficient) == 1
        assert sufficient[0].confirm is True
        proposed_goals = [
            item for item in OBSERVATIONS if item.kind is KnowledgeKind.GOAL and not item.confirm
        ]
        assert len(proposed_goals) == HEADLINE_COUNTS[KnowledgeKind.GOAL.value]


class TestFixtureHygiene:
    def test_every_observation_has_a_source(self) -> None:
        assert all(item.source.strip() for item in OBSERVATIONS)

    def test_identical_collapse_keys_are_unique(self) -> None:
        """Semantic duplicates must survive write_knowledge as separate rows."""

        keys = [collapse_key(item) for item in OBSERVATIONS]
        assert len(keys) == len(set(keys))

    def test_attention_bound_is_a_handful_not_a_target_count(self) -> None:
        assert 1 <= ATTENTION_BOUND <= 12
        extracted = len(OBSERVATIONS)
        assert extracted > ATTENTION_BOUND * 10
