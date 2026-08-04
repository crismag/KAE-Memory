"""``python -m kae_memory.worker``.

The runnable local worker M9 owns (ADR-0013, amended 2026-07-28). It claims
queued runs from CockroachDB and executes them, so the asynchronous product
workflow completes without anyone driving it by hand.

Deliberately minimal. Deployment packaging, supervisor configuration, production
signal handling, automatic replacement, secrets, and logging operations are M10.
What is here is what the workflow needs: a process, a loop, and a deterministic
execution path that works without credentials.
"""

import logging
import os
import signal
import socket
import threading
from collections.abc import Callable
from types import FrameType

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.persistence import providers

from .execution import AgentStepExecutor, default_extractor, default_reviewer
from .runner import Worker, WorkerConfig

_LOGGER = logging.getLogger("kae_memory.worker")


def default_worker_id() -> str:
    """Return a worker identity that is distinguishable in the lease column.

    Host and process, because two workers on one machine must not share an
    identity: the lease owner is how a run tells its claimant from an impostor.
    """

    return os.environ.get("KAE_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"


def build_config() -> WorkerConfig:
    """Return the worker configuration from the environment."""

    return WorkerConfig(
        worker_id=default_worker_id(),
        lease_seconds=int(os.environ.get("KAE_LEASE_DURATION_SECONDS", "30")),
        idle_poll_seconds=float(os.environ.get("KAE_WORKER_POLL_SECONDS", "2.0")),
    )


def install_signal_handlers(worker: Worker, deadline_seconds: float) -> Callable[[], None]:
    """Ask the worker to stop on SIGTERM or SIGINT, and bound how long it may take.

    systemd sends `SIGTERM` before forcing termination, and ADR-0007's graceful
    path — stop accepting work, checkpoint, release the lease — only runs if
    something catches it. Without this the run waits out its full lease expiry
    instead of being released immediately.

    The deadline is the second half of the promise. A step that hangs must not
    hold the shutdown open past `graceful_shutdown_seconds`, so the process exits
    and lets the lease expire the slow way rather than never exiting at all.

    Returns a canceller. It has to be a callable rather than the timer itself:
    the timer does not exist until a signal arrives, so returning it at install
    time always returned ``None`` and left the deadline uncancellable — which
    killed the test process that installed a handler and then finished normally.
    """

    pending: list[threading.Timer] = []

    def handle(signum: int, _frame: FrameType | None) -> None:
        if worker.stop_requested():
            # A second signal means someone is impatient, or systemd escalated.
            _LOGGER.warning("second signal %s, exiting now", signum)
            os._exit(1)

        _LOGGER.info("signal %s received, finishing the current step", signum)
        worker.request_stop()
        timer = threading.Timer(deadline_seconds, _expire, args=(deadline_seconds,))
        timer.daemon = True
        timer.start()
        pending.append(timer)

    for received in (signal.SIGTERM, signal.SIGINT):
        signal.signal(received, handle)

    def cancel() -> None:
        for timer in pending:
            timer.cancel()
        pending.clear()

    return cancel


def _expire(deadline_seconds: float) -> None:  # pragma: no cover - timing path
    _LOGGER.error("graceful shutdown exceeded %.0fs, exiting", deadline_seconds)
    os._exit(1)


def main() -> None:
    """Run the worker until interrupted."""

    logging.basicConfig(
        level=os.environ.get("KAE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    database = providers.resolve()
    _LOGGER.info("persistence: %s", database.describe())

    engine = create_engine(database.url, pool_pre_ping=True)
    factory = sessionmaker(engine)
    config = build_config()
    executor = AgentStepExecutor(factory, default_extractor(), default_reviewer())
    worker = Worker(factory, executor, config)

    cancel_shutdown_deadline = install_signal_handlers(worker, config.graceful_shutdown_seconds)
    _LOGGER.info(
        "worker %s polling every %.1fs, graceful shutdown %.0fs",
        config.worker_id,
        config.idle_poll_seconds,
        config.graceful_shutdown_seconds,
    )
    try:
        processed = worker.run_forever()
    except KeyboardInterrupt:  # pragma: no cover - only when no handler is installed
        worker.request_stop()
        processed = 0
    finally:
        cancel_shutdown_deadline()
        engine.dispose()

    _LOGGER.info("worker %s completed %d run(s)", config.worker_id, processed)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
