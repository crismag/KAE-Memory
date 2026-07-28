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
import socket

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .execution import AgentStepExecutor, default_extractor
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


def main() -> None:
    """Run the worker until interrupted."""

    logging.basicConfig(
        level=os.environ.get("KAE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    url = os.environ.get("KAE_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "KAE_DATABASE_URL is not set. Copy .env.example and set it, for example "
            "'cockroachdb+psycopg://user:password@host:26257/kae?sslmode=verify-full'."
        )

    engine = create_engine(url, pool_pre_ping=True)
    factory = sessionmaker(engine)
    config = build_config()
    worker = Worker(factory, AgentStepExecutor(factory, default_extractor()), config)

    _LOGGER.info("worker %s polling every %.1fs", config.worker_id, config.idle_poll_seconds)
    try:
        processed = worker.run_forever()
    except KeyboardInterrupt:
        # Ctrl-C during a step: ask the worker to stop, then let the current
        # step finish and release its lease. SIGTERM handling and
        # `graceful_shutdown_seconds` belong to a supervised deployment, which
        # is M10.
        worker.request_stop()
        _LOGGER.info("worker %s stopping", config.worker_id)
        processed = 0
    finally:
        engine.dispose()

    _LOGGER.info("worker %s completed %d run(s)", config.worker_id, processed)


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
