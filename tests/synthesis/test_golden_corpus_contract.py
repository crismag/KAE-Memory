"""Qualitative gates the golden corpus must satisfy once synthesis exists.

These are not target counts. They fail on today's product because the active
model is the extracted notebook. They are marked xfail until Phase 3 provides
a synthesizer; removing the mark without satisfying them is a regression.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.goal_synthesis_service import GoalSynthesisService
from kae_memory.application.synthesis_service import SynthesisService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project
from kae_memory.domain.synthesizers.goals import GoalJudgement
from tests.synthesis.corpus import (
    ATTENTION_BOUND,
    HOLD_MOON_TEXT,
    WHAT_ARE_WE_BUILDING,
    observations_for,
)
from tests.synthesis.load import load_golden_corpus

pytestmark = pytest.mark.synthesis_gate

_UNKNOWNS_MISSING = (
    "strict=True xfail: the Unknowns synthesizer is Phase 3c. The unknown half "
    "of the active model is still every extracted row."
)


def _shown_as_model(items: tuple[KnowledgeItem, ...]) -> tuple[KnowledgeItem, ...]:
    """What the product presents where no synthesizer exists yet: extracted rows.

    Still the honest description of the unknown half, which is Phase 3c. The
    goal gates below no longer use it — they read the synthesized model, which
    is what these assertions were always about.
    """

    return tuple(
        item
        for item in items
        if item.lifecycle in {LifecycleState.PROPOSED, LifecycleState.VALIDATED}
    )


class _CorpusJudge:
    """A judge that knows this project, standing in for a model in CI.

    `D-101`: membership is a judgement, and no deterministic rule separates
    `hold-moon` from a real goal on this corpus. What CI can assert is that the
    **pipeline honours a judgement** — that a refusal keeps a statement out of
    the model and the reason survives. Whether a 14B model judges well is a
    different claim, measured against a live Ollama and recorded in the phase
    document, not asserted here.
    """

    def judge(self, statement: str, identity: Sequence[str]) -> GoalJudgement:
        if HOLD_MOON_TEXT.casefold() in statement.casefold():
            return GoalJudgement(
                include=False,
                reason="Names nothing this project is about; no evidence connects it.",
            )
        return GoalJudgement(include=True, reason="Consistent with the project's identity.")


def _synthesized_goals(
    factory: sessionmaker[Session], memory: MemoryService, project_id: ProjectId
) -> tuple[str, ...]:
    """The project's goal model, as the product would read it."""

    GoalSynthesisService(factory, judge=_CorpusJudge()).synthesize(project_id)
    return tuple(
        obj.statement for obj in SynthesisService(factory).list_objects(project_id, domain="goal")
    )


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, Project]:
    memory = MemoryService(factory)
    return memory, memory.create_project("KAE synthesis corpus", key="golden-gates")


class TestNoGarbageInTheActiveModel:
    def test_hold_moon_does_not_survive_as_an_active_goal(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        memory, proj = project
        load_golden_corpus(memory, proj.id)

        goals = _synthesized_goals(factory, memory, proj.id)

        assert goals, "the goal model is empty; synthesis did not run"
        assert not any(HOLD_MOON_TEXT.casefold() in goal.casefold() for goal in goals)

    def test_conversation_local_instructions_are_not_active_goals(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """Excluded deterministically, so this holds with no judge at all."""

        memory, proj = project
        load_golden_corpus(memory, proj.id)
        local = {item.content for item in observations_for("conversation-local")}

        goals = _synthesized_goals(factory, memory, proj.id)

        assert set(goals).isdisjoint(local)

    def test_the_model_is_much_smaller_than_the_evidence(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """The claim the whole package rests on, stated as a ratio.

        Not a target count — `02-GOALS-SYNTHESIS.md` is explicit that exact
        cardinality is not the acceptance criterion. What must hold is that 47
        goal-shaped sentences do not arrive as 47 goals.
        """

        memory, proj = project
        loaded = load_golden_corpus(memory, proj.id)
        extracted = [item for item in loaded.items if item.kind == KnowledgeKind.GOAL.value]

        goals = _synthesized_goals(factory, memory, proj.id)

        assert len(goals) < len(extracted)

    def test_every_promoted_goal_keeps_its_evidence(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """Compaction is not deletion (`ADR-0007`).

        Every goal in the model points back at the rows that produced it, and
        every one of those rows is still retrievable.
        """

        memory, proj = project
        load_golden_corpus(memory, proj.id)
        synthesis = SynthesisService(factory)
        GoalSynthesisService(factory, judge=_CorpusJudge()).synthesize(proj.id)

        objects = synthesis.list_objects(proj.id, domain="goal")

        assert objects
        for obj in objects:
            bindings = synthesis.list_bindings(proj.id, obj.id)
            assert bindings, f"{obj.statement!r} entered the model with no evidence"


@pytest.mark.xfail(strict=True, reason=_UNKNOWNS_MISSING)
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


@pytest.mark.xfail(strict=True, reason=_UNKNOWNS_MISSING)
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
