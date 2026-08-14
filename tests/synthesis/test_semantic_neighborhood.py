"""Neighbourhoods found by vector, and honest about which measure answered.

`PHASE-2-RECONCILIATION.md` recorded the limit this closes:

> `planning-expertise` and most `development-ready-plan` paraphrases share no
> stems (`plan` vs `plann`). Phase 2 leaves them unlinked. That is Phase 3, not
> a threshold to lower.

The corpus is already embedded — 1024 dimensions per chunk, in the same
database — so the fix is a query, not a model call. What these protect is the
part that is easy to get wrong: an empty result must never be read as *nothing
is related* when the real answer is *this deployment cannot compare them*.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.reconciliation_service import ReconciliationService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project
from kae_memory.domain.reconciliation import NeighborhoodMeasure
from kae_memory.persistence.chunk_repository import ChunkRepository

pytestmark = pytest.mark.synthesis_gate

DIMENSIONS = 1024


def _vector(*leading: float) -> list[float]:
    """A unit-ish vector whose leading axes are the ones under test."""

    values = [0.0] * DIMENSIONS
    for index, value in enumerate(leading):
        values[index] = value
    return values


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, Project]:
    memory = MemoryService(factory)
    return memory, memory.create_project("semantic neighborhood", key="semantic-neighborhood")


def _submit(
    memory: MemoryService,
    project_id: ProjectId,
    *observations: tuple[KnowledgeKind, str],
) -> tuple[KnowledgeItem, ...]:
    """Write extracted observations in one run, the way the corpus loader does.

    One run per test rather than one per statement: a project holds one open run
    at a time, and writing them separately is a lifecycle error rather than a
    fixture detail.
    """

    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "neighborhood-fixture")
    return memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind.value, content=text, source="test")
            for kind, text in observations
        ],
        output_summary={
            "fixture": "semantic-neighborhood",
            "items_written": len(observations),
        },
    )


def _embed(
    factory: sessionmaker[Session],
    item: KnowledgeItem,
    vector: list[float],
) -> None:
    """Attach a vector to the chunk the write already created.

    `write_knowledge` chunks every item as it lands, so the rows exist and are
    `pending`. Adding another would be a fixture inventing a shape the product
    does not have — and the unique key on
    `(knowledge_id, chunk_index, embedding_version)` says so.
    """

    with factory() as session:
        chunks = ChunkRepository(session)
        stored = chunks.list_for_knowledge(item.id)
        assert stored, "write_knowledge should have chunked this item"
        chunks.store_embedding(
            stored[0].id,
            vector,
            model="test-embedder",
            dimensions=DIMENSIONS,
            moment=datetime.now(UTC),
        )
        session.commit()


class TestWhatStemsCannotSee:
    def test_paraphrases_sharing_no_stems_become_neighbours(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """The `plan` / `plann` case, which is why this phase exists."""

        memory, proj = project
        focus, near, far = _submit(
            memory,
            proj.id,
            (KnowledgeKind.GOAL, "Make planning accessible without expertise."),
            (KnowledgeKind.GOAL, "Anybody should be able to plan a project."),
            (KnowledgeKind.GOAL, "Hold something until it reaches the moon."),
        )
        _embed(factory, focus, _vector(1.0, 0.05))
        _embed(factory, near, _vector(0.98, 0.2))
        _embed(factory, far, _vector(0.0, 1.0))

        found = ReconciliationService(factory).neighborhood(proj.id, focus.id)

        assert found.measure is NeighborhoodMeasure.SEMANTIC
        ids = [neighbor.item_id for neighbor in found.neighbors]
        assert near.id in ids
        assert far.id not in ids

    def test_a_neighbour_scores_higher_the_closer_it_is(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """Both measures must read the same direction.

        Lexical coverage is higher-is-closer. Cosine *distance* is the reverse,
        and a merge of the two without conversion ranks the least related first
        — silently, because both are floats.
        """

        memory, proj = project
        focus, nearer, further = _submit(
            memory,
            proj.id,
            (KnowledgeKind.GOAL, "Focus statement."),
            (KnowledgeKind.GOAL, "Very close statement."),
            (KnowledgeKind.GOAL, "Somewhat related statement."),
        )
        _embed(factory, focus, _vector(1.0))
        _embed(factory, nearer, _vector(0.99, 0.1))
        _embed(factory, further, _vector(0.8, 0.6))

        found = ReconciliationService(factory).neighborhood(proj.id, focus.id)
        scores = {neighbor.item_id: neighbor.score for neighbor in found.neighbors}

        assert scores[nearer.id] > scores[further.id]
        assert all(0.0 <= score <= 1.0 for score in scores.values())

    def test_a_different_kind_is_never_a_neighbour(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        # A goal and an actor may be worded alike and are not the same thing.
        # Synthesis runs per domain, so a cross-kind neighbour is only ever a
        # way to merge a person into an outcome.
        memory, proj = project
        focus, other = _submit(
            memory,
            proj.id,
            (KnowledgeKind.GOAL, "Make planning accessible."),
            (KnowledgeKind.ACTOR, "Make planning accessible."),
        )
        _embed(factory, focus, _vector(1.0))
        _embed(factory, other, _vector(1.0))

        found = ReconciliationService(factory).neighborhood(proj.id, focus.id)

        assert other.id not in [neighbor.item_id for neighbor in found.neighbors]


class TestSayingWhichMeasureAnswered:
    def test_an_unembedded_corpus_falls_back_to_stems_and_says_so(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """`ADR-0006`: a deployment with no model still works, and says how.

        Falling back is correct. Falling back silently is not — the caller
        would attribute the weaker result to the project.
        """

        memory, proj = project
        focus, _ = _submit(
            memory,
            proj.id,
            (KnowledgeKind.GOAL, "Preserve the original source notes."),
            (KnowledgeKind.GOAL, "Preserve original notes from the source."),
        )

        found = ReconciliationService(factory).neighborhood(proj.id, focus.id)

        assert found.measure is NeighborhoodMeasure.LEXICAL
        assert found.neighbors

    def test_unindexed_and_unrelated_are_different_answers(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """The distinction the whole `measure` field exists for.

        An empty list from an indexed corpus is a fact about the project.
        An empty list from an unindexed one is a fact about the deployment, and
        reading the second as the first is how a product tells somebody their
        statement is unique when nothing ever looked.
        """

        memory, proj = project
        (alone,) = _submit(
            memory, proj.id, (KnowledgeKind.GOAL, "A wholly singular objective here.")
        )

        found = ReconciliationService(factory).neighborhood(proj.id, alone.id)

        assert found.neighbors == ()
        assert found.measure is NeighborhoodMeasure.NONE
        assert not found.searchable

    def test_an_indexed_item_with_nothing_near_it_is_searchable(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        memory, proj = project
        focus, far = _submit(
            memory,
            proj.id,
            (KnowledgeKind.GOAL, "A wholly singular objective."),
            (KnowledgeKind.GOAL, "Entirely unrelated subject matter."),
        )
        _embed(factory, focus, _vector(1.0))
        _embed(factory, far, _vector(0.0, 1.0))

        found = ReconciliationService(factory).neighborhood(proj.id, focus.id)

        assert found.neighbors == ()
        assert found.measure is NeighborhoodMeasure.SEMANTIC
        assert found.searchable


class TestNothingIsWrittenByLooking:
    def test_a_neighbourhood_writes_no_edges_and_no_events(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """Reading is not reconciling. `3a` adds a measure, not a decision."""

        from kae_memory.application.synthesis_service import SynthesisService

        memory, proj = project
        focus, near = _submit(
            memory,
            proj.id,
            (KnowledgeKind.GOAL, "Focus statement."),
            (KnowledgeKind.GOAL, "Close statement."),
        )
        _embed(factory, focus, _vector(1.0))
        _embed(factory, near, _vector(0.99, 0.1))

        ReconciliationService(factory).neighborhood(proj.id, focus.id)

        assert SynthesisService(factory).list_changes(proj.id) == ()
        assert SynthesisService(factory).list_objects(proj.id) == ()
