"""Widen ``knowledge_versions.version_number`` to 64 bits.

The second half of what revision 0009 started, and found by the schema-parity
test rather than by a failure: ``Integer`` realises as 32 bits on PostgreSQL and
64 on CockroachDB, so any bare one leaves the two providers holding different
schemas from the same migration history.

Unlike ``id``, this column is harmless at either width — version numbers count
from one and will not reach two billion. The width is not the point. Agreeing on
it is: a schema that differs by provider cannot be reasoned about, and "this
particular divergence happens to be safe" is a judgement someone has to make
correctly every time rather than once.

Idempotent by inspection rather than by provider, so the outcome is identical on
both even though only one of them has work to do.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "knowledge_versions"
COLUMN = "version_number"


def _current_type() -> str:
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns(TABLE):
        if column["name"] == COLUMN:
            return str(column["type"]).upper()
    return ""


def upgrade() -> None:
    if "BIGINT" in _current_type():
        # Already 64-bit, which is how this has always compiled on CockroachDB.
        return
    op.alter_column(
        TABLE, COLUMN, existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False
    )


def downgrade() -> None:
    # Not narrowing, for the same reason as 0009: every row written on
    # CockroachDB is already 64-bit, and a downgrade that truncates is not one.
    pass
