"""M7: compute is disposable.

A worker dies mid-run and another finishes what it started, using durable state
alone. Nothing here reconstructs anything from the dead process.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.workspace_repositories import AgentRunRepository
from kae_memory.worker import LeaseLostError, StepResult, Worker, WorkerConfig

START = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class Clock:
    """A hand-cranked clock, so lease expiry is exercised without waiting."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _three_step_executor(kill_after: int | None = None) -> Any:
    """A run of three steps, optionally dying partway through.

    The step number lives in the checkpoint, so resuming reads where it got to
    from the database rather than from any process state.
    """

    executed: list[int] = []

    def execute(run: Any, checkpoint: dict[str, Any]) -> StepResult:
        step = int(checkpoint.get("step", 0)) + 1
        if kill_after is not None and step > kill_after:
            raise _WorkerDied
        executed.append(step)
        return StepResult(
            checkpoint={"step": step},
            done=step >= 3,
            output_summary={"steps_completed": step} if step >= 3 else None,
        )

    execute.executed = executed  # type: ignore[attr-defined]
    return execute


class _WorkerDied(BaseException):
    """Simulates hard death: not an Exception, so the worker cannot record it."""


def _queue_run(service: MemoryService, project_id: ProjectId, key: str) -> Any:
    """Enqueue a run for a worker to claim, as an API submission would."""

    return service.enqueue_run(project_id, AgentRole.REQUIREMENTS, key)


def test_a_killed_worker_is_replaced_and_the_run_completes(
    factory: sessionmaker[Session],
) -> None:
    """AT-005. The proof M7 exists for."""

    clock = Clock()
    service = MemoryService(factory, clock=clock)
    project = service.create_project("Recovery", key="recovery")
    _queue_run(service, project.id, "extract-1")

    # --- Worker one claims it and dies after the second step ---------------
    dying = _three_step_executor(kill_after=2)
    worker_one = Worker(factory, dying, WorkerConfig(worker_id="worker-1"), clock=clock)
    claimed = worker_one.claim()
    assert claimed is not None
    assert claimed.lease is not None
    assert claimed.lease.owner == "worker-1"
    assert claimed.lease.token == 1

    with pytest.raises(_WorkerDied):
        worker_one.execute(claimed)

    assert dying.executed == [1, 2]
    del worker_one, dying

    # --- The lease is still held; nothing may steal it yet ------------------
    worker_two = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-2"), clock=clock
    )
    assert worker_two.claim() is None, "a live lease must not be reclaimable"

    # --- The lease expires -------------------------------------------------
    clock.advance(31)
    survivor = _three_step_executor()
    worker_three = Worker(factory, survivor, WorkerConfig(worker_id="worker-3"), clock=clock)
    reclaimed = worker_three.claim()

    assert reclaimed is not None
    assert reclaimed.lease is not None
    assert reclaimed.lease.owner == "worker-3"
    assert reclaimed.lease.token == 2, "reclaiming advances the fencing token"
    assert reclaimed.continuation_state == {"step": 2}, "resumes from the durable checkpoint"

    finished = worker_three.execute(reclaimed)

    assert finished.status is RunStatus.SUCCEEDED
    assert survivor.executed == [3], "only the unfinished step ran again"
    assert finished.output_summary == {"steps_completed": 3}


def test_a_superseded_worker_cannot_write(factory: sessionmaker[Session]) -> None:
    """Fencing. A recovered worker must not overwrite the newer owner's work."""

    clock = Clock()
    service = MemoryService(factory, clock=clock)
    project = service.create_project("Fencing", key="fencing")
    _queue_run(service, project.id, "extract-1")

    stale_worker = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-1"), clock=clock
    )
    stale_run = stale_worker.claim()
    assert stale_run is not None

    clock.advance(31)
    new_worker = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-2"), clock=clock
    )
    assert new_worker.claim() is not None

    # The original worker wakes up holding a superseded token.
    assert stale_worker.heartbeat(stale_run) is False
    with pytest.raises(LeaseLostError):
        stale_worker.execute(stale_run)

    with factory() as db:
        stored = AgentRunRepository(db).get(stale_run.id)
    assert stored is not None
    assert stored.lease is not None
    assert stored.lease.owner == "worker-2", "the newer owner is untouched"
    assert stored.lease.token == 2


