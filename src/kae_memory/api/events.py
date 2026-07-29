"""Server-Sent Events for run progress.

ADR-0009 names `GET /runs/{id}/events` and states the constraint that shapes
this file: **SSE improves the demonstration; correctness must never depend on an
uninterrupted browser connection.** Current run state is always recoverable
through an ordinary `GET /v1/runs/{id}`, and nothing here is the only way to
learn anything.

The stream is a *view* of durable state, not a channel the worker publishes to.
It polls CockroachDB and emits when something changed. That is deliberate: a
push channel would need the worker to know about connected browsers, which
couples the durable execution path to the presentation layer and gives the run
a second place to fail.

The generator is synchronous. Starlette iterates sync generators in a worker
thread, so blocking database calls stay off the event loop without an async
database driver.
"""

import json
import time
from collections.abc import Generator
from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.memory_service import MemoryService
from kae_memory.domain.execution import TERMINAL_STATUSES, AgentRun
from kae_memory.domain.identifiers import AgentRunId

from .schemas import RunResponse


@dataclass(frozen=True, slots=True)
class StreamConfig:
    """How the stream paces itself.

    ``max_seconds`` exists because a browser tab left open overnight should not
    hold a database connection forever. Reaching it closes the stream cleanly and
    the client reconnects — EventSource does that on its own.
    """

    poll_seconds: float = 1.0
    heartbeat_seconds: float = 15.0
    max_seconds: float = 300.0


def format_event(name: str, payload: dict[str, object]) -> str:
    """Return one SSE frame."""

    return f"event: {name}\ndata: {json.dumps(payload)}\n\n"


def _fingerprint(run: AgentRun) -> tuple[object, ...]:
    """Return what counts as a change worth sending.

    Status, attempt, and checkpoint — the three things a user watching a recovery
    demonstration is actually watching. A heartbeat timestamp changing every ten
    seconds is not progress, and emitting it would bury the events that are.
    """

    return (
        run.status.value,
        run.attempt_number,
        json.dumps(run.continuation_state or {}, sort_keys=True),
        run.error_code,
    )


def run_events(
    session_factory: sessionmaker[DbSession],
    run_id: AgentRunId,
    config: StreamConfig | None = None,
) -> Generator[str, None, None]:
    """Yield SSE frames for one run until it reaches a terminal status.

    Emits the current state immediately, so a client that connects late is never
    left waiting for a change that already happened.
    """

    settings = config or StreamConfig()
    memory = MemoryService(session_factory)

    run = memory.get_run(run_id)
    if run is None:
        yield format_event("error", {"code": "run_not_found", "run_id": str(run_id)})
        return

    yield format_event("run", dict(RunResponse.of(run).model_dump(mode="json")))
    if run.status in TERMINAL_STATUSES:
        yield format_event("close", {"reason": "terminal"})
        return

    previous = _fingerprint(run)
    started = time.monotonic()
    last_sent = started

    while time.monotonic() - started < settings.max_seconds:
        time.sleep(settings.poll_seconds)
        current = memory.get_run(run_id)
        if current is None:  # pragma: no cover - a run is never deleted
            yield format_event("error", {"code": "run_not_found", "run_id": str(run_id)})
            return

        fingerprint = _fingerprint(current)
        if fingerprint != previous:
            previous = fingerprint
            last_sent = time.monotonic()
            yield format_event("run", dict(RunResponse.of(current).model_dump(mode="json")))
            if current.status in TERMINAL_STATUSES:
                yield format_event("close", {"reason": "terminal"})
                return
        elif time.monotonic() - last_sent >= settings.heartbeat_seconds:
            # A comment frame. Keeps proxies from closing an idle connection
            # without the client having to treat silence as an event.
            last_sent = time.monotonic()
            yield ": heartbeat\n\n"

    yield format_event("close", {"reason": "timeout"})
