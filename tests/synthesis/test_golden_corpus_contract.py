"""Qualitative gates the golden corpus must satisfy once synthesis exists.

These are not target counts. They fail on today's product because the active
model is the extracted notebook. They are marked xfail until Phase 3 provides
a synthesizer; removing the mark without satisfying them is a regression.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project
from tests.synthesis.corpus import (
    ATTENTION_BOUND,
    HOLD_MOON_TEXT,
    WHAT_ARE_WE_BUILDING,
    observations_for,
)
from tests.synthesis.load import load_golden_corpus

pytestmark = pytest.mark.synthesis_gate

_SYNTHESIS_MISSING = (
    "strict=True xfail: Phase 3 Goals+Unknowns synthesizer is not implemented. "
    "The active model is still every extracted row."
)


def _shown_as_model(items: tuple[KnowledgeItem, ...]) -> tuple[KnowledgeItem, ...]:
    """What the product currently presents as the project: extracted rows.

    Domain synthesizers replace this. The gates below must be pointed at the
    synthesizer's output when that exists; until then they document the gap.
    """

    return tuple(
        item
        for item in items
        if item.lifecycle in {LifecycleState.PROPOSED, LifecycleState.VALIDATED}
    )


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, Project]:
    memory = MemoryService(factory)
    return memory, memory.create_project("KAE synthesis corpus", key="golden-gates")


@pytest.mark.xfail(strict=True, reason=_SYNTHESIS_MISSING)
class TestNoGarbageInTheActiveModel:
    def test_hold_moon_does_not_survive_as_an_active_goal(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        active_goals = [
            item for item in _shown_as_model(loaded.items) if item.kind == KnowledgeKind.GOAL.value
        ]

        assert not any(
            HOLD_MOON_TEXT.casefold() in item.current_version.content.casefold()
            for item in active_goals
        )

    def test_conversation_local_instructions_are_not_active_goals(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        contents = {
            item.current_version.content
            for item in _shown_as_model(loaded.items)
            if item.kind == KnowledgeKind.GOAL.value
        }
        local = {item.content for item in observations_for("conversation-local")}

        assert contents.isdisjoint(local)


@pytest.mark.xfail(strict=True, reason=_SYNTHESIS_MISSING)
class TestStaleUnknownsDoNotRemainCurrent:
    def test_what_are_we_building_is_closed_once_identity_evidence_exists(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        active_unknowns = [
            item.current_version.content
            for item in _shown_as_model(loaded.items)
            if item.kind == KnowledgeKind.UNKNOWN.value
        ]
        stale = {item.content for item in observations_for(WHAT_ARE_WE_BUILDING)}

        assert stale.isdisjoint(active_unknowns)


@pytest.mark.xfail(strict=True, reason=_SYNTHESIS_MISSING)
class TestHumanWorkloadIsBounded:
    def test_proposed_rows_are_not_the_attention_queue(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        """Attention must be a handful, not the extraction count."""

        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        shown = _shown_as_model(loaded.items)

        assert len(shown) <= ATTENTION_BOUND


class TestTraceabilityIsAlreadyRequired:
    def test_every_extracted_row_remains_retrievable_after_load(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        """Synthesis may compact the model. It must not delete evidence."""

        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)

        assert len(loaded.items) == len(loaded.observations)
        assert all(item.current_version.provenance.source.strip() for item in loaded.items)
