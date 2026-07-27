"""Transaction execution with bounded CockroachDB serialization retries."""

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker


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


def run_transaction[ResultT](
    session_factory: sessionmaker[Session],
    operation: Callable[[Session], ResultT],
    policy: RetryPolicy = DEFAULT_RETRY_POLICY,
) -> ResultT:
    """Run a complete unit of work and retry only serialization failures."""

    delay = policy.initial_delay_seconds
    for attempt in range(1, policy.max_attempts + 1):
        with session_factory() as session:
            try:
                result = operation(session)
                session.commit()
                return result
            except DBAPIError as error:
                session.rollback()
                if not _is_serialization_failure(error) or attempt == policy.max_attempts:
                    raise
        sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable transaction retry state")


def _is_serialization_failure(error: DBAPIError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    return sqlstate == "40001"
