"""Run durability, idempotency, and transactional atomicity."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.lifecycle import LifecycleState


def test_same_idempotency_key_returns_the_existing_run(factory: sessionmaker[Session]) -> None:
    """Re-submitting a run must not create a second one."""

    service = MemoryService(factory)
    project = service.create_project("Idempotency")

    first = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-batch-1")
    second = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-batch-1")

    assert first.id == second.id
    assert len(service.runs_for_project(project.id)) == 1


def test_replayed_submission_produces_one_set_of_knowledge(
    factory: sessionmaker[Session],
) -> None:
    """AT-007: a replayed submission converges on one run and one result."""

    service = MemoryService(factory)
    project = service.create_project("Replay")
    request = WriteKnowledgeRequest(kind="requirement", content="A claim.", source="model")

    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    service.write_knowledge(run.id, [request])

    replayed = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    assert replayed.id == run.id
    assert replayed.status is RunStatus.SUCCEEDED
    assert len(service.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)) == 1


def test_interrupted_run_is_resumed_by_another_worker(factory: sessionmaker[Session]) -> None:
    """AT-005: recovery uses only durable state."""

    writer = MemoryService(factory)
    project = writer.create_project("Recovery")
    run = writer.start_run(project.id, AgentRole.ARCHITECTURE, "derive-1")

    # The worker stops mid-run without reporting an outcome.
    writer.interrupt_run(run.id, continuation_state={"next_requirement_index": 2})
    del writer

    # A different worker, holding nothing from the first process.
    resumer = MemoryService(factory)
    resumable = resumer.resumable_runs(project.id)
    assert [candidate.id for candidate in resumable] == [run.id]
    assert resumable[0].continuation_state == {"next_requirement_index": 2}

    resumed = resumer.resume_run(run.id)
    assert resumed.status is RunStatus.RUNNING
    assert resumed.attempt_number == 2
    assert resumed.continuation_state == {"next_requirement_index": 2}

    completed = resumer.complete_run(run.id, output_summary={"items_written": 3})
    assert completed.status is RunStatus.SUCCEEDED
    assert completed.output_summary == {"items_written": 3}


def test_failed_run_can_be_retried(factory: sessionmaker[Session]) -> None:
    """A failed run carries typed failure information and remains retryable."""

    service = MemoryService(factory)
    project = service.create_project("Retry")
    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    failed = service.fail_run(run.id, "provider_unavailable", "model provider timed out")
    assert failed.status is RunStatus.FAILED
    assert failed.error_code == "provider_unavailable"
    assert failed.failed_at is not None
    assert failed.is_resumable

    retried = service.resume_run(run.id)
    assert retried.status is RunStatus.RUNNING
    assert retried.attempt_number == 2


def test_knowledge_and_run_status_commit_together(factory: sessionmaker[Session]) -> None:
    """FR-010: no knowledge without an accountable run, no success without outputs."""

    service = MemoryService(factory)
    project = service.create_project("Atomicity")
    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    service.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="model")],
        output_summary={"items_written": 1},
    )

    reloaded = service.get_run(run.id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.SUCCEEDED
    assert reloaded.output_summary == {"items_written": 1}

    items = service.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)
    assert len(items) == 1
    assert str(items[0].current_version.provenance.execution_id) == str(run.id)


def test_failed_write_leaves_no_knowledge_and_no_success(factory: sessionmaker[Session]) -> None:
    """A write that raises mid-transaction must roll the run status back with it."""

    service = MemoryService(factory)
    project = service.create_project("Rollback")
    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    with pytest.raises(Exception):  # noqa: B017 - domain rejects the empty content
        service.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(kind="requirement", content="Valid.", source="model"),
                WriteKnowledgeRequest(kind="requirement", content="   ", source="model"),
            ],
        )

    reloaded = service.get_run(run.id)
    assert reloaded is not None
    assert reloaded.status is RunStatus.RUNNING
    assert service.retrieve_knowledge(project.id, lifecycle=None) == ()


def test_terminal_runs_are_never_reopened(factory: sessionmaker[Session]) -> None:
    """Succeeded is terminal; a new attempt is a new run, not a mutation."""

    service = MemoryService(factory)
    project = service.create_project("Terminal")
    run = service.start_run(project.id, AgentRole.REVIEW, "review-1")
    service.complete_run(run.id)

    with pytest.raises(Exception):  # noqa: B017 - typed domain error
        service.resume_run(run.id)


def test_runs_are_listed_by_status(factory: sessionmaker[Session]) -> None:
    """Execution history is queryable by status without parsing JSON."""

    service = MemoryService(factory)
    project = service.create_project("History")
    first = service.start_run(project.id, AgentRole.REQUIREMENTS, "one")
    service.complete_run(first.id)
    service.start_run(project.id, AgentRole.ARCHITECTURE, "two")

    assert len(service.runs_for_project(project.id)) == 2
    assert len(service.runs_for_project(project.id, RunStatus.SUCCEEDED)) == 1
    assert len(service.runs_for_project(project.id, RunStatus.RUNNING)) == 1
