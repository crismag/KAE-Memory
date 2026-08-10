"""Make the setup and publication identifier columns UUID, as the model says.

**A drift the test suite cannot see, found by deploying.**

`tables.py` declares 45 columns as `UUID_STR` — a native `uuid` column mapped to
`str` in Python. Migrations `0020` and `0021` created five of them with
`sa.String(64)` instead. The database and the model have disagreed about those
five since the day they were created.

It stayed invisible for two reasons, and both are worth naming:

* **Nothing ever read those rows by primary key.** `SetupService`'s write
  methods had no production caller, so the tables held zero rows and no query
  reached them. The drift needed a caller to become a defect, and stage one of
  the product acquiring a surface is what supplied one.
* **Tests create their schema from `Base.metadata`, not from the migrations.**
  So every test ran against `uuid` columns while the deployment ran against
  `varchar`. A suite built this way cannot fail on a migration that disagrees
  with its model — it never executes the migration.

The failure, once a caller existed:

    operator does not exist: character varying = uuid
    LINE 3: WHERE provider_connections.connection_id = $1::UUID

SQLAlchemy renders a bind cast for `Uuid` on psycopg, so `session.get` sends a
`uuid` where the column is `varchar`. `select().where()` on the same table works
fine, which is why this surfaced on one code path and not the others.

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: The five, and only the five. Verified against the deployed database by
#: comparing every `Uuid` column in `Base.metadata` with
#: `information_schema.columns` — 45 declared, 5 drifted.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("provider_connections", "connection_id"),
    ("publication_targets", "target_id"),
    ("publication_targets", "connection_id"),
    ("publication_attempts", "attempt_id"),
    ("setup_questions", "setup_question_id"),
)


def upgrade() -> None:
    """Widen the type, keeping every value.

    `USING column::uuid` rather than a drop-and-recreate: the values are already
    well-formed UUID strings, so this is a representation change and no row is
    rewritten by hand. A column holding anything else would fail here loudly,
    which is the correct outcome — silently discarding an unparseable identifier
    would lose the row it identifies.

    SQLite has no `uuid` type and ignores the request; the tests that matter run
    against PostgreSQL, and `ADR-0011` retired SQLite for exactly this class of
    difference.
    """

    if op.get_bind().dialect.name != "postgresql":  # pragma: no cover - see docstring
        return

    for table, column in COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE uuid USING {column}::uuid")


def downgrade() -> None:
    """Back to text. Lossless in the other direction as well."""

    if op.get_bind().dialect.name != "postgresql":  # pragma: no cover
        return

    for table, column in COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE varchar(64) USING {column}::text"
        )


__all__ = ["COLUMNS", "downgrade", "revision", "upgrade"]


# Kept out of `COLUMNS` deliberately: `sa.String` is correct for these.
_NOT_DRIFT = {
    ("messages", "actor_id"),  # a person's name, not an identifier
}
