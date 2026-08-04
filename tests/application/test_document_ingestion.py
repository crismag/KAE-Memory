"""Document ingestion fan-out, end to end and at its limits.

A large file becomes many bounded extractions. What matters is that each span is
stored verbatim so a statement can trace back to it, that limits are
configurable, and that a limit which changed what was read says so — a truncated
ingestion presenting itself as complete is the one outcome worse than refusing.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicExtractionAdapter
from kae_memory.application import (
    IngestionPolicy,
    IngestionService,
    MemoryService,
    ReadinessService,
    policy_from_environment,
)
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

PARAGRAPH = (
    "Staff submit monthly reports for their ministry. Only an authorised "
    "approver may approve a report. A report cannot be published before it is "
    "approved. "
)
"""Includes an actor-cue sentence on purpose.

With no review engine configured only kinds accepted by exactly one area are
classified, so a document of pure requirements would end the chain with zero
area links — correct behaviour, and useless as a demonstration that the chain
closes.
"""


def _document(paragraphs: int) -> str:
    """Return a document long enough to split into several chunks."""

    return "\n\n".join(f"Section {index}. {PARAGRAPH * 30}" for index in range(paragraphs))


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[IngestionService, MemoryService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="ingest")
    return IngestionService(factory, memory), memory, proj.id


class TestFanOut:
    def test_a_document_becomes_one_run_per_chunk(self, project: tuple[Any, ...]) -> None:
        ingestion, _, project_id = project

        result = ingestion.ingest_document(project_id, "spec.md", _document(6))

        assert len(result.chunks) > 1
        assert result.complete
        run_ids = {chunk.run_id for chunk in result.chunks}
        assert len(run_ids) == len(result.chunks), "each chunk gets its own run"

    def test_each_span_is_stored_verbatim(self, project: tuple[Any, ...]) -> None:
        """The stored message is what a statement traces back to.

        Extracting from a copy passed through an API would break the provenance
        chain the product exists to show.
        """

        ingestion, memory, project_id = project
        text = _document(4)

        result = ingestion.ingest_document(project_id, "spec.md", text)

        stored = [memory.get_message(chunk.message_id) for chunk in result.chunks]
        assert all(message is not None for message in stored)
        for message in stored:
            assert message is not None
            assert message.content in text

    def test_runs_are_enqueued_not_executed(self, project: tuple[Any, ...]) -> None:
        """The submitter never owns the execution (ADR-0007)."""

        ingestion, memory, project_id = project

        result = ingestion.ingest_document(project_id, "spec.md", _document(4))

        runs = {run.id: run for run in memory.runs_for_project(project_id)}
        assert all(runs[chunk.run_id].status is RunStatus.PENDING for chunk in result.chunks)

    def test_the_run_carries_its_document_position(self, project: tuple[Any, ...]) -> None:
        ingestion, memory, project_id = project

        result = ingestion.ingest_document(project_id, "spec.md", _document(4))

        run = next(
            r for r in memory.runs_for_project(project_id) if r.id == result.chunks[0].run_id
        )
        assert run.input_context["document"] == "spec.md"
        assert run.input_context["chunk_index"] == 0
        assert run.input_context["chunk_count"] == len(result.chunks)


class TestDepthAndExtentAreConfigurable:
    def test_smaller_chunks_read_the_document_more_closely(self, project: tuple[Any, ...]) -> None:
        """The depth dial: same document, more extractions over less text each."""

        ingestion, _, project_id = project
        text = _document(6)

        coarse = ingestion.ingest_document(
            project_id, "coarse.md", text, IngestionPolicy(target_tokens=900, max_tokens=1000)
        )
        fine = ingestion.ingest_document(
            project_id, "fine.md", text, IngestionPolicy(target_tokens=200, max_tokens=400)
        )

        assert len(fine.chunks) > len(coarse.chunks)

    def test_extent_caps_how_much_is_read(self, project: tuple[Any, ...]) -> None:
        ingestion, _, project_id = project

        result = ingestion.ingest_document(
            project_id, "spec.md", _document(8), IngestionPolicy(max_chunks=2)
        )

        assert len(result.chunks) == 2
        assert result.chunks_available > 2

    def test_truncation_is_never_silent(self, project: tuple[Any, ...]) -> None:
        """The load-bearing guarantee.

        A partial ingestion that looks complete would let someone treat a
        project's knowledge as covering a file it only partly read.
        """

        ingestion, _, project_id = project

        result = ingestion.ingest_document(
            project_id, "spec.md", _document(8), IngestionPolicy(max_chunks=2)
        )

        assert result.complete is False
        assert result.truncated_chunks == result.chunks_available - 2
        assert result.warnings
        assert "max_chunks" in result.warnings[0]

    def test_breadth_travels_with_the_run(self, project: tuple[Any, ...]) -> None:
        """One document's policy stays attached to the runs it created."""

        ingestion, memory, project_id = project

        result = ingestion.ingest_document(
            project_id, "spec.md", _document(3), IngestionPolicy(max_items_per_chunk=5)
        )

        run = next(
            r for r in memory.runs_for_project(project_id) if r.id == result.chunks[0].run_id
        )
        assert run.input_context["max_items"] == 5

    def test_an_incoherent_policy_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            IngestionPolicy(target_tokens=900, max_tokens=100)
        with pytest.raises(ValueError):
            IngestionPolicy(max_chunks=0)

    def test_environment_overrides_apply_without_touching_the_service(self) -> None:
        policy = policy_from_environment(
            {"KAE_INGEST_MAX_CHUNKS": "3", "KAE_INGEST_TARGET_TOKENS": "250"}
        )

        assert policy.max_chunks == 3
        assert policy.target_tokens == 250
        assert policy.max_items_per_chunk == IngestionPolicy().max_items_per_chunk

    def test_an_explicit_policy_still_wins_per_request(self, project: tuple[Any, ...]) -> None:
        """A demo dialling extent down must not need a redeploy."""

        ingestion, _, project_id = project
        deployment = policy_from_environment({"KAE_INGEST_MAX_CHUNKS": "40"})

        result = ingestion.ingest_document(
            project_id, "spec.md", _document(8), IngestionPolicy(max_chunks=1)
        )

        assert deployment.max_chunks == 40
        assert len(result.chunks) == 1


