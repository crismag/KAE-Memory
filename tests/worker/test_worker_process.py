"""The worker as a process: the daemon loop and the step executor.

Together these close the gap that made M9's workflow unwalkable — an enqueued
run stayed `pending` because nothing claimed it.
"""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory import runtime_profile
from kae_memory.agents.deterministic import DeterministicExtractionAdapter
from kae_memory.agents.provider import ProviderConfigurationError
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
    default_reviewer,
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


def test_every_authorised_role_is_executable(factory: sessionmaker[Session]) -> None:
    """Four roles since N46 added discovery, and the worker executes each.

    Counted from the enum rather than written as a number, so adding a role
    fails here only when it has no execution path — which is the thing worth
    failing on. ``UnsupportedRoleError`` remains the guard for exactly that.
    """

    memory = MemoryService(factory)
    project = memory.create_project("Roles")
    for index, role in enumerate(AgentRole):
        memory.enqueue_run(project.id, role, f"role-{index}", input_context={"source_text": IDEA})

    worker = _worker(factory)
    executed = [worker.run_once() for _ in AgentRole]

    assert len(list(AgentRole)) == len(executed), "every role has an execution path"
    assert all(run is not None and run.status is RunStatus.SUCCEEDED for run in executed)
    assert UnsupportedRoleError.error_code == "role_not_implemented"