def test_heartbeat_extends_the_lease_without_changing_the_token(
    factory: sessionmaker[Session],
) -> None:
    """Renewal continues a claim; it does not create a new one."""

    clock = Clock()
    service = MemoryService(factory, clock=clock)
    project = service.create_project("Heartbeat", key="heartbeat")
    _queue_run(service, project.id, "extract-1")

    worker = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-1"), clock=clock
    )
    run = worker.claim()
    assert run is not None
    assert run.lease is not None
    original_expiry = run.lease.expires_at

    clock.advance(10)
    assert worker.heartbeat(run) is True

    with factory() as db:
        stored = AgentRunRepository(db).get(run.id)
    assert stored is not None and stored.lease is not None
    assert stored.lease.expires_at > original_expiry
    assert stored.lease.token == 1, "renewal keeps the token"

    # A competitor still cannot take it, because the lease was renewed.
    clock.advance(25)
    other = Worker(factory, _three_step_executor(), WorkerConfig(worker_id="worker-2"), clock=clock)
    assert other.claim() is None


def test_release_makes_the_run_immediately_claimable(factory: sessionmaker[Session]) -> None:
    """Graceful shutdown does not make the next worker wait out the expiry."""

    clock = Clock()
    service = MemoryService(factory, clock=clock)
    project = service.create_project("Shutdown", key="shutdown")
    _queue_run(service, project.id, "extract-1")

    worker = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-1"), clock=clock
    )
    run = worker.claim()
    assert run is not None
    worker.request_stop()
    stopped = worker.execute(run)

    assert stopped.continuation_state == {"step": 1}, "the completed step was checkpointed"

    successor = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-2"), clock=clock
    )
    resumed = successor.claim()

    assert resumed is not None, "released immediately, not after 30 seconds"
    assert resumed.lease is not None
    assert resumed.lease.owner == "worker-2"
    assert resumed.continuation_state == {"step": 1}


def test_retry_backs_off_then_abandons(factory: sessionmaker[Session]) -> None:
    """A permanently failing run surfaces instead of consuming the worker."""

    clock = Clock()
    service = MemoryService(factory, clock=clock)
    project = service.create_project("Retry", key="retry")
    _queue_run(service, project.id, "extract-1")

    def always_fails(run: Any, checkpoint: dict[str, Any]) -> StepResult:
        raise RuntimeError("provider exploded")

    config = WorkerConfig(worker_id="worker-1", max_attempts=3, backoff_base_seconds=5.0)
    worker = Worker(factory, always_fails, config, clock=clock)

    first = worker.run_once()
    assert first is not None
    assert first.status is RunStatus.FAILED
    assert first.error_code == "RuntimeError"
    assert first.next_attempt_at == clock.now + timedelta(seconds=10), "backoff is scheduled"

    # Not claimable until the backoff elapses.
    assert worker.claim() is None
    clock.advance(11)

    second = worker.run_once()
    assert second is not None
    assert second.status is RunStatus.ABANDONED, "budget exhausted on the third attempt"
    assert second.error_code == "retry_budget_exhausted"

    clock.advance(3600)
    assert worker.claim() is None, "an abandoned run is terminal and never reclaimed"


def test_claim_is_ordered_and_returns_nothing_when_idle(factory: sessionmaker[Session]) -> None:
    """Oldest first, and an empty queue is not an error."""

    clock = Clock()
    service = MemoryService(factory, clock=clock)
    project = service.create_project("Ordering", key="ordering")
    first = _queue_run(service, project.id, "one")
    clock.advance(1)
    second = _queue_run(service, project.id, "two")

    worker = Worker(
        factory, _three_step_executor(), WorkerConfig(worker_id="worker-1"), clock=clock
    )
    claimed = worker.claim()

    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.id != second.id

    idle = Worker(factory, _three_step_executor(), WorkerConfig(worker_id="worker-2"), clock=clock)
    idle_project = service.create_project("Empty", key="empty")
    assert idle_project is not None
    # worker-2 can still take the second run, but once both are held nothing is left.
    assert idle.claim() is not None
    assert idle.claim() is None
