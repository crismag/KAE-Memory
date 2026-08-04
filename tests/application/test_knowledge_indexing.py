"""Knowledge written through production paths must become searchable.

The defect these cover: `knowledge_items` rows committed with no
`knowledge_chunks`, so every search returned an empty list for knowledge that
was present. `RetrievalService.chunk_knowledge` existed and was called by
nothing in `src/` — only by tests and by fixture preparation, which is why the
one project that looked healthy looked healthy.

Every test here writes through a supported application path. None calls
`chunk_knowledge` to make its own assertion pass; doing so would recreate the
exact condition that hid the defect.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicEmbeddingAdapter, DeterministicExtractionAdapter
from kae_memory.application import (
    MemoryService,
    ReadinessService,
    RetrievalService,
    WriteKnowledgeRequest,
)
from kae_memory.domain.chunks import EmbeddingState
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.workspace import SessionType
from kae_memory.persistence.chunk_repository import ChunkRepository
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

DISTINCTIVE = "Ministry approvers must hold a delegated signing mandate."


@pytest.fixture
def services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, RetrievalService, ProjectId]:
    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
    ReadinessService(factory).install_template()
    project = memory.create_project("Ministry Reporting", key="indexing")
    return memory, retrieval, project.id


def _write(memory: MemoryService, project_id: ProjectId, key: str, *texts: str) -> tuple[Any, ...]:
    """Write through the production boundary. No chunking call anywhere."""

    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="requirement", content=t, source="seed") for t in texts],
    )


class TestNewKnowledgeIsSearchable:
    def test_written_knowledge_is_found_without_a_chunking_call(
        self, services: tuple[Any, ...]
    ) -> None:
        """Test 1. The defect, stated as the behaviour that must hold."""

        memory, retrieval, project_id = services

        _write(memory, project_id, "w1", DISTINCTIVE)

        hits = retrieval.find(project_id, "delegated signing mandate")
        assert hits, "knowledge written through the service must be searchable"
        assert "delegated signing mandate" in hits[0].text

    def test_chunks_commit_with_the_knowledge(
        self, factory: sessionmaker[Session], services: tuple[Any, ...]
    ) -> None:
        """One transaction. There is no window where knowledge exists unindexed."""

        memory, _, project_id = services

        item = _write(memory, project_id, "w2", DISTINCTIVE)[0]

        with factory() as db:
            chunks = ChunkRepository(db).list_for_knowledge(item.id)
        assert chunks
        assert all(chunk.knowledge_id == item.id for chunk in chunks)

    def test_the_worker_path_indexes_too(self, factory: sessionmaker[Session]) -> None:
        """Test 5. The acquisition path, not a hand-built fixture."""

        memory = MemoryService(factory)
        retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
        ReadinessService(factory).install_template()
        project = memory.create_project("Acquisition", key="indexing-worker")
        session = memory.open_session(project.id, SessionType.DISCOVERY)
        message = memory.record_message(
            project.id,
            session.id,
            content="Staff submit monthly reports. Approval must precede publication.",
            idempotency_key="acq-1",
        )
        memory.enqueue_run(
            project.id,
            AgentRole.REQUIREMENTS,
            "acq-run-1",
            input_context={"message_id": str(message.message.id)},
        )

        Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter(), None),
            WorkerConfig(worker_id="indexer"),
        ).run_once()

        assert retrieval.indexing_status(project.id).chunks > 0
        assert retrieval.find(project.id, "approval")


class TestUnindexedIsNotNoMatch:
    def test_status_separates_the_two_conditions(self, services: tuple[Any, ...]) -> None:
        """Test 2. An empty list means one of two very different things."""

        memory, retrieval, project_id = services

        empty = retrieval.indexing_status(project_id)
        assert empty.knowledge_items == 0
        assert empty.unindexed is False, "an empty project is not an unindexed one"

        _write(memory, project_id, "w3", DISTINCTIVE)
        indexed = retrieval.indexing_status(project_id)
        assert indexed.knowledge_items == 1
        assert indexed.lexically_searchable is True
        assert indexed.unindexed is False

    def test_knowledge_without_chunks_reports_unindexed(
        self, factory: sessionmaker[Session], services: tuple[Any, ...]
    ) -> None:
        """Simulates the state every project was in before this fix."""

        memory, retrieval, project_id = services
        item = _write(memory, project_id, "w4", DISTINCTIVE)[0]

        with factory() as db:
            ChunkRepository(db).delete_for_knowledge(item.id)
            db.commit()

        status = retrieval.indexing_status(project_id)
        assert status.knowledge_items == 1
        assert status.chunks == 0
        assert status.unindexed is True


class TestEmbeddingMayLag:
    def test_lexical_search_works_before_any_embedding(self, services: tuple[Any, ...]) -> None:
        """Test 3. The hybrid lifecycle: lexical now, vectors later."""

        memory, retrieval, project_id = services

        _write(memory, project_id, "w5", DISTINCTIVE)

        status = retrieval.indexing_status(project_id)
        assert status.embedded_chunks == 0
        assert status.embedding_pending > 0
        assert retrieval.find(project_id, "mandate"), "lexical must not wait for vectors"

    def test_chunks_start_pending_and_are_retryable(
        self, factory: sessionmaker[Session], services: tuple[Any, ...]
    ) -> None:
        memory, _, project_id = services
        item = _write(memory, project_id, "w6", DISTINCTIVE)[0]

        with factory() as db:
            chunks = ChunkRepository(db).list_for_knowledge(item.id)
        assert all(chunk.state is EmbeddingState.PENDING for chunk in chunks)
        assert all(chunk.needs_embedding for chunk in chunks)

    def test_embedding_completes_without_duplicating_chunks(
        self, services: tuple[Any, ...]
    ) -> None:
        """Test 6. A resumed embedding pass must not fork the index."""

        memory, retrieval, project_id = services
        _write(memory, project_id, "w7", DISTINCTIVE)
        before = retrieval.indexing_status(project_id).chunks

        retrieval.embed_pending(project_id)
        retrieval.embed_pending(project_id)

        after = retrieval.indexing_status(project_id)
        assert after.chunks == before
        assert after.embedded_chunks == before


class TestUpdatesRefreshTheIndex:
    def test_corrected_text_replaces_stale_text(self, services: tuple[Any, ...]) -> None:
        """Test 4. Stale wording must stop being findable as current."""

        memory, retrieval, project_id = services
        item = _write(memory, project_id, "w8", "Approvers must hold a paper mandate.")[0]
        assert retrieval.find(project_id, "paper")

        memory.correct_knowledge(item.id, DISTINCTIVE, source="interview")

        assert not retrieval.find(project_id, "paper"), "the old wording is gone"
        assert retrieval.find(project_id, "delegated signing mandate")

    def test_a_correction_does_not_accumulate_chunks(self, services: tuple[Any, ...]) -> None:
        memory, retrieval, project_id = services
        item = _write(memory, project_id, "w9", "Approvers must hold a paper mandate.")[0]
        before = retrieval.indexing_status(project_id).chunks

        memory.correct_knowledge(item.id, DISTINCTIVE, source="interview")
        memory.correct_knowledge(item.id, "Approvers must be named individuals.", source="i")

        assert retrieval.indexing_status(project_id).chunks == before

    def test_a_refreshed_chunk_is_marked_for_re_embedding(
        self, factory: sessionmaker[Session], services: tuple[Any, ...]
    ) -> None:
        """The vector still describes the old words, so it must be retried."""

        memory, retrieval, project_id = services
        item = _write(memory, project_id, "w10", "Approvers must hold a paper mandate.")[0]
        retrieval.embed_pending(project_id)

        memory.correct_knowledge(item.id, DISTINCTIVE, source="interview")

        with factory() as db:
            chunks = ChunkRepository(db).list_for_knowledge(item.id)
        assert all(chunk.state is EmbeddingState.STALE for chunk in chunks)
        assert all(chunk.needs_embedding for chunk in chunks)


class TestBackfillIsSafe:
    def test_chunking_an_already_indexed_item_is_idempotent(
        self, services: tuple[Any, ...]
    ) -> None:
        """The backfill runs over projects that are partly indexed."""

        memory, retrieval, project_id = services
        project = memory.get_project(project_id)
        assert project is not None
        item = _write(memory, project_id, "w11", DISTINCTIVE)[0]
        before = retrieval.indexing_status(project_id).chunks

        retrieval.chunk_knowledge(item, project.name)
        retrieval.chunk_knowledge(item, project.name)

        assert retrieval.indexing_status(project_id).chunks == before
