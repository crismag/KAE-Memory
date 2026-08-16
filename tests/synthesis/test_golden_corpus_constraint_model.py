"""Golden corpus: three boundaries nobody accepted, so nothing propagates.

`SYN-5e`, doc 07, `D-124`/`D-126`. The domain layer is tested in
`tests/domain/test_constraint_synthesis.py`; this is what the run persists.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.application.constraint_synthesis_service import ConstraintSynthesisService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.synthesis import SynthesizedLifecycle
from tests.synthesis.corpus import count_by_kind
from tests.synthesis.load import load_golden_corpus

COLLABORATION_OUTSIDE_MVP = "Team collaboration is outside MVP."
IS_COLLABORATION_IN_MVP = "Is team collaboration in MVP?"


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, ConstraintSynthesisService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-constraints")
    return memory, ConstraintSynthesisService(factory), SynthesisService(factory), project


class TestEveryBoundaryBecomesAnObject:
    def test_each_constraint_observation_becomes_exactly_one_object(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, constraints, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = constraints.synthesize(project.id)

        expected = count_by_kind()[KnowledgeKind.CONSTRAINT.value]
        assert report.considered == expected
        assert len(report.constraints) == expected
        stored = synthesis.list_objects(project.id, KnowledgeKind.CONSTRAINT.value)
        assert len(stored) == expected
        assert {obj.lifecycle for obj in stored} == {SynthesizedLifecycle.WORKING}

    def test_the_open_items_are_the_unknowns_and_assumptions(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 07's effects land on what is still open, which is both kinds."""

        memory, constraints, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = constraints.synthesize(project.id)

        counts = count_by_kind()
        expected = counts[KnowledgeKind.UNKNOWN.value] + counts[KnowledgeKind.ASSUMPTION.value]
        assert report.open_items == expected


class TestAnUnacceptedBoundaryPropagatesNothing:
    def test_the_corpus_accepts_none_of_them_so_the_table_stays_empty(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-126`: only accepted constraints get rows, so an empty table here
        is the acceptance boundary holding rather than an absence of reach."""

        memory, constraints, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = constraints.synthesize(project.id)

        assert [constraint.accepted for constraint in report.constraints] == [False, False, False]
        assert report.effects == ()
        assert synthesis.list_constraint_effects(project.id) == ()

    def test_what_would_follow_is_still_reported(self, factory: sessionmaker[Session]) -> None:
        """Reported rather than hidden: the evidence already claims the
        boundary, and what it would settle is the argument for looking at it."""

        memory, constraints, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = constraints.synthesize(project.id)

        assert report.proposed_effects
        for statement, item_statement, basis in report.proposed_effects:
            assert statement
            assert item_statement
            assert basis

    def test_nothing_reaches_the_attention_queue(self, factory: sessionmaker[Session]) -> None:
        """An effect is an argument about an item, not a task; and an
        unaccepted boundary is not an interruption (`D-126`)."""

        memory, constraints, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        constraints.synthesize(project.id)

        assert synthesis.list_attention(project.id) == ()


class TestAcceptanceIsWhatWrites:
    def _accepted_boundary_over_one_unknown(self, memory: MemoryService, project: Project) -> None:
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "constraint-effect")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.CONSTRAINT.value,
                    content=COLLABORATION_OUTSIDE_MVP,
                    source="fixture",
                ),
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.UNKNOWN.value,
                    content=IS_COLLABORATION_IN_MVP,
                    source="fixture",
                ),
            ],
            output_summary={"fixture": "constraint-effect"},
        )
        memory.confirm_knowledge(written[0].id)

    def test_an_accepted_boundary_writes_the_effect_it_imposes(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, constraints, synthesis, project = _services(factory)
        self._accepted_boundary_over_one_unknown(memory, project)

        report = constraints.synthesize(project.id)

        assert report.proposed_effects == ()
        assert len(report.effects) == 1
        effect = report.effects[0]
        assert effect.statement == COLLABORATION_OUTSIDE_MVP
        assert effect.item_statement == IS_COLLABORATION_IN_MVP
        assert effect.kind == "resolves"
        stored = synthesis.list_constraint_effects(project.id)
        assert len(stored) == 1
        assert str(stored[0].knowledge_item_id) == str(effect.knowledge_item_id)

    def test_the_effect_is_queryable_from_the_item_it_bears_on(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The reason the relation is stored at all: a later reader asks what
        bounds *this* question without recomputing the whole cross product."""

        memory, constraints, synthesis, project = _services(factory)
        self._accepted_boundary_over_one_unknown(memory, project)

        report = constraints.synthesize(project.id)

        item_id = report.effects[0].knowledge_item_id
        assert len(synthesis.list_constraint_effects(project.id, item_id)) == 1

    def test_rerunning_writes_nothing_new(self, factory: sessionmaker[Session]) -> None:
        memory, constraints, synthesis, project = _services(factory)
        self._accepted_boundary_over_one_unknown(memory, project)

        first = constraints.synthesize(project.id)
        second = constraints.synthesize(project.id)

        assert second.replayed is True
        assert len(synthesis.list_constraint_effects(project.id)) == 1
        assert [effect.knowledge_item_id for effect in second.effects] == [
            effect.knowledge_item_id for effect in first.effects
        ]

    def test_no_extracted_row_is_touched(self, factory: sessionmaker[Session]) -> None:
        memory, constraints, synthesis, project = _services(factory)
        self._accepted_boundary_over_one_unknown(memory, project)
        before = memory.retrieve_knowledge(project.id, lifecycle=None)

        report = constraints.synthesize(project.id)

        after = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(after) == len(before)
        for constraint in report.constraints:
            assert synthesis.list_bindings(project.id, constraint.object_id)