class TestIdempotence:
    def test_resubmitting_a_document_does_not_read_it_twice(self, project: tuple[Any, ...]) -> None:
        ingestion, memory, project_id = project
        text = _document(4)

        first = ingestion.ingest_document(project_id, "spec.md", text)
        second = ingestion.ingest_document(project_id, "spec.md", text)

        assert [c.run_id for c in second.chunks] == [c.run_id for c in first.chunks]
        assert second.replayed is True
        assert len(memory.runs_for_project(project_id)) == len(first.chunks)

    def test_an_edited_document_ingests_only_what_changed(self, project: tuple[Any, ...]) -> None:
        """Content is part of the chunk key, so an edit is not a whole re-read."""

        ingestion, _, project_id = project

        first = ingestion.ingest_document(project_id, "spec.md", _document(4))
        edited = ingestion.ingest_document(
            project_id, "spec.md", _document(4) + "\n\nA new closing section. " + PARAGRAPH * 20
        )

        unchanged = {c.run_id for c in first.chunks} & {c.run_id for c in edited.chunks}
        assert unchanged, "spans that did not change are replayed, not re-read"
        assert len(edited.chunks) > len(first.chunks)


class TestReviewOrdering:
    def test_review_is_not_enqueued_with_the_extractions(self, project: tuple[Any, ...]) -> None:
        """Review is cross-chunk, so it is only meaningful once they finish.

        There is no run-dependency mechanism, so enqueuing it alongside would
        let a worker claim it first and review an empty project.
        """

        ingestion, memory, project_id = project

        ingestion.ingest_document(project_id, "spec.md", _document(4))

        roles = {run.role for run in memory.runs_for_project(project_id)}
        assert roles == {AgentRole.REQUIREMENTS}

    def test_outstanding_runs_tells_a_caller_when_to_review(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        ingestion, _, project_id = project
        ingestion.ingest_document(project_id, "spec.md", _document(3))

        assert ingestion.outstanding_runs(project_id) > 0

        worker = Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter(), None),
            WorkerConfig(worker_id="ingest"),
        )
        while worker.run_once() is not None:
            pass

        assert ingestion.outstanding_runs(project_id) == 0

    def test_the_whole_chain_produces_classified_knowledge(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """Ingest, extract every chunk, then review once."""

        ingestion, memory, project_id = project
        readiness = ReadinessService(factory)
        ingestion.ingest_document(project_id, "spec.md", _document(3))

        worker = Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter(), None),
            WorkerConfig(worker_id="ingest"),
        )
        while worker.run_once() is not None:
            pass

        candidates = memory.retrieve_knowledge(project_id, lifecycle=None)
        assert candidates, "the document produced candidate knowledge"
        for item in candidates:
            memory.confirm_knowledge(item.id)

        ingestion.enqueue_review(project_id, "review-after-ingest")
        while worker.run_once() is not None:
            pass

        assert readiness.area_links(project_id), "review classified what it could"
