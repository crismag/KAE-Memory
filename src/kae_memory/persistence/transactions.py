"""Transaction execution, per provider.

A unit of work is the same everywhere; what differs is what a database does
under contention. CockroachDB runs serializable isolation and reports conflicts
as SQLSTATE 40001, expecting the caller to retry. PostgreSQL at its default
isolation does not raise that at all.

Each strategy is wrong for the other engine. Retrying where retries cannot
happen is dead code implying a guarantee the engine never made; not retrying
where they are routine turns ordinary contention into an error a user sees. So
the strategy is chosen by the provider, and services call one interface.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import sleep
from typing import Protocol

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

SERIALIZATION_FAILURE = "40001"
"""SQLSTATE for a serialization failure. Retryable; nothing else here is."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry policy for SQLSTATE 40001 serialization failures."""

    max_attempts: int = 3
    initial_delay_seconds: float = 0.05

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must not be negative")


DEFAULT_RETRY_POLICY = RetryPolicy()


class TransactionRunner(Protocol):
    """Runs one complete unit of work."""

    def run[ResultT](self, operation: Callable[[Session], ResultT]) -> ResultT:
        """Execute ``operation`` in a transaction and commit it."""
        ...


@dataclass(frozen=True, slots=True)
class PostgreSQLTransactionRunner:
    """One attempt, no retries.

    PostgreSQL's default isolation cannot produce the serialization failure the
    retrying runner exists for. A deployment raising isolation to serializable
    should select the retrying runner instead: the difference is real, and it
    belongs in configuration rather than in a loop that usually does nothing.
    """

    session_factory: sessionmaker[Session]

    def run[ResultT](self, operation: Callable[[Session], ResultT]) -> ResultT:
        with self.session_factory() as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except Exception:
                session.rollback()
                raise


@dataclass(frozen=True, slots=True)
class CockroachDBRetryingTransactionRunner:
    """Retries serialization failures, and only those.

    A failed attempt is rolled back before the next begins: retrying inside a
    poisoned transaction fails again for a reason unrelated to the conflict.
    """

    session_factory: sessionmaker[Session]
    policy: RetryPolicy = field(default=DEFAULT_RETRY_POLICY)

    def run[ResultT](self, operation: Callable[[Session], ResultT]) -> ResultT:
        delay = self.policy.initial_delay_seconds
        for attempt in range(1, self.policy.max_attempts + 1):
            with self.session_factory() as session:
                try:
                    result = operation(session)
                    session.commit()
                    return result
                except DBAPIError as error:
                    session.rollback()
                    if (
                        not _is_serialization_failure(error)
                        or attempt == self.policy.max_attempts
                    ):
                        raise
                except Exception:
                    session.rollback()
                    raise
            sleep(delay)
            delay *= 2
        raise RuntimeError("unreachable transaction retry state")


def runner_for(
    session_factory: sessionmaker[Session],
    retry_required: bool,
    policy: RetryPolicy | None = None,
) -> TransactionRunner:
    """Return the runner matching a provider's transaction behaviour.

    Driven by :class:`~kae_memory.persistence.providers.DatabaseCapabilities`
    rather than by a provider name, so a future engine that shares PostgreSQL's
    semantics gets the right strategy without being listed here.
    """

    if retry_required:
        return CockroachDBRetryingTransactionRunner(
            session_factory, policy or DEFAULT_RETRY_POLICY
        )
    return PostgreSQLTransactionRunner(session_factory)


def run_transaction[ResultT](
    session_factory: sessionmaker[Session],
    operation: Callable[[Session], ResultT],
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> ResultT:
    """Run a complete unit of work and retry only serialization failures.

    The long-standing entry point, kept so every existing caller keeps working.
    Retrying is harmless on a provider that never raises 40001 — the loop simply
    never repeats — so this stays correct on both while services move to
    :class:`TransactionRunner`.
    """

    return CockroachDBRetryingTransactionRunner(session_factory, policy).run(operation)


def _is_serialization_failure(error: DBAPIError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    return sqlstate == SERIALIZATION_FAILURE


__all__ = [
    "DEFAULT_RETRY_POLICY",
    "SERIALIZATION_FAILURE",
    "CockroachDBRetryingTransactionRunner",
    "PostgreSQLTransactionRunner",
    "RetryPolicy",
    "TransactionRunner",
    "run_transaction",
    "runner_for",
]
