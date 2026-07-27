"""Test fixtures.

**Tests run against CockroachDB, not SQLite.** The engine under test is the
engine in production, at the same major version.

SQLite was retired after it produced two false passes: a timezone-aware
provenance defect that only surfaced because SQLite drops the offset on read, and
a revision that could not add a ``NOT NULL`` column because SQLite rejects a
non-constant ``ADD COLUMN`` default. It also could not express ``VECTOR`` at all,
which would have left M8's central capability unverifiable. A suite that passes
on an engine nobody deploys is not evidence.

A single-node CockroachDB in Docker backs the suite locally and in CI. Point
``KAE_TEST_DATABASE_URL`` elsewhere to run against another cluster.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.persistence.tables import Base

DEFAULT_TEST_URL = "cockroachdb+psycopg://root@localhost:26258/defaultdb?sslmode=disable"
"""Local single-node CockroachDB. Started by ``make test-db-up``."""


def admin_url() -> str:
    """Return the URL used to create and drop test databases."""

    return os.environ.get("KAE_TEST_DATABASE_URL", DEFAULT_TEST_URL)


def database_url(base_url: str, database: str) -> str:
    """Return ``base_url`` pointed at a different database."""

    root, _, query = base_url.partition("?")
    return f"{root.rsplit('/', 1)[0]}/{database}" + (f"?{query}" if query else "")


@pytest.fixture(scope="session")
def test_database() -> Iterator[str]:
    """Create a throwaway database for this session and drop it afterwards.

    Named per session so a parallel run, or leftovers from a killed one, never
    collide.
    """

    base = admin_url()
    name = f"kae_test_{uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f"CREATE DATABASE {name}"))
    except Exception as error:  # pragma: no cover - environment, not a test failure
        admin.dispose()
        pytest.exit(
            f"Cannot reach CockroachDB at {base.rsplit('@', 1)[-1]}: {error}\n"
            "Start it with `make test-db-up`, or set KAE_TEST_DATABASE_URL.",
            returncode=1,
        )

    yield database_url(base, name)

    with admin.connect() as connection:
        connection.execute(sa.text(f"DROP DATABASE {name} CASCADE"))
    admin.dispose()


@pytest.fixture(scope="session")
def engine(test_database: str) -> Iterator[Engine]:
    """Session-scoped engine with the schema created once."""

    created = sa.create_engine(test_database)
    Base.metadata.create_all(created)
    yield created
    created.dispose()


@pytest.fixture
def factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Return a session factory over an empty schema.

    Isolation is by truncation rather than by wrapping each test in a
    transaction that is rolled back: the application opens its own sessions
    through this factory and commits them, which is exactly the behaviour worth
    testing. Rolling those commits back would test something the application
    never does.
    """

    _truncate(engine)
    yield sessionmaker(engine)


def _truncate(engine: Engine) -> None:
    tables = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))
    with engine.begin() as connection:
        connection.execute(sa.text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def alembic_config() -> Iterator[tuple[Config, str]]:
    """Return an Alembic config pointed at a database created for this test.

    Each migration test gets its own database: they upgrade and downgrade the
    whole schema, so they cannot share the session-scoped one.
    """

    base = admin_url()
    name = f"kae_mig_{uuid4().hex[:12]}"
    admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f"CREATE DATABASE {name}"))

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    url = database_url(base, name)
    config.set_main_option("sqlalchemy.url", url)

    yield config, url

    with admin.connect() as connection:
        connection.execute(sa.text(f"DROP DATABASE {name} CASCADE"))
    admin.dispose()
