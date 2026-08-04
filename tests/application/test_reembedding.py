"""Migrating a corpus between embedding spaces.

The failure this exists to prevent is not a crash. It is a search that keeps
working and returns confident nonsense, because vectors from two models were
ranked against each other in one cosine query.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import (
    DeterministicEmbeddingAdapter,
    EmbeddingProviderUnavailableError,
    EmbeddingResult,
)
from kae_memory.application import (
    MemoryService,
    ReembeddingService,
    RetrievalService,
    WriteKnowledgeRequest,
)
from kae_memory.domain.chunks import EMBEDDING_VERSION, EmbeddingState
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.chunk_repository import ChunkRepository

PREVIOUS_VERSION = EMBEDDING_VERSION - 1

STATEMENTS = [
    "A report cannot be published before it is approved.",
    "Only an authorised approver may approve a report.",
    "A submitter cannot approve their own report.",
]


class StubEmbedder:
    """An embedder whose successes and failures are chosen by the test."""

    model = "stub-embedding"

    def __init__(self, dimensions: int = 1024, fail_on: Sequence[str] = ()) -> None:
        self.dimensions = dimensions
        self._fail_on = tuple(fail_on)
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        self.calls += 1
        for text in texts:
            if any(marker in text for marker in self._fail_on):
                raise EmbeddingProviderUnavailableError("provider refused this chunk")
        vector = tuple([1.0] + [0.0] * (self.dimensions - 1))
        return EmbeddingResult(
            vectors=tuple(vector for _ in texts), model=self.model, dimensions=self.dimensions
        )


@pytest.fixture
def seeded(factory: sessionmaker[Session]) -> tuple[MemoryService, ProjectId]:
    """A project whose chunks are embedded in the *previous* space."""

    memory = MemoryService(factory)
    project = memory.create_project("Ministry Reporting", key="reembed")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "seed")
    memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="requirement", content=t, source="seed") for t in STATEMENTS],
    )
    # Embed at the old version and mark embedded, exactly as a corpus written
    # before the model changed would look.
    old = DeterministicEmbeddingAdapter()
    with factory() as db:
        chunks = ChunkRepository(db).list_needing_embedding(project.id, limit=100)
        for chunk in chunks:
            result = old.embed([chunk.text])
            ChunkRepository(db).store_embedding(
                chunk.id,
                result.vectors[0],
                old.model,
                old.dimensions,
                chunk.created_at,
                embedding_version=PREVIOUS_VERSION,
            )
        db.commit()
    return memory, project.id


def _chunks(factory: sessionmaker[Session], project_id: ProjectId) -> list[Any]:
    with factory() as db:
        return list(
            ChunkRepository(db).list_needing_embedding(project_id, limit=100, embedding_version=-1)
        )


class TestVersionIsolation:
    def test_search_never_ranks_another_version(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        """The whole reason the version exists.

        The corpus is embedded at the previous version. Semantic search at the
        current version must return nothing rather than ranking vectors from a
        space it does not share.
        """

        _, project_id = seeded
        retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())

        assert retrieval.search(project_id, STATEMENTS[0], max_distance=None) == ()

    def test_lexical_search_is_unaffected(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        """Degrading to lexical is the point; going dark is not."""

        _, project_id = seeded
        retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())

        assert retrieval.find(project_id, "approval")


class TestSelection:
    def test_an_embedded_old_version_chunk_is_selected(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        """State alone would leave the whole corpus behind.

        These chunks are `embedded` and entirely correct about themselves. They
        simply hold vectors from a space the current search no longer queries.
        """

        _, project_id = seeded

        with factory() as db:
            outstanding = ChunkRepository(db).list_needing_embedding(project_id, limit=100)

        assert len(outstanding) == len(STATEMENTS)
        assert all(chunk.state is EmbeddingState.EMBEDDED for chunk in outstanding)

    def test_a_current_version_chunk_is_not_selected(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        service = ReembeddingService(factory, StubEmbedder())

        service.migrate(project_id)

        assert service.outstanding(project_id) == 0

    def test_selection_can_be_scoped_to_one_project(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        memory, project_id = seeded
        other = memory.create_project("Other", key="reembed-other")
        run = memory.start_run(other.id, AgentRole.REQUIREMENTS, "other-seed")
        memory.write_knowledge(
            run.id, [WriteKnowledgeRequest(kind="rule", content="Unrelated.", source="s")]
        )
        service = ReembeddingService(factory, StubEmbedder())

        service.migrate(project_id)

        assert service.outstanding(project_id) == 0
        assert service.outstanding(other.id) > 0


class TestSuccessIsAtomic:
    def test_a_success_updates_vector_version_model_and_state_together(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        embedder = StubEmbedder()

        ReembeddingService(factory, embedder).migrate(project_id)

        for chunk in _chunks(factory, project_id):
            assert chunk.embedding_version == EMBEDDING_VERSION
            assert chunk.embedding_model == embedder.model
            assert chunk.embedding_dimensions == embedder.dimensions
            assert chunk.state is EmbeddingState.EMBEDDED

    def test_the_report_names_the_model_that_produced_the_vectors(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded

        report = ReembeddingService(factory, StubEmbedder()).migrate(project_id)

        assert report.model == "stub-embedding"
        assert report.target_version == EMBEDDING_VERSION
        assert report.complete


class TestFailureIsolation:
    def test_a_failed_chunk_does_not_stop_the_others(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        embedder = StubEmbedder(fail_on=["Only an authorised"])

        report = ReembeddingService(factory, embedder).migrate(project_id)

        assert report.attempted == len(STATEMENTS)
        assert report.succeeded == len(STATEMENTS) - 1
        assert report.failed == 1

    def test_a_failure_does_not_destroy_the_previous_vector(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        """The provider is called before anything is overwritten.

        A run that cleared the vector first would leave a chunk unsearchable in
        both spaces on any provider hiccup.
        """

        _, project_id = seeded
        embedder = StubEmbedder(fail_on=["Only an authorised"])
        ReembeddingService(factory, embedder).migrate(project_id)

        failed = [c for c in _chunks(factory, project_id) if c.state is EmbeddingState.FAILED]
        assert len(failed) == 1
        assert failed[0].embedding_model == "deterministic-embedding"
        assert failed[0].embedding_version == PREVIOUS_VERSION

    def test_failures_are_reported_with_a_diagnosable_cause(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded

        report = ReembeddingService(factory, StubEmbedder(fail_on=["Only an authorised"])).migrate(
            project_id
        )

        assert len(report.failures) == 1
        assert report.failures[0].error_code == "embedding_provider_unavailable"
        assert report.failures[0].chunk_id
        assert not report.complete

    def test_a_failed_chunk_is_retried_by_a_later_run(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        ReembeddingService(factory, StubEmbedder(fail_on=["Only an authorised"])).migrate(
            project_id
        )

        second = ReembeddingService(factory, StubEmbedder()).migrate(project_id)

        assert second.succeeded == 1
        assert second.complete


class TestResume:
    def test_a_rerun_processes_only_what_is_outstanding(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        service = ReembeddingService(factory, StubEmbedder())

        first = service.migrate(project_id, max_chunks=1)
        second = service.migrate(project_id)

        assert first.attempted == 1
        assert second.attempted == len(STATEMENTS) - 1
        assert second.complete

    def test_a_completed_migration_rerun_does_nothing(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        service = ReembeddingService(factory, StubEmbedder())
        service.migrate(project_id)

        again = service.migrate(project_id)

        assert again.attempted == 0
        assert again.complete


class TestConcurrency:
    def test_two_runners_cannot_process_the_same_chunk(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        """Claiming is a compare-and-set, so exactly one runner wins.

        Simulated by claiming directly, which is what the losing runner's
        attempt resolves to.
        """

        _, project_id = seeded
        with factory() as db:
            chunk = ChunkRepository(db).list_needing_embedding(project_id, limit=1)[0]
            first = ChunkRepository(db).claim(chunk.id, chunk.state)
            second = ChunkRepository(db).claim(chunk.id, chunk.state)
            db.commit()

        assert first is True
        assert second is False, "the second runner must not also win the claim"

    def test_a_claimed_chunk_is_not_offered_to_another_runner(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        _, project_id = seeded
        with factory() as db:
            repository = ChunkRepository(db)
            chunk = repository.list_needing_embedding(project_id, limit=1)[0]
            repository.claim(chunk.id, chunk.state)
            db.commit()

        service = ReembeddingService(factory, StubEmbedder())
        report = service.migrate(project_id)

        assert report.attempted == len(STATEMENTS) - 1
        assert report.remaining == 0, "a claimed chunk is not outstanding work"

    def test_stranded_claims_are_recoverable(
        self, factory: sessionmaker[Session], seeded: tuple[Any, ...]
    ) -> None:
        """A crashed runner leaves claims behind; recovery is explicit.

        An automatic timeout would race with a slow-but-alive runner and embed
        the same chunk twice.
        """

        _, project_id = seeded
        with factory() as db:
            repository = ChunkRepository(db)
            chunk = repository.list_needing_embedding(project_id, limit=1)[0]
            repository.claim(chunk.id, chunk.state)
            db.commit()

        service = ReembeddingService(factory, StubEmbedder())
        released = service.release_claims(project_id)

        assert released == 1
        assert service.migrate(project_id).complete
