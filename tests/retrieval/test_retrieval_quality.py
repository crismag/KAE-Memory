"""The retrieval quality guarantees established by T11.

These lock behaviour, not scores. Live quality is measured against the real
corpus by ``scripts/development/evaluate-retrieval.py``, which calls Titan and
therefore cannot run here; what these tests protect is the policy that turned
that measurement into acceptable behaviour — a distance cutoff, project
scoping, version isolation, and staying quiet when nothing is close enough.

Vector geometry is chosen by the test rather than produced by a model. Asserting
on a real embedder's distances would make these tests a record of one model's
opinions on one afternoon, and they would fail on any provider change for
reasons unrelated to the guarantee being checked.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import EmbeddingResult
from kae_memory.application import MemoryService, RetrievalService, WriteKnowledgeRequest
from kae_memory.domain.chunks import EMBEDDING_VERSION, MAX_DISTANCE
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.chunk_repository import ChunkRepository

DIMENSIONS = 1024

# Statements placed at known angles. The angle is the whole point: it fixes the
# cosine distance from a query to each statement, so a threshold assertion is
# about the threshold rather than about how a model happened to feel.
NEAR = "Only an authorised approver may approve a report."
MARGINAL = "A submitter cannot approve their own report."
FAR = "Roughly 25 ministries submit monthly."
ELSEWHERE = "Every important state change is recorded."

ANGLES = {
    NEAR: 0.20,  # distance from the query ≈ 0.02
    MARGINAL: 1.15,  # ≈ 0.59
    FAR: 2.10,  # ≈ 1.50 — beyond any usable cutoff
    ELSEWHERE: 0.20,  # near the query, but in the other project
}
QUERY_ANGLE = 0.0


def _unit(angle: float) -> tuple[float, ...]:
    """A unit vector at ``angle`` in the plane the corpus occupies."""

    return tuple([math.cos(angle), math.sin(angle)] + [0.0] * (DIMENSIONS - 2))


def _out_of_plane() -> tuple[float, ...]:
    """A vector orthogonal to the entire corpus — distance 1.0 to every chunk.

    No angle within the corpus plane would do: the statements are spread across
    it, so every in-plane direction is close to one of them.
    """

    return tuple([0.0, 0.0, 1.0] + [0.0] * (DIMENSIONS - 3))


class GeometryEmbedder:
    """An embedder that places known texts at chosen angles.

    Anything it has not been told about lands far from everything, which is what
    an unrelated query should look like.
    """

    model = "geometry-embedding"
    dimensions = DIMENSIONS

    def __init__(self, angles: dict[str, float] | None = None) -> None:
        self._angles = dict(angles or ANGLES)

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        vectors = []
        for text in texts:
            angle = next(
                (a for statement, a in self._angles.items() if statement in text),
                QUERY_ANGLE if text in self._angles else math.pi / 2,
            )
            vectors.append(_unit(angle))
        return EmbeddingResult(vectors=tuple(vectors), model=self.model, dimensions=self.dimensions)


def _has(hits: Sequence[Any], statement: str) -> bool:
    """Whether any hit carries ``statement``.

    Substring rather than equality: stored chunk text is prefixed with the
    project and kind metadata that retrieval indexes alongside the statement.
    """

    return any(statement in hit.text for hit in hits)


class _QueryAt:
    """An embedder that answers every query from one fixed position.

    ``angle`` places the query in the corpus plane; ``in_plane=False`` puts it
    outside, equidistant from everything.
    """

    model = "geometry-embedding"
    dimensions = DIMENSIONS

    def __init__(self, angle: float = 0.0, *, in_plane: bool = True) -> None:
        self._vector = _unit(angle) if in_plane else _out_of_plane()

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=tuple(self._vector for _ in texts),
            model=self.model,
            dimensions=self.dimensions,
        )


def _embed_project(factory: sessionmaker[Session], project_id: ProjectId) -> None:
    """Give every outstanding chunk its geometric vector."""

    embedder = GeometryEmbedder()
    with factory() as db:
        repository = ChunkRepository(db)
        for chunk in repository.list_needing_embedding(project_id, limit=100):
            result = embedder.embed([chunk.text])
            repository.store_embedding(
                chunk.id,
                result.vectors[0],
                embedder.model,
                embedder.dimensions,
                chunk.created_at,
            )
        db.commit()


@pytest.fixture
def corpus(factory: sessionmaker[Session]) -> tuple[MemoryService, ProjectId, ProjectId]:
    """Two projects, each with knowledge embedded at known angles."""

    memory = MemoryService(factory)
    ministry = memory.create_project("Ministry Reporting", key="t11-ministry")
    other = memory.create_project("KAE-Memory", key="t11-other")

    run = memory.start_run(ministry.id, AgentRole.REQUIREMENTS, "seed")
    memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind="requirement", content=text, source="seed")
            for text in (NEAR, MARGINAL, FAR)
        ],
    )
    other_run = memory.start_run(other.id, AgentRole.REQUIREMENTS, "seed")
    memory.write_knowledge(
        other_run.id,
        [WriteKnowledgeRequest(kind="goal", content=ELSEWHERE, source="seed")],
    )

    _embed_project(factory, ministry.id)
    _embed_project(factory, other.id)
    return memory, ministry.id, other.id


class TestThreshold:
    """Distance decides whether an answer is offered at all."""

    def test_a_result_beyond_the_cutoff_is_dropped_not_ranked_last(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        """The failure this prevents is a confident wrong answer.

        Without a cutoff the furthest chunk in the project still comes back as
        the top hit whenever nothing better exists, and a caller reading rank 1
        has no way to tell that from a real match.
        """

        _, ministry, _ = corpus
        retrieval = RetrievalService(factory, _QueryAt(QUERY_ANGLE))

        hits = retrieval.search(ministry, "who approves", limit=10)

        assert not _has(hits, FAR)

    def test_an_unrelated_query_returns_nothing_at_all(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        """Silence is a valid answer, and the only honest one here."""

        _, ministry, _ = corpus
        # Orthogonal to the entire corpus: distance 1.0 to everything.
        retrieval = RetrievalService(factory, _QueryAt(in_plane=False))

        assert retrieval.search(ministry, "Kubernetes ingress controller", limit=10) == ()

    def test_removing_the_cutoff_returns_the_far_chunk(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        """Proves the cutoff is doing the work, not an empty corpus."""

        _, ministry, _ = corpus
        retrieval = RetrievalService(factory, _QueryAt(QUERY_ANGLE))

        hits = retrieval.search(ministry, "who approves", limit=10, max_distance=None)

        assert _has(hits, FAR)

    def test_the_cutoff_is_the_value_T11_measured(self) -> None:
        """A change here is a change to what the system will assert is true.

        0.85 was measured, not chosen: on the development corpus relevant
        paraphrase matches reach 0.842 and unrelated queries begin at 0.847.
        Anyone moving this should re-run the evaluation harness rather than
        adjust it until a symptom disappears.
        """

        assert MAX_DISTANCE == 0.85


class TestScoping:
    """A hit from the wrong project is worse than no hit."""

    def test_search_never_crosses_a_project_boundary(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        _, _ministry, other = corpus
        retrieval = RetrievalService(factory, _QueryAt(QUERY_ANGLE))

        hits = retrieval.search(other, "who approves", limit=10)

        assert _has(hits, ELSEWHERE), "the other project holds a matching statement"
        assert not _has(hits, NEAR), "a hit leaked in from Ministry Reporting"

    def test_only_the_current_embedding_version_is_ranked(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        """Two models' vectors in one cosine query rank by nothing at all."""

        _, ministry, _ = corpus
        with factory() as db:
            repository = ChunkRepository(db)
            for chunk in repository.list_needing_embedding(
                ministry, limit=100, embedding_version=-1
            ):
                repository.store_embedding(
                    chunk.id,
                    _unit(QUERY_ANGLE),
                    "some-other-model",
                    DIMENSIONS,
                    chunk.created_at,
                    embedding_version=EMBEDDING_VERSION + 1,
                )
            db.commit()
        retrieval = RetrievalService(factory, _QueryAt(QUERY_ANGLE))

        assert retrieval.search(ministry, "who approves", limit=10) == ()


