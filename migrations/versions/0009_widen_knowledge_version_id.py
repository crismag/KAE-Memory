"""Widen ``knowledge_versions.id`` to 64 bits.

Additive over revision 0008 in effect: no data changes, one column widens.

``Integer`` is not the same column on both providers. PostgreSQL compiles it to
a 32-bit ``integer``; CockroachDB's ``INT`` is ``INT8``, so it compiles to
``bigint``. The same migration therefore produced two different schemas, which
nobody noticed while only one engine existed.

It matters because CockroachDB generates these keys with ``unique_rowid()``,
whose values are far outside 32-bit range. A dataset written on CockroachDB
cannot be loaded into the PostgreSQL schema this migration corrects — which is
exactly how the divergence was found.

Deliberately not a no-op guarded by provider: on CockroachDB the column is
already 64-bit, so widening is either unnecessary or rejected as such, and both
are handled by checking the column rather than the provider name. What matters
is the *outcome* being identical on both, not the statement being identical.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "knowledge_versions"
COLUMN = "id"


def _current_type(name: str) -> str:
    inspector = sa.inspect(op.get_bind())
    for column in inspector.get_columns(TABLE):
        if column["name"] == name:
            return str(column["type"]).upper()
    return ""


def upgrade() -> None:
    if "BIGINT" in _current_type(COLUMN):
        # Already 64-bit, which is how this column has always compiled on
        # CockroachDB. Nothing to widen.
        return
    op.alter_column(
        TABLE, COLUMN, existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=False
    )


def downgrade() -> None:
    # Deliberately not narrowing. Any row whose id exceeds 32 bits — every row
    # written on CockroachDB — would be destroyed by the conversion, and a
    # downgrade that loses data is not a downgrade.
    pass
