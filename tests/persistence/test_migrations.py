"""Migrations apply and roll back cleanly.

Run against CockroachDB, because that is where they run in production. The
version that motivated this: revision 0003 first used a non-constant
``ADD COLUMN`` default, which SQLite rejects and CockroachDB accepts — the
opposite failure to the one SQLite usually hides, and equally misleading.

The mapped metadata is the source of truth; these checks make sure the committed
revisions actually produce it, so a mapping change without a migration is caught
here rather than in production.
"""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from kae_memory.persistence.tables import Base

EXPECTED_TABLES = {
    "agent_runs",
    "knowledge_items",
    "knowledge_provenance_links",
    "knowledge_relationships",
    "knowledge_versions",
    "messages",
    "projects",
    "sessions",
}


def test_upgrade_creates_every_mapped_table(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        present = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert present >= EXPECTED_TABLES
    assert set(Base.metadata.tables) <= present


def test_downgrade_removes_every_table(alembic_config: tuple[Config, str]) -> None:
    config, url = alembic_config

    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        created = set(inspect(engine).get_table_names())
        # Proving the upgrade landed *in this database* is what stops the
        # assertion below passing vacuously. An empty database satisfies "no
        # expected tables remain" perfectly, so without this the test reports
        # success precisely when the migration ran somewhere else.
        assert created >= EXPECTED_TABLES

        command.downgrade(config, "base")
        remaining = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert not (EXPECTED_TABLES & remaining)


def test_revision_0002_is_additive_over_0001(alembic_config: tuple[Config, str]) -> None:
    """Revision 0001 stands alone; 0002 only adds to it."""

    config, url = alembic_config

    command.upgrade(config, "0001")
    engine = create_engine(url)
    try:
        after_first = set(inspect(engine).get_table_names())
        command.upgrade(config, "0002")
        after_second = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"knowledge_items", "knowledge_versions"} <= after_first
    assert after_first < after_second


def test_revision_0003_is_additive_over_0002(alembic_config: tuple[Config, str]) -> None:
    """The lease columns arrive without disturbing what 0002 built."""

    config, url = alembic_config

    command.upgrade(config, "0002")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        before = {column["name"] for column in inspector.get_columns("agent_runs")}
        command.upgrade(config, "0003")
        inspector = inspect(engine)
        after = {column["name"] for column in inspector.get_columns("agent_runs")}
    finally:
        engine.dispose()

    assert before < after
    assert after - before == {
        "lease_owner",
        "lease_token",
        "lease_acquired_at",
        "lease_expires_at",
        "heartbeat_at",
        "next_attempt_at",
    }


def test_revision_0003_backfills_existing_runs(alembic_config: tuple[Config, str]) -> None:
    """A populated table survives the migration.

    The NOT NULL columns are added with a server default so existing rows
    backfill, then the default is dropped — the application stays the sole author
    of both values.
    """

    config, url = alembic_config
    command.upgrade(config, "0002")

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (project_id, project_key, name, status, "
                    "created_at, updated_at) VALUES (gen_random_uuid(), 'k1', 'Legacy', 'active', "
                    "'2026-07-27 00:00:00+00', '2026-07-27 00:00:00+00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO agent_runs (agent_run_id, project_id, agent_role, status, "
                    "idempotency_key, attempt_number, input_context, output_summary, "
                    "continuation_state, created_at, updated_at) SELECT "
                    "'11111111-1111-1111-1111-111111111111', project_id, "
                    "'requirements', 'pending', 'legacy-1', 1, '{}', '{}', '{}', "
                    "'2026-07-27 00:00:00+00', '2026-07-27 00:00:00+00' FROM projects"
                )
            )

        command.upgrade(config, "0003")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT lease_token, next_attempt_at FROM agent_runs "
                    "WHERE idempotency_key = 'legacy-1'"
                )
            ).one()
    finally:
        engine.dispose()

    assert row[0] == 0, "pre-existing runs start with no lease"
    assert row[1] is not None, "pre-existing runs are immediately claimable"
