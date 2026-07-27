from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.persistence.transactions import RetryPolicy, run_transaction


class _Orig(Exception):
    """Driver error carrying a SQLSTATE, as psycopg exposes it."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _dbapi_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, _Orig(sqlstate))


def _factory() -> sessionmaker[Session]:
    return sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))


def test_returns_result_without_retrying_on_success() -> None:
    attempts: list[int] = []

    def operation(_: Session) -> str:
        attempts.append(1)
        return "done"

    result = run_transaction(_factory(), operation)

    assert result == "done"
    assert len(attempts) == 1


def test_retries_serialization_failure_then_succeeds() -> None:
    attempts: list[int] = []

    def operation(_: Session) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _dbapi_error("40001")
        return "committed"

    policy = RetryPolicy(max_attempts=3, initial_delay_seconds=0.0)
    result = run_transaction(_factory(), operation, policy)

    assert result == "committed"
    assert len(attempts) == 3


def test_raises_after_exhausting_retry_budget() -> None:
    attempts: list[int] = []

    def operation(_: Session) -> str:
        attempts.append(1)
        raise _dbapi_error("40001")

    policy = RetryPolicy(max_attempts=2, initial_delay_seconds=0.0)

    with pytest.raises(DBAPIError):
        run_transaction(_factory(), operation, policy)

    assert len(attempts) == 2


def test_does_not_retry_other_database_errors() -> None:
    attempts: list[int] = []

    def operation(_: Session) -> str:
        attempts.append(1)
        raise _dbapi_error("23505")

    with pytest.raises(DBAPIError):
        run_transaction(_factory(), operation, RetryPolicy(initial_delay_seconds=0.0))

    assert len(attempts) == 1


def test_detects_serialization_failure_from_pgcode() -> None:
    class _PgcodeOrig(Exception):
        pgcode = "40001"

    attempts: list[int] = []

    def operation(_: Session) -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise DBAPIError("SELECT 1", {}, _PgcodeOrig())
        return "committed"

    result = run_transaction(_factory(), operation, RetryPolicy(initial_delay_seconds=0.0))

    assert result == "committed"
    assert len(attempts) == 2


def test_backoff_doubles_between_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr(
        "kae_memory.persistence.transactions.sleep",
        lambda seconds: delays.append(seconds),
    )
    attempts: list[int] = []

    def operation(_: Session) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _dbapi_error("40001")
        return "committed"

    run_transaction(_factory(), operation, RetryPolicy(max_attempts=3, initial_delay_seconds=0.1))

    assert delays == [0.1, 0.2]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_attempts": 0}, "max_attempts must be positive"),
        ({"initial_delay_seconds": -1.0}, "initial_delay_seconds must not be negative"),
    ],
)
def test_rejects_invalid_policy(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RetryPolicy(**kwargs)
