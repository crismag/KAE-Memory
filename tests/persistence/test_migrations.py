"""Migrations apply and roll back cleanly.

Run against CockroachDB, because that is where they run in production. The
version that motivated this: revision 0003 first used a non-constant
``ADD COLUMN`` default, which SQLite rejects and CockroachDB accepts — the
opposite failure to the one SQLite usually hides, and equally misleading.

The mapped metadata is the source of truth; these checks make sure the committed
revisions actually produce it, so a mapping change without a migration is caught
here rather than in production.
"""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from tests.support.database import require_safe_test_target

from kae_memory.persistence.tables import Base

pytestmark = [pytest.mark.database, pytest.mark.migration]


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
    # Checked here, not only in the fixture: the fixture resolving the wrong
    # target is the failure being guarded against.
    require_safe_test_target(url)

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


class TestTheMigrationsBuildTheSchemaTheModelDeclares:
    """Not only the tables. **The column types too.**

    `test_upgrade_creates_every_mapped_table` compares table *names*, and a
    check that compares names cannot notice a type. Five columns declared
    `UUID_STR` in `tables.py` were created `sa.String(64)` by revisions `0020`
    and `0021`, and the disagreement survived from the day they were written
    until somebody read one of those rows by primary key on the deployment:

        operator does not exist: character varying = uuid
        WHERE provider_connections.connection_id = $1::UUID

    **The rest of the suite is structurally unable to catch this.** Every other
    test builds its schema from `Base.metadata`, so it runs against the types
    the model declares — which is precisely the side of the disagreement that
    was never in doubt. Only a database built by the migrations can disagree
    with the model, and only this file builds one.

    The same shape as `AUD-040`, one layer down: a guard that enumerates one
    property drifts from the thing it is guarding.
    """

    def test_every_uuid_column_in_the_model_is_a_uuid_column_in_the_database(
        self, alembic_config: tuple[Config, str]
    ) -> None:
        from sqlalchemy import Uuid

        config, url = alembic_config
        command.upgrade(config, "head")

        declared = {
            (table.name, column.name)
            for table in Base.metadata.sorted_tables
            for column in table.columns
            if isinstance(column.type, Uuid)
        }
        assert declared, "the model declares no UUID columns; this check has lost its subject"

        engine = create_engine(url)
        try:
            inspector = inspect(engine)
            present = set(inspector.get_table_names())
            actual = {
                (table, column["name"]): type(column["type"]).__name__
                for table in present
                for column in inspector.get_columns(table)
            }
        finally:
            engine.dispose()

        drifted = sorted(
            f"{table}.{column} is {actual[(table, column)]} in the database, UUID in the model"
            for table, column in declared
            if (table, column) in actual and actual[(table, column)] not in {"UUID", "Uuid"}
        )

        assert not drifted, (
            "the migrations built columns the model disagrees with:\n  "
            + "\n  ".join(drifted)
            + "\n\nA type mismatch on an identifier column fails only when something "
            "reads that row by primary key, which can be years after the migration "
            "that caused it."
        )


