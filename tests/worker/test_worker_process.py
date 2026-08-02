"""The worker as a process: the daemon loop and the step executor.

Together these close the gap that made M9's workflow unwalkable — an enqueued
run stayed `pending` because nothing claimed it.
"""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.deterministic import DeterministicExtractionAdapter
from kae_memory.application import MemoryService, ReadinessService
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import Project
from kae_memory.domain.workspace import Message, SessionType
from kae_memory.domain.workspace import Session as WorkSession
from kae_memory.worker.__main__ import build_config, default_worker_id
from kae_memory.worker.execution import (
    AgentStepExecutor,
    MissingRunInputError,
    UnsupportedRoleError,
    default_extractor,
)
from kae_memory.worker.runner import Worker, WorkerConfig

IDEA = (
    "We need a way for ministry staff to submit monthly reports. "
    "Approval should happen before publication, but we have not decided who approves."
)


def _worker(factory: sessionmaker[Session], worker_id: str = "worker-1") -> Worker:
    return Worker(
        factory,
        AgentStepExecutor(factory, DeterministicExtractionAdapter()),
        WorkerConfig(worker_id=worker_id, idle_poll_seconds=0.01),
    )


def _enqueue_requirements(
    memory: MemoryService, factory: sessionmaker[Session]
) -> tuple[Project, WorkSession, Message, AgentRun]:
    project = memory.create_project("Reporting")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    message = memory.record_message(project.id, session.id, IDEA).message
    run = memory.enqueue_run(
        project.id,
        AgentRole.REQUIREMENTS,
        "extract-1",
        session_id=session.id,
        input_context={"message_id": str(message.id)},
    )
    return project, session, message, run


def test_an_enqueued_run_is_claimed_and_executed(factory: sessionmaker[Session]) -> None:
    """The gap this closes: enqueue used to leave a run pending for ever."""

    memory = MemoryService(factory)
    project, _session, _message, run = _enqueue_requirements(memory, factory)
    assert memory.get_run(run.id).status is RunStatus.PENDING  # type: ignore[union-attr]

    executed = _worker(factory).run_once()

    assert executed is not None
    assert executed.id == run.id
    assert executed.status is RunStatus.SUCCEEDED
    assert memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)


def test_extraction_traces_back_to_the_source_message(factory: sessionmaker[Session]) -> None:
    """The provenance chain the product exists to show.

    The executor reads the stored message rather than text passed through the
    API, so every candidate points at the words the user actually submitted.
    """

    memory = MemoryService(factory)
    _project, _session, message, run = _enqueue_requirements(memory, factory)

    _worker(factory).run_once()

    items = memory.knowledge_produced_by(run.id)
    assert items
    links = memory.provenance_for_item(items[0].id)
    assert any(link.message_id == message.id for link in links)
    assert any(link.agent_run_id == run.id for link in links)


