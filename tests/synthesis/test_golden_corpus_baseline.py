"""Load the golden corpus the way extraction does, and record today's pathology.

These tests pass on the current product. They exist so a later synthesizer
cannot claim victory by deleting evidence or by changing the fixture until the
baseline no longer resembles the documented conversation corpus.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, Project
from tests.synthesis.corpus import (
    AREA_SUFFICIENT_TEXT,
    HEADLINE_COUNTS,
    HOLD_MOON_TEXT,
    OBSERVATIONS,
    count_by_kind,
)
from tests.synthesis.load import load_golden_corpus


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, Project]:
    memory = MemoryService(factory)
    return memory, memory.create_project("KAE synthesis corpus", key="golden-corpus")


class TestTheFixtureLoadsWithoutCollapsingSemanticDuplicates:
    def test_every_extracted_row_becomes_a_knowledge_item(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)

        assert len(loaded.items) == len(OBSERVATIONS)

    def test_headline_kind_counts_survive_the_write(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        stored = {kind: 0 for kind in HEADLINE_COUNTS}
        for item in loaded.items:
            if item.kind in stored:
                stored[item.kind] += 1

        assert stored == dict(HEADLINE_COUNTS)
        assert stored == {
            kind: count for kind, count in count_by_kind().items() if kind in HEADLINE_COUNTS
        }


class TestTodayTheProductTreatsExtractionAsTheModel:
    def test_hold_moon_is_proposed_knowledge(self, project: tuple[MemoryService, Project]) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        moon = next(
            item
            for item in loaded.items
            if item.current_version.content == HOLD_MOON_TEXT
            and item.kind == KnowledgeKind.GOAL.value
        )

        assert moon.kind == KnowledgeKind.GOAL.value
        assert moon.lifecycle is LifecycleState.PROPOSED

    def test_the_review_queue_is_the_proposed_row_count(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        """Studio Reviews currently equals proposed knowledge. That is the defect."""

        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        proposed = [item for item in loaded.items if item.lifecycle is LifecycleState.PROPOSED]
        confirmed = [item for item in loaded.items if item.lifecycle is LifecycleState.VALIDATED]

        assert len(confirmed) == 1
        assert confirmed[0].current_version.content == AREA_SUFFICIENT_TEXT
        assert len(proposed) == len(OBSERVATIONS) - 1

    def test_every_stored_item_keeps_its_source(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)

        assert all(item.current_version.provenance.source.strip() for item in loaded.items)


class TestTheSynthesizedLayerStartsEmpty:
    def test_extraction_creates_no_synthesized_objects_and_no_attention(
        self, project: tuple[MemoryService, Project], factory: sessionmaker[Session]
    ) -> None:
        """Phase 1 invariant: evidence volume is not model volume or attention volume."""

        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        synthesis = SynthesisService(factory)

        assert len(loaded.items) == len(OBSERVATIONS)
        assert synthesis.list_objects(proj.id) == ()
        assert synthesis.list_attention(proj.id) == ()
        assert synthesis.list_changes(proj.id) == ()
