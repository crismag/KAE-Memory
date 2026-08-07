"""Declared purpose on a message (EM-2).

Additive over revision 0021. One nullable column on an existing table, no
backfill required and no data rewritten.

**Why a column rather than a metadata key.** `messages.metadata` already carries
structure about a message, and putting purpose there would have been cheaper.
It is the wrong home for two reasons: extraction has to filter on this, and a
JSONB predicate on the hot acquisition path is a worse query than a column; and
metadata is deliberately open, so anything stored there can be absent, misspelt,
or shaped differently by a caller nobody has met. What decides whether a
sentence becomes project knowledge should not be a string key that fails quietly
when it is missing.

**Nullable, and read as `project_input`.** Every message written before this
existed was project input, so a NULL is accurate rather than unknown. A NOT NULL
default would say the same thing while claiming each historical row had made a
declaration it never made.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("purpose", sa.String(length=40), nullable=True))

    # Partial, because the interesting query is "which messages were excluded
    # from interpretation" and that is the small set. Indexing every row to find
    # the few would cost writes on the busiest table for a read nobody makes.
    op.create_index(
        "ix_messages_project_purpose",
        "messages",
        ["project_id", "purpose"],
        postgresql_where=sa.text("purpose IS NOT NULL AND purpose <> 'project_input'"),
    )


def downgrade() -> None:
    op.drop_index("ix_messages_project_purpose", table_name="messages")
    op.drop_column("messages", "purpose")
