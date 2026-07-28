"""Run progress over Server-Sent Events.

Driven by stepping the generator by hand rather than by sleeping in a thread:
the interesting behaviour is *what is emitted and when*, and a test that waits on
wall-clock timing would be slow and flaky without testing anything more.
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api.events import StreamConfig, format_event, run_events
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import AgentRunId

FAST = StreamConfig(poll_seconds=0.01, heartbeat_seconds=0.02, max_seconds=2.0)


def _frame(raw: str) -> tuple[str, dict[str, object]]:
    """Return the event name and payload of one frame."""

    name = raw.split("event: ", 1)[1].split("\n", 1)[0]
    data = raw.split("data: ", 1)[1].strip()
    return name, dict(json.loads(data))


def test_a_frame_is_well_formed() -> None:
    assert format_event("run", {"a": 1}) == 'event: run\ndata: {"a": 1}\n\n'


def test_an_unknown_run_yields_an_error_frame(factory: sessionmaker[Session]) -> None:
    frames = list(run_events(factory, AgentRunId("11111111-1111-1111-1111-111111111111"), FAST))

    name, payload = _frame(frames[0])
    assert name == "error"
    assert payload["code"] == "run_not_found"


def test_current_state_is_emitted_immediately(factory: sessionmaker[Session]) -> None:
    """A client that connects late must not wait for a change that already happened."""

    memory = MemoryService(factory)
    project = memory.create_project("Stream")
    run = memory.enqueue_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    stream = run_events(factory, run.id, FAST)
    name, payload = _frame(next(stream))
    stream.close()

    assert name == "run"
    assert payload["status"] == "pending"
    assert payload["id"] == str(run.id)


def test_a_terminal_run_emits_once_and_closes(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project = memory.create_project("Finished")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="test")]
    )

    frames = [_frame(raw) for raw in run_events(factory, run.id, FAST)]

    assert [name for name, _ in frames] == ["run", "close"]
    assert frames[0][1]["status"] == "succeeded"
    assert frames[1][1]["reason"] == "terminal"


def test_a_status_change_is_emitted_then_the_stream_closes(
    factory: sessionmaker[Session],
) -> None:
    """The stream is a view of durable state, not a channel the worker writes to."""

    memory = MemoryService(factory)
    project = memory.create_project("Progress")
    run = memory.start_run(project.id, AgentRole.ARCHITECTURE, "derive-1")

    stream = run_events(factory, run.id, FAST)
    first = _frame(next(stream))
    assert first[1]["status"] == "running"

    memory.interrupt_run(run.id, continuation_state={"next_requirement_index": 2})
    interrupted = _frame(next(stream))

    memory.resume_run(run.id)
    memory.complete_run(run.id, output_summary={"written": 1})
    frames = [_frame(raw) for raw in stream]

    assert interrupted[1]["status"] == "interrupted"
    assert interrupted[1]["continuation_state"] == {"next_requirement_index": 2}
    assert [name for name, _ in frames][-1] == "close"
    assert frames[-1][1]["reason"] == "terminal"


def test_an_unchanged_run_produces_heartbeats_not_duplicate_state(
    factory: sessionmaker[Session],
) -> None:
    """A heartbeat timestamp changing is not progress, and must not look like it."""

    memory = MemoryService(factory)
    project = memory.create_project("Idle")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    stream = run_events(factory, run.id, FAST)
    next(stream)
    following = [next(stream) for _ in range(3)]
    stream.close()

    assert all(raw == ": heartbeat\n\n" for raw in following)


def test_the_stream_stops_at_its_own_deadline(factory: sessionmaker[Session]) -> None:
    """A tab left open overnight must not hold a connection forever."""

    memory = MemoryService(factory)
    project = memory.create_project("Deadline")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    config = StreamConfig(poll_seconds=0.01, heartbeat_seconds=10.0, max_seconds=0.05)

    frames = list(run_events(factory, run.id, config))

    assert _frame(frames[-1]) == ("close", {"reason": "timeout"})


def test_the_endpoint_streams_event_stream_content(factory: sessionmaker[Session]) -> None:
    """The HTTP surface ADR-0009 names, end to end."""

    from kae_memory.api import create_app

    memory = MemoryService(factory)
    project = memory.create_project("HTTP stream")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="test")]
    )

    with TestClient(create_app(factory)) as client:
        response = client.get(f"/v1/runs/{run.id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert "event: run" in response.text
    assert '"status": "succeeded"' in response.text


def test_run_state_is_readable_without_the_stream(factory: sessionmaker[Session]) -> None:
    """Correctness never depends on an uninterrupted browser connection."""

    from kae_memory.api import create_app

    memory = MemoryService(factory)
    project = memory.create_project("No stream")
    run = memory.enqueue_run(project.id, AgentRole.REQUIREMENTS, "extract-1")

    with TestClient(create_app(factory)) as client:
        body = client.get(f"/v1/runs/{run.id}").json()

    assert body["status"] == "pending"