class TestRevision0027BackfillsTheSourceTypeNothingEverWrote:
    """`EPI-5a`, `D-105`. Data only — no column is added, altered or dropped.

    The column has been in the schema since revision 0002 and every producing
    link in every deployment carries `NULL`, because nothing wrote one. The
    backfill applies the same rule `source_type_for_run` applies to new writes,
    so a backfilled row and a freshly written one agree.
    """

    PROJECT = "aaaaaaaa-0000-0000-0000-000000000001"
    MOMENT = "'2026-08-16 00:00:00+00'"

    def _seed(self, connection: object) -> None:
        """Four rows at 0026: three producing links and one consumption."""

        run = "bbbbbbbb-0000-0000-0000-00000000000"
        connection.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO projects (project_id, project_key, name, status, created_at, "
                f"updated_at) VALUES ('{self.PROJECT}', 'epi5a', 'Legacy', 'active', "
                f"{self.MOMENT}, {self.MOMENT})"
            )
        )
        runs = [
            (f"{run}1", "requirements", '{"document": "src/api.py", "source_type": "repository"}'),
            (f"{run}2", "requirements", '{"document": "spec.md"}'),
            (f"{run}3", "requirements", '{"message_id": "m1"}'),
            (f"{run}4", "architecture", "{}"),
        ]
        for index, (run_id, role, context) in enumerate(runs):
            connection.execute(  # type: ignore[attr-defined]
                text(
                    "INSERT INTO agent_runs (agent_run_id, project_id, agent_role, status, "
                    "idempotency_key, attempt_number, input_context, output_summary, "
                    "continuation_state, lease_token, next_attempt_at, created_at, "
                    f"updated_at) VALUES ('{run_id}', '{self.PROJECT}', '{role}', "
                    f"'succeeded', 'legacy-{index}', 1, '{context}', '{{}}', '{{}}', "
                    f"0, {self.MOMENT}, {self.MOMENT}, {self.MOMENT})"
                )
            )
            item = f"item-{index}"
            connection.execute(  # type: ignore[attr-defined]
                text(
                    "INSERT INTO knowledge_items (id, project_id, kind, lifecycle) VALUES "
                    f"('{item}', '{self.PROJECT}', 'requirement', 'proposed')"
                )
            )
            links = (
                ("produced_by", f"'{run_id}'"),
                ("used_by", f"'{run_id}'"),
                # A correction carries no run, which is why the migration needs
                # a second pass at all.
                ("derived_from_message", "NULL"),
            )
            for slot, (link_type, run_column) in enumerate(links):
                link_id = f"cccccccc-0000-0000-000{index}-00000000000{slot}"
                connection.execute(  # type: ignore[attr-defined]
                    text(
                        "INSERT INTO knowledge_provenance_links (provenance_link_id, "
                        "project_id, knowledge_item_id, link_type, agent_run_id, "
                        f"source_type, created_at) VALUES ('{link_id}', "
                        f"'{self.PROJECT}', '{item}', '{link_type}', {run_column}, NULL, "
                        f"{self.MOMENT})"
                    )
                )

    def _backfilled(self, alembic_config: tuple[Config, str]) -> dict[tuple[str, str], str | None]:
        config, url = alembic_config
        command.upgrade(config, "0026")

        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                self._seed(connection)

            command.upgrade(config, "0027")

            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT knowledge_item_id, link_type, source_type "
                        "FROM knowledge_provenance_links ORDER BY knowledge_item_id, link_type"
                    )
                ).all()
        finally:
            engine.dispose()

        return {(row[0], row[1]): row[2] for row in rows}

    def test_every_producing_link_names_a_source_and_used_by_stays_empty(
        self, alembic_config: tuple[Config, str]
    ) -> None:
        backfilled = self._backfilled(alembic_config)

        assert backfilled[("item-0", "produced_by")] == "repository", (
            "a run that declared its source is believed"
        )
        assert backfilled[("item-1", "produced_by")] == "imported_document", (
            "a run carrying a document was given one"
        )
        assert backfilled[("item-2", "produced_by")] == "user_statement", (
            "anything else read a message in a session"
        )
        assert backfilled[("item-3", "produced_by")] == "kae_inference", (
            "architecture derives from what the project already holds"
        )
        assert all(backfilled[(f"item-{index}", "used_by")] is None for index in range(4)), (
            "consumption is not an origin and is left alone"
        )

    def test_a_message_link_with_no_run_inherits_from_its_sibling(
        self, alembic_config: tuple[Config, str]
    ) -> None:
        """Corrections carry no `agent_run_id`, so the rule cannot reach a run."""

        backfilled = self._backfilled(alembic_config)

        assert backfilled[("item-0", "derived_from_message")] == "repository"
        assert backfilled[("item-3", "derived_from_message")] == "kae_inference"

    def test_downgrade_returns_the_column_to_the_state_it_was_in(
        self, alembic_config: tuple[Config, str]
    ) -> None:
        config, url = alembic_config
        command.upgrade(config, "0026")

        engine = create_engine(url)
        try:
            with engine.begin() as connection:
                self._seed(connection)
            command.upgrade(config, "0027")
            command.downgrade(config, "0026")

            with engine.connect() as connection:
                remaining = connection.execute(
                    text(
                        "SELECT count(*) FROM knowledge_provenance_links "
                        "WHERE source_type IS NOT NULL"
                    )
                ).scalar_one()
        finally:
            engine.dispose()

        assert remaining == 0, "the backfill is data, and data can be put back"