def test_architecture_consumes_only_confirmed_knowledge(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project, session, _message, _run = _enqueue_requirements(memory, factory)
    worker = _worker(factory)
    worker.run_once()

    # Extraction drained, so it asked for the review that classifies what it
    # wrote. Drain that too before enqueuing anything else, or the next
    # `run_once` claims the review and this test reads its summary instead.
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

    # Four, not three. The last extraction to finish sees an empty queue and
    # asks for the review that assigns what all three wrote to areas — the step
    # without which a project holding hundreds of statements reports 0% with
    # every area empty. One review for three extractions, because they share an
    # idempotency key.
    assert processed == 4
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


def test_a_misspelled_extractor_refuses_instead_of_giving_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`D-173`: the whitelist `KAE_REVIEW` already had.

    The slip is cheap to make and expensive to notice — the run succeeds,
    knowledge is written, and nothing says the model an operator configured was
    never called.
    """

    monkeypatch.delenv(runtime_profile.VARIABLE, raising=False)
    monkeypatch.setenv("KAE_EXTRACTION", "bedrok")

    with pytest.raises(ProviderConfigurationError) as error:
        default_extractor()

    assert "bedrok" in str(error.value)


def test_a_blank_extractor_setting_still_means_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike `KAE_REVIEW=`, which means `off`.

    Extraction is not optional, so an exported-but-empty variable — the ordinary
    result of a shell script setting one conditionally — must not fail a worker
    that would otherwise run the documented default.
    """

    monkeypatch.delenv(runtime_profile.VARIABLE, raising=False)
    monkeypatch.setenv("KAE_EXTRACTION", "  ")

    assert isinstance(default_extractor(), DeterministicExtractionAdapter)


def test_the_runtime_profile_refuses_the_worker_providers_it_does_not_permit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`D-172`: the profile is worth having only where a provider is built.

    Both worker choice points, and both directions — `offline` refuses the
    hosted adapter, `production` refuses the fixture that ranks at chance.
    """

    monkeypatch.setenv(runtime_profile.VARIABLE, runtime_profile.OFFLINE)
    monkeypatch.setenv("KAE_EXTRACTION", "bedrock")
    monkeypatch.setenv("KAE_REVIEW", "bedrock")

    with pytest.raises(runtime_profile.ProfileViolation):
        default_extractor()
    with pytest.raises(runtime_profile.ProfileViolation):
        default_reviewer()

    monkeypatch.setenv(runtime_profile.VARIABLE, runtime_profile.PRODUCTION)
    monkeypatch.setenv("KAE_EXTRACTION", "deterministic")
    monkeypatch.setenv("KAE_REVIEW", "deterministic")

    with pytest.raises(runtime_profile.ProfileViolation):
        default_extractor()
    with pytest.raises(runtime_profile.ProfileViolation):
        default_reviewer()


def test_a_disabled_reviewer_is_not_a_reach_the_profile_rules_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`KAE_REVIEW=off` survives `production`.

    Refusing it would be the runtime profile ruling on product scope rather than
    on what this deployment may reach — a capability nobody built reaches
    nothing.
    """

    monkeypatch.setenv(runtime_profile.VARIABLE, runtime_profile.PRODUCTION)
    monkeypatch.setenv("KAE_REVIEW", "off")

    assert default_reviewer() is None


def test_extraction_asks_for_the_review_that_makes_readiness_mean_anything(
    factory: sessionmaker[Session],
) -> None:
    """The defect this closes: knowledge written, never classified, 0% reported.

    A deployment accrued twenty-five knowledge revisions and zero review runs,
    because `enqueue_review` was left for "the caller" to decide and no caller
    existed. Review assigns each item to a discovery area and readiness counts
    per area, so without it a project holding hundreds of accurate statements
    reports every area empty.

    Nothing here calls `enqueue_review`. That is the assertion.
    """

    memory = MemoryService(factory)
    project, _session, _message, _run = _enqueue_requirements(memory, factory)
    worker = _worker(factory)

    worker.run_once()  # extraction

    queued = [r for r in memory.runs_for_project(project.id) if r.role is AgentRole.REVIEW]
    assert len(queued) == 1, "extraction should have asked for exactly one review"
    assert queued[0].status is RunStatus.PENDING

    reviewed = worker.run_once()
    assert reviewed is not None
    assert reviewed.role is AgentRole.REVIEW
    assert reviewed.status is RunStatus.SUCCEEDED

    summary = reviewed.output_summary or {}

    # `areas_assigned` is deliberately not asserted here. This worker has no
    # review adapter, so it classifies offline from the statement's own wording
    # (`EPI-3b`) — how well it does that is the subject of its own tests, not of
    # the trigger this one is about.
    assert summary["classification"] == "offline_by_content"

    # What this test does assert about readiness: the review recalculated it,
    # inside the same run. A review that assigns areas and leaves the snapshot
    # untouched has changed nothing anyone can see — the deployed project sat at
    # snapshot revision 0 against a current revision of 25 and reported
    # "0% · not_started", accurate about a state twenty-five revisions old.
    assert "readiness_percentage" in summary
    assert "readiness_status" in summary


def test_several_extractions_produce_one_review_not_one_each(
    factory: sessionmaker[Session],
) -> None:
    """Review is cross-chunk, so it is worth doing once, at the end.

    Chunk 7 and chunk 31 may conflict and neither run can see the other. A
    review per chunk would be a model call per chunk and would still miss what
    only the whole set shows.
    """

    memory = MemoryService(factory)
    project = memory.create_project("Fan-out")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    for index in range(3):
        message = memory.record_message(project.id, session.id, IDEA).message
        memory.enqueue_run(
            project.id,
            AgentRole.REQUIREMENTS,
            f"chunk-{index}",
            session_id=session.id,
            input_context={"message_id": str(message.id)},
        )

    worker = _worker(factory)
    for _ in range(4):
        worker.run_once()

    reviews = [r for r in memory.runs_for_project(project.id) if r.role is AgentRole.REVIEW]
    assert len(reviews) == 1, f"three extractions should yield one review, got {len(reviews)}"


def test_no_review_is_asked_for_while_extraction_is_still_running(
    factory: sessionmaker[Session],
) -> None:
    """Reviewing a half-extracted project would classify half of it.

    The check is by identity rather than status: the run asking has not been
    marked terminal yet — the worker does that after this returns — so counting
    non-terminal runs would always find itself.
    """

    memory = MemoryService(factory)
    project = memory.create_project("Still going")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    for index in range(2):
        message = memory.record_message(project.id, session.id, IDEA).message
        memory.enqueue_run(
            project.id,
            AgentRole.REQUIREMENTS,
            f"chunk-{index}",
            session_id=session.id,
            input_context={"message_id": str(message.id)},
        )

    worker = _worker(factory)
    worker.run_once()  # one of two — the other is still pending

    reviews = [r for r in memory.runs_for_project(project.id) if r.role is AgentRole.REVIEW]
    assert reviews == [], "a review asked for now would classify a half-extracted project"
