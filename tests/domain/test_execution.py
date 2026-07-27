"""Agent run status transitions and invariants."""

from datetime import UTC, datetime

import pytest

from kae_memory.domain.errors import DomainInvariantError, InvalidRunTransitionError
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus, ensure_run_transition
from kae_memory.domain.identifiers import AgentRunId, ProjectId

MOMENT = datetime(2026, 7, 27, tzinfo=UTC)


def _run(status: RunStatus = RunStatus.PENDING) -> AgentRun:
    return AgentRun(
        id=AgentRunId("run-1"),
        project_id=ProjectId("project-1"),
        role=AgentRole.REQUIREMENTS,
        idempotency_key="extract-1",
        status=status,
    )


def test_new_run_is_pending_and_not_terminal() -> None:
    run = _run()

    assert run.status is RunStatus.PENDING
    assert not run.is_terminal
    assert not run.is_resumable


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (RunStatus.PENDING, RunStatus.RUNNING),
        (RunStatus.PENDING, RunStatus.CANCELLED),
        (RunStatus.RUNNING, RunStatus.SUCCEEDED),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.INTERRUPTED),
        (RunStatus.INTERRUPTED, RunStatus.RUNNING),
        (RunStatus.INTERRUPTED, RunStatus.ABANDONED),
        (RunStatus.FAILED, RunStatus.RUNNING),
        (RunStatus.FAILED, RunStatus.ABANDONED),
    ],
)
def test_allowed_transitions(start: RunStatus, target: RunStatus) -> None:
    ensure_run_transition(start, target)


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (RunStatus.SUCCEEDED, RunStatus.RUNNING),
        (RunStatus.CANCELLED, RunStatus.RUNNING),
        (RunStatus.ABANDONED, RunStatus.RUNNING),
        (RunStatus.PENDING, RunStatus.SUCCEEDED),
        (RunStatus.INTERRUPTED, RunStatus.SUCCEEDED),
    ],
)
def test_rejected_transitions(start: RunStatus, target: RunStatus) -> None:
    with pytest.raises(InvalidRunTransitionError):
        ensure_run_transition(start, target)


def test_resuming_increments_the_attempt_number() -> None:
    """A continuation chain stays visible; a first start does not inflate it."""

    started = _run().start(MOMENT)
    assert started.attempt_number == 1

    resumed = started.interrupt().start(MOMENT)
    assert resumed.attempt_number == 2
    assert resumed.status is RunStatus.RUNNING


def test_interrupt_preserves_committed_continuation_state() -> None:
    running = _run().start(MOMENT)

    interrupted = running.interrupt({"cursor": 7})

    assert interrupted.status is RunStatus.INTERRUPTED
    assert interrupted.continuation_state == {"cursor": 7}
    assert interrupted.is_resumable


def test_abandon_is_distinct_from_cancel() -> None:
    """Cancellation is a human act; abandonment is retry-budget exhaustion."""

    failed = _run().start(MOMENT).fail(MOMENT, "provider_error", "timed out")
    abandoned = failed.abandon(MOMENT, "3 attempts exhausted")

    assert abandoned.status is RunStatus.ABANDONED
    assert abandoned.error_code == "retry_budget_exhausted"
    assert abandoned.is_terminal

    cancelled = _run().cancel()
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.is_terminal


def test_succeeded_run_is_terminal() -> None:
    succeeded = _run().start(MOMENT).succeed(MOMENT, {"items": 2})

    assert succeeded.is_terminal
    assert succeeded.output_summary == {"items": 2}
    with pytest.raises(InvalidRunTransitionError):
        succeeded.start(MOMENT)


def test_rejects_blank_idempotency_key() -> None:
    with pytest.raises(DomainInvariantError, match="idempotency key"):
        AgentRun(
            id=AgentRunId("run-1"),
            project_id=ProjectId("project-1"),
            role=AgentRole.REVIEW,
            idempotency_key="   ",
        )


def test_rejects_naive_timestamps() -> None:
    with pytest.raises(DomainInvariantError, match="timezone-aware"):
        AgentRun(
            id=AgentRunId("run-1"),
            project_id=ProjectId("project-1"),
            role=AgentRole.REVIEW,
            idempotency_key="review-1",
            started_at=datetime(2026, 7, 27),
        )


def test_rejects_non_positive_attempt_number() -> None:
    with pytest.raises(DomainInvariantError, match="attempt number"):
        AgentRun(
            id=AgentRunId("run-1"),
            project_id=ProjectId("project-1"),
            role=AgentRole.REVIEW,
            idempotency_key="review-1",
            attempt_number=0,
        )
