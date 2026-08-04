"""Test fixtures.

**Tests run against an engine the product deploys on, never SQLite.** SQLite was
retired after it produced two false passes: a timezone-aware provenance defect
it hid by dropping offsets on read, and a migration it rejected because it
cannot add a ``NOT NULL`` column with a non-constant default. It could not
express a vector column at all. A suite that passes on an engine nobody deploys
is not evidence (ADR-0011).

What changed is that "the engine" is now one of two. PostgreSQL with pgvector
and CockroachDB are both supported, and ``KAE_TEST_DATABASE_PROVIDER`` selects
which one this run exercises (ADR-0022).

Test configuration is resolved separately from application configuration and
never falls back to it. A suite that can read ``KAE_DATABASE_URL`` is one
mistaken environment away from truncating a real database — which has already
happened once here, when Alembic resolved that variable ahead of the throwaway
database a fixture had built.
"""

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from tests.support.database import (
    DatabaseTestSettings,
    DatabaseUnavailableError,
    require_safe_test_target,
    resolve_settings,
    selected_provider,
    with_database,
)

from kae_memory.persistence import providers
from kae_memory.persistence.providers import DatabaseProvider
from kae_memory.persistence.tables import Base

DATABASE_MARKERS = {"database", "database_contract", "migration"}
"""Markers whose tests need a live database."""

DATABASE_FIXTURES = {
    "factory",
    "engine",
    "test_database",
    "database_session",
    "database_engine",
    "alembic_config",
    "database_test_settings",
}
"""Fixtures that only exist against a live database.

Requesting one is the same statement as carrying the ``database`` marker, so it
is treated as one. Marking six hundred existing tests by hand would be the
alternative, and a marker people forget to add is worse than one derived from
what a test actually asks for.
"""

PROVIDER_MARKERS = {provider.value for provider in DatabaseProvider}
"""Markers naming one provider. A test carrying one runs only on that provider."""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip what this environment cannot honestly run.

    Two separate reasons, kept distinct in the skip message so a reader can tell
    "this provider was not selected" from "no test database is configured".
    Neither is a pass, and neither is a failure of the code under test.
    """

    try:
        settings: DatabaseTestSettings | None = resolve_settings()
        unavailable = ""
    except DatabaseUnavailableError as error:
        settings = None
        unavailable = str(error)

    provider = settings.provider if settings else selected_provider()

    for item in items:
        if DATABASE_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.database)

        # Markers, not keywords. `keywords` also contains parametrize ids, so a
        # perfectly offline test parametrised over both providers was being
        # skipped as though it required one of them.
        applied = {marker.name for marker in item.iter_markers()}
        wrong_provider = PROVIDER_MARKERS & applied - {provider.value}
        if wrong_provider:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"{sorted(wrong_provider)[0]} test: this run selected "
                        f"{provider.value}. Set KAE_TEST_DATABASE_PROVIDER to change it."
                    )
                )
            )
            continue
        applied = {marker.name for marker in item.iter_markers()}
        needs_database = (DATABASE_MARKERS | PROVIDER_MARKERS) & applied
        if needs_database and settings is None:
            item.add_marker(pytest.mark.skip(reason=unavailable))


@pytest.fixture(scope="session")
def database_test_settings() -> DatabaseTestSettings:
    """Where this run may create and destroy databases.

    Skips rather than failing when unconfigured: a developer running the unit
    suite has not asked for a database, and a suite that cannot start without
    one would push people toward configuring it carelessly.
    """

    try:
        settings = resolve_settings()
    except DatabaseUnavailableError as error:
        pytest.skip(str(error))
    require_safe_test_target(settings.url)
    return settings


@pytest.fixture(scope="session")
def provider(database_test_settings: DatabaseTestSettings) -> DatabaseProvider:
    """The provider this run exercises."""

    return database_test_settings.provider


@pytest.fixture(scope="session")
def provider_adapter(provider: DatabaseProvider) -> providers.ProviderAdapter:
    """The adapter under test.

    Contract tests take this rather than reading configuration themselves, so
    one test body runs against either engine.
    """

    return providers.adapter_for(provider)


def _drop_database(provider: DatabaseProvider, name: str) -> str:
    """Return DDL discarding a throwaway database on this provider.

    Asked of the adapter rather than written here: CockroachDB takes ``CASCADE``
    and PostgreSQL rejects it, and a fixture that knew the difference would be a
    provider check living outside the persistence layer.
    """

    return providers.adapter_for(provider).drop_database(name)


@pytest.fixture(scope="session")
def test_database(database_test_settings: DatabaseTestSettings) -> Iterator[str]:
    """Create a throwaway database for this session and drop it afterwards.

    Named per session so a parallel run, or leftovers from a killed one, never
    collide. Every name carries ``test`` so the safety guard recognises it.
    """

    settings = database_test_settings
    name = f"kae_test_{uuid4().hex[:12]}"
    require_safe_test_target(with_database(settings.url, name))

    admin = sa.create_engine(settings.url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f"CREATE DATABASE {name}"))
    except Exception as error:  # pragma: no cover - environment, not a test failure
        admin.dispose()
        pytest.skip(
            f"cannot reach {settings.provider.value} at {settings.url.rsplit('@', 1)[-1]}: {error}"
        )

    url = with_database(settings.url, name)
    if settings.provider is DatabaseProvider.POSTGRESQL:
        # pgvector lives per database, and this one was just created. Without
        # it the schema cannot be built at all.
        prepared = sa.create_engine(url, isolation_level="AUTOCOMMIT")
        with prepared.connect() as connection:
            for statement in providers.adapter_for(settings.provider).prepare_statements():
                connection.execute(sa.text(statement))
        prepared.dispose()

    yield url

    with admin.connect() as connection:
        connection.execute(sa.text(_drop_database(settings.provider, name)))
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


@pytest.fixture
def database_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One session over an empty schema, for contract tests."""

    with factory() as session:
        yield session


def _truncate(engine: Engine) -> None:
    tables = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))
    with engine.begin() as connection:
        connection.execute(sa.text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def alembic_config(
    database_test_settings: DatabaseTestSettings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Config, str]]:
    """An Alembic config pointed at a database created for this test.

    Each migration test gets its own database: they upgrade and downgrade the
    whole schema, so they cannot share the session-scoped one.

    ``KAE_DATABASE_URL`` and ``KAE_DATABASE_PROVIDER`` are repointed at it for
    the duration, and this is not belt-and-braces. ``migrations/env.py``
    resolves configuration *before* the Alembic config, so with a developer's
    environment loaded these tests once ran ``downgrade base`` against whatever
    those variables named — the real database — while inspecting the throwaway
    one, finding no tables, and reporting success.
    """

    settings = database_test_settings
    name = f"kae_test_mig_{uuid4().hex[:12]}"
    url = with_database(settings.url, name)
    require_safe_test_target(url)

    admin = sa.create_engine(settings.url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f"CREATE DATABASE {name}"))

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    monkeypatch.setenv("KAE_DATABASE_URL", url)
    monkeypatch.setenv("KAE_DATABASE_PROVIDER", settings.provider.value)
    for variable in ("KAE_POSTGRESQL_URL", "KAE_COCKROACHDB_URL"):
        monkeypatch.delenv(variable, raising=False)

    yield config, url

    with admin.connect() as connection:
        connection.execute(sa.text(_drop_database(settings.provider, name)))
    admin.dispose()
