"""Graceful shutdown — the M10 half of ADR-0013's deferred signal handling.

`graceful_shutdown_seconds` was declared in `WorkerConfig` from M7 and unused
until now. What it buys is speed of recovery, not correctness: an ungraceful kill
still recovers through lease expiry, it just waits the full thirty seconds first.
"""

import signal
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.deterministic import DeterministicExtractionAdapter
from kae_memory.application import MemoryService
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.workspace import SessionType
from kae_memory.worker.__main__ import install_signal_handlers
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import StepResult, Worker, WorkerConfig

IDEA = "Ministry staff submit monthly reports. Approval happens before publication."


def _worker(factory: sessionmaker[Session]) -> Worker:
    return Worker(
        factory,
        AgentStepExecutor(factory, DeterministicExtractionAdapter()),
        WorkerConfig(worker_id="w1", idle_poll_seconds=0.01, graceful_shutdown_seconds=5.0),
    )


def test_sigterm_asks_the_worker_to_stop_rather_than_killing_it(
    factory: sessionmaker[Session],
) -> None:
    """systemd sends SIGTERM before forcing termination; something must catch it."""

    worker = _worker(factory)
    original = signal.getsignal(signal.SIGTERM)
    cancel = install_signal_handlers(worker, 5.0)
    try:
        assert not worker.stop_requested()

        signal.raise_signal(signal.SIGTERM)

        assert worker.stop_requested()
    finally:
        # Cancelling matters: the deadline timer calls os._exit, so a leaked one
        # would kill this process five seconds later, mid-suite.
        cancel()
        signal.signal(signal.SIGTERM, original)


def test_a_stopping_worker_finishes_its_step_and_stops_claiming(
    factory: sessionmaker[Session],
) -> None:
    """Stop means stop accepting work, not abandon the work in hand."""

    memory = MemoryService(factory)
    project = memory.create_project("Shutdown")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    for index in range(2):
        message = memory.record_message(project.id, session.id, IDEA).message
        memory.enqueue_run(
            project.id,
            AgentRole.REQUIREMENTS,
            f"extract-{index}",
            session_id=session.id,
            input_context={"message_id": str(message.id)},
        )

    worker = _worker(factory)
    first = worker.run_once()
    worker.request_stop()
    processed = worker.run_forever(sleep=lambda _seconds: None)

    assert first is not None
    assert first.status is RunStatus.SUCCEEDED, "the claimed step completed"
    assert processed == 0, "no further run is claimed once stopping"
    pending = memory.runs_for_project(project.id, RunStatus.PENDING)
    assert len(pending) == 1, "the unclaimed run stays claimable by another worker"


def test_a_released_run_is_immediately_claimable_by_another_worker(
    factory: sessionmaker[Session],
) -> None:
    """What graceful shutdown buys: no waiting out the lease.

    An ungraceful kill leaves the lease held until it expires — correct, but
    thirty seconds slower, and that gap is the whole difference on stage.
    """

    memory = MemoryService(factory)
    project = memory.create_project("Handover")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    message = memory.record_message(project.id, session.id, IDEA).message
    run = memory.enqueue_run(
        project.id,
        AgentRole.ARCHITECTURE,
        "derive-1",
        session_id=session.id,
        input_context={"message_id": str(message.id)},
    )

    # A step that checkpoints and then asks the worker to stop, so the run is
    # released mid-flight rather than completed.
    holder: list[Worker] = []

    def step(run: AgentRun, checkpoint: dict[str, Any]) -> StepResult:
        holder[0].request_stop()
        return StepResult(checkpoint={**checkpoint, "step": 1}, done=False)

    stopping = Worker(factory, step, WorkerConfig(worker_id="stopping", idle_poll_seconds=0.01))
    holder.append(stopping)
    stopping.run_once()

    replacement = _worker(factory)
    claimed = replacement.claim()

    assert claimed is not None, "the replacement claims without waiting for expiry"
    assert str(claimed.id) == str(run.id)
    assert claimed.continuation_state == {"step": 1}