class TestLexicalRemains:
    def test_exact_terminology_is_found_without_any_embedding(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        """Lexical is the floor the system degrades to, not a legacy path."""

        _, ministry, _ = corpus
        retrieval = RetrievalService(factory, _QueryAt(in_plane=False))

        hits = retrieval.find(ministry, "approver", limit=10)

        assert _has(hits, NEAR)


class TestKnownLimitation:
    """The finding T11 could not engineer away.

    On the real corpus the worst relevant match (0.840) and the best unrelated
    match (0.847) leave a 0.005-wide window for a global cutoff. This test
    states that as a fact about the design rather than a footnote in a report,
    so that a later attempt to tighten the threshold fails here first and reads
    why.
    """

    def test_a_marginal_match_and_noise_are_not_separable_by_distance_alone(
        self, factory: sessionmaker[Session], corpus: tuple[Any, ...]
    ) -> None:
        _, ministry, _ = corpus
        # A query sitting between the relevant statement and nothing in
        # particular — the shape of a paraphrase the model only half recognises.
        retrieval = RetrievalService(factory, _QueryAt(1.15))

        marginal = retrieval.search(ministry, "half-recognised paraphrase", limit=10)

        # It comes back, and distance alone offers no basis to prefer it to a
        # near-miss at the same range. Hybrid ranking is the follow-up.
        assert _has(marginal, MARGINAL)
