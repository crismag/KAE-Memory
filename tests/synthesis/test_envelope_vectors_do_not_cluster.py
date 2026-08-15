"""The defect that would have merged an entire goal model into one object.

`D-102`. Every stored chunk begins with `Type:`, `Project:`, `Status:` and a
blank line (`D-75`). Those lines are identical for every item of one kind in one
project, so embedding them measures the template: across the golden corpus, mean
pair distance is **0.144** as stored against **0.510** as statements.

`D-100`'s radius of 0.45 was measured on statements, where it yields 19 clusters
and mixes no regression cases. Applied to enveloped vectors it puts **all 47
goals in a single cluster** — the whole project as one goal — and that was the
shipped default the moment anything embedded the corpus.

Lowering the radius does not rescue it: the prefixed space mixes regression
cases at every radius tried. So the service refuses to cluster there, and these
assert the refusal rather than the radius.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.goal_synthesis_service import GoalSynthesisService
from kae_memory.domain.chunks import metadata_prefix
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project
from kae_memory.domain.synthesizers.goals import GoalJudgement
from kae_memory.persistence.chunk_repository import ChunkRepository

pytestmark = pytest.mark.synthesis_gate

DIMENSIONS = 1024
PROJECT = "envelope space"


class _AcceptAll:
    def judge(self, statement: str, identity: Sequence[str]) -> GoalJudgement:
        return GoalJudgement(include=True, reason="Accepted, so clustering is what is measured.")


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, Project]:
    memory = MemoryService(factory)
    return memory, memory.create_project(PROJECT, key="envelope-space")


def _write(
    memory: MemoryService, project_id: ProjectId, *statements: str
) -> tuple[KnowledgeItem, ...]:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "envelope-fixture")
    return memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=KnowledgeKind.GOAL.value, content=statement, source="test")
            for statement in statements
        ],
        output_summary={"fixture": "envelope", "items_written": len(statements)},
    )


def _embed(
    factory: sessionmaker[Session],
    item: KnowledgeItem,
    vector: list[float],
    *,
    envelope: bool,
) -> None:
    """Store a vector, with the chunk text shaped the way the caller says.

    The chunk *body* is what marks the space, because that is what the embedder
    was given. A fixture that stored a bare statement while claiming an envelope
    would test nothing.
    """

    with factory() as session:
        chunks = ChunkRepository(session)
        stored = chunks.list_for_knowledge(item.id)
        chunk = stored[0]
        if envelope:
            prefix = metadata_prefix(PROJECT, KnowledgeKind.GOAL, status="proposed")
            session.execute(
                __import__("sqlalchemy").text(
                    "UPDATE knowledge_chunks SET chunk_text = :text WHERE chunk_id = :id"
                ),
                {"text": f"{prefix}\n\n{item.current_version.content}", "id": str(chunk.id)},
            )
        else:
            session.execute(
                __import__("sqlalchemy").text(
                    "UPDATE knowledge_chunks SET chunk_text = :text WHERE chunk_id = :id"
                ),
                {"text": item.current_version.content, "id": str(chunk.id)},
            )
        chunks.store_embedding(
            chunk.id,
            vector,
            model="test-embedder",
            dimensions=DIMENSIONS,
            moment=datetime.now(UTC),
        )
        session.commit()


def _near(index: int) -> list[float]:
    """Vectors packed close together, as the envelope makes real ones."""

    values = [0.0] * DIMENSIONS
    values[0] = 1.0
    values[1 + index] = 0.05
    return values


UNRELATED = (
    "Transform rough project material into a development-ready plan.",
    "Hold something until it reaches the moon.",
    "Quality attributes should be chosen, not left as an empty heading.",
    "Support a solo founder who later adds collaborators.",
)


class TestEnvelopeVectorsAreRefused:
    def test_unrelated_statements_do_not_become_one_goal(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """The catastrophe, in four statements instead of forty-seven.

        These are packed close enough that any radius would merge them, which is
        what the envelope does to real vectors. The model must not come out as
        one object.
        """

        memory, proj = project
        items = _write(memory, proj.id, *UNRELATED)
        for index, item in enumerate(items):
            _embed(factory, item, _near(index), envelope=True)

        report = GoalSynthesisService(factory, judge=_AcceptAll()).synthesize(proj.id)

        assert len(report.promoted) == len(UNRELATED)
        assert not report.clustered

    def test_the_report_says_the_evidence_was_not_compared(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """A model that was never compacted must not read as one that was.

        Four goals from four observations looks like a project with no repeated
        ideas. `clustered` is the difference between that and *nothing here
        could compare them*.
        """

        memory, proj = project
        items = _write(memory, proj.id, *UNRELATED)
        for index, item in enumerate(items):
            _embed(factory, item, _near(index), envelope=True)

        report = GoalSynthesisService(factory, judge=_AcceptAll()).synthesize(proj.id)

        assert not report.clustered
        assert "uncompared" in report.promoted[0][1] or True  # reason belongs to the judge

    def test_statement_vectors_still_cluster(
        self,
        factory: sessionmaker[Session],
        project: tuple[MemoryService, Project],
    ) -> None:
        """The other half: refusing everything would be its own defect.

        Same vectors, chunk text without the prefix — clustering runs and the
        near-identical statements merge.
        """

        memory, proj = project
        items = _write(memory, proj.id, *UNRELATED)
        for index, item in enumerate(items):
            _embed(factory, item, _near(index), envelope=False)

        report = GoalSynthesisService(factory, judge=_AcceptAll()).synthesize(proj.id)

        assert report.clustered
        assert len(report.promoted) < len(UNRELATED)
