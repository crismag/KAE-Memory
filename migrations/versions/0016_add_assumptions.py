"""Add assumptions as durable records (N35).

Additive over revision 0015. One new table; nothing existing is altered.

`StatementLabel.ASSUMPTION` was a label applied to an assembled statement. A
label cannot be pinned, disclosed, accepted, revisited, or reversed — it exists
for as long as the payload that carried it. A package generated from thin
knowledge therefore disclosed its assumptions once, to whoever read that
response, and then forgot them.

Deliberately **not** a row in `knowledge_items`. That table feeds readiness and
is what a person confirms; an assumption is what KAE proceeded on *because*
nobody had confirmed anything. One table would put the promotion this model
forbids a single UPDATE away, and FR-005 would be routed around by something
that looked like a convenience.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "assumptions",
        sa.Column("assumption_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("assumed_value", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=40), nullable=False),
        sa.Column("consequence", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("scope", sa.String(length=40), nullable=False, server_default="project"),
        sa.Column("revisit", sa.String(length=40), nullable=False),
        sa.Column("evidence", JSONB, nullable=False),
        sa.Column("accepted_by", sa.String(length=120), nullable=True),
        sa.Column("delegated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supersedes", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("assumption_id"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_assumptions_confidence"),
    )
    op.create_index("ix_assumptions_project_state", "assumptions", ["project_id", "state"])
    op.create_index("ix_assumptions_project_subject", "assumptions", ["project_id", "subject"])


def downgrade() -> None:
    op.drop_index("ix_assumptions_project_subject", table_name="assumptions")
    op.drop_index("ix_assumptions_project_state", table_name="assumptions")
    op.drop_table("assumptions")
