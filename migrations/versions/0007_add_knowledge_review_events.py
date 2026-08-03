"""Add the append-only knowledge review event log.

Additive over revision 0006. One new table; nothing existing is altered, so
every prior row and query is untouched.

A lifecycle column records what a statement is. It cannot record who decided
that, on which wording, or why — and for knowledge a person accepted as
authoritative, that is the part someone needs when they later disagree.

Idempotency lives in the unique index over ``(knowledge_item_id,
idempotency_key)``, not in application code, for the same reason as revision
0006: a read-then-insert races, and two concurrent retries of one confirmation
would both find nothing and both write a decision. NULL keys are permitted many
times over, so a decision recorded without one is unaffected.

``knowledge_item_id`` is ``String(64)`` to match ``knowledge_items.id``, which
revision 0001 created as a string rather than a UUID column. ``project_id`` is
likewise a plain string and carries no foreign key, matching
``knowledge_items.project_id`` — the two columns are not even the same type as
``projects.project_id``, and correcting that is a separate change with its own
migration rather than a side effect of adding an audit log.

Written by hand for the same reason as revisions 0004 to 0006: autogenerate
against CockroachDB reports cosmetic differences that are not real changes.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_review_events",
        sa.Column("review_event_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_item_id", sa.String(length=64), nullable=False),
        sa.Column("version_number", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("from_lifecycle", sa.String(length=32), nullable=False),
        sa.Column("to_lifecycle", sa.String(length=32), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column("reason_code", sa.String(length=40), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("review_event_id"),
        sa.ForeignKeyConstraint(
            ["knowledge_item_id"], ["knowledge_items.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "uq_review_events_item_idempotency",
        "knowledge_review_events",
        ["knowledge_item_id", "idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_review_events_item_created",
        "knowledge_review_events",
        ["knowledge_item_id", "created_at"],
    )
    op.create_index(
        "ix_review_events_project_created",
        "knowledge_review_events",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_events_project_created", table_name="knowledge_review_events")
    op.drop_index("ix_review_events_item_created", table_name="knowledge_review_events")
    op.drop_index("uq_review_events_item_idempotency", table_name="knowledge_review_events")
    op.drop_table("knowledge_review_events")