def test_a_run_without_input_fails_typed(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project = memory.create_project("No input")
    memory.enqueue_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    executed = _worker(factory).run_once()

    assert executed is not None
    assert executed.status is RunStatus.FAILED
    assert executed.error_code == MissingRunInputError.error_code


def test_all_three_authorised_roles_are_executable(factory: sessionmaker[Session]) -> None:
    """FR-009 authorises exactly three roles, and the worker now executes each.

    ``UnsupportedRoleError`` remains as the guard for a fourth role appearing
    without an execution path — it should never be reachable through the enum.
    """

    memory = MemoryService(factory)
    project = memory.create_project("Roles")
    for index, role in enumerate(AgentRole):
        memory.enqueue_run(project.id, role, f"role-{index}", input_context={"source_text": IDEA})

    worker = _worker(factory)
    executed = [worker.run_once() for _ in AgentRole]

    assert len(list(AgentRole)) == 3
    assert all(run is not None and run.status is RunStatus.SUCCEEDED for run in executed)
    assert UnsupportedRoleError.error_code == "role_not_implemented"


def test_architecture_consumes_only_confirmed_knowledge(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project, session, _message, _run = _enqueue_requirements(memory, factory)
    worker = _worker(factory)
    worker.run_once()

    # Nothing confirmed yet: no decisions, and that is the correct answer.
    memory.enqueue_run(project.id, AgentRole.ARCHITECTURE, "derive-1", session_id=session.id)
    empty = worker.run_once()
    assert empty is not None
    assert (empty.output_summary or {})["reason"] == "no_confirmed_knowledge"

    for item in memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED):
        memory.confirm_knowledge(item.id)

    memory.enqueue_run(project.id, AgentRole.ARCHITECTURE, "derive-2", session_id=session.id)
    derived = worker.run_once()

    assert derived is not None
    assert derived.status is RunStatus.SUCCEEDED
    assert (derived.output_summary or {})["consumed_items"] > 0


def test_a_replayed_step_does_not_duplicate_knowledge(factory: sessionmaker[Session]) -> None:
    """At-least-once execution means a step can run twice."""

    memory = MemoryService(factory)
    _project, _session, _message, run = _enqueue_requirements(memory, factory)
    executor = AgentStepExecutor(factory, DeterministicExtractionAdapter())
    _worker(factory).run_once()

    written = len(memory.knowledge_produced_by(run.id))
    replayed = executor(memory.get_run(run.id), {})  # type: ignore[arg-type]

    assert replayed.done
    assert replayed.output_summary == {"items_written": written, "replayed": True}
    assert len(memory.knowledge_produced_by(run.id)) == written


def test_the_loop_drains_the_queue_then_stops_when_asked(factory: sessionmaker[Session]) -> None:
    """`run_forever` honours idle_poll_seconds, declared since M7 and unused."""

    memory = MemoryService(factory)
    project = memory.create_project("Queue")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    for index in range(3):
        message = memory.record_message(project.id, session.id, IDEA).message
        memory.enqueue_run(
            project.id,
            AgentRole.REQUIREMENTS,
            f"extract-{index}",
            session_id=session.id,
            input_context={"message_id": str(message.id)},
        )

    worker = _worker(factory)
    polls: list[float] = []

    def sleep(seconds: float) -> None:
        polls.append(seconds)
        worker.request_stop()

    processed = worker.run_forever(sleep=sleep)

    assert processed == 3
    assert polls == [0.01], "the loop should idle exactly once, after draining the queue"


def test_the_whole_asynchronous_workflow_moves_readiness(factory: sessionmaker[Session]) -> None:
    """Enqueue, execute, confirm, assign, recalculate — without driving an agent by hand."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project, _session, _message, _run = _enqueue_requirements(memory, factory)

    before = readiness.calculate(project.id)
    _worker(factory).run_once()

    # An area only counts knowledge of a kind it accepts, so each item goes to an
    # area that admits it. Note what this exposes: `unknown` — a recorded gap —
    # belongs to no area at all, which is right. A gap is not coverage.
    areas = {"goal": "problem_and_value", "requirement": "functional_requirements"}
    confirmed = []
    for item in memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED):
        confirmed.append(memory.confirm_knowledge(item.id))
        area = areas.get(item.kind)
        if area:
            readiness.assign_area(project.id, item.id, area)

    after = readiness.calculate(project.id)

    assert confirmed
    assert any(item.kind == "unknown" for item in confirmed), "the idea names an open question"
    assert after.score > before.score
    assert after.knowledge_revision > before.knowledge_revision


def test_the_worker_identity_distinguishes_two_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lease owner is how a run tells its claimant from an impostor."""

    monkeypatch.delenv("KAE_WORKER_ID", raising=False)
    generated = default_worker_id()

    monkeypatch.setenv("KAE_WORKER_ID", "explicit-worker")

    assert str(__import__("os").getpid()) in generated
    assert default_worker_id() == "explicit-worker"
    assert build_config().worker_id == "explicit-worker"


def test_the_default_extractor_needs_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The demonstrable path must not depend on a provider being reachable."""

    monkeypatch.delenv("KAE_EXTRACTION", raising=False)

    assert isinstance(default_extractor(), DeterministicExtractionAdapter)
