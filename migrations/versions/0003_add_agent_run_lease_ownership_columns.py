"""Add agent run lease ownership columns.

Additive over revision 0002 (ADR-0007). The claim on a run is committed database
state rather than a held lock, because CockroachDB row locks do not outlive their
transaction and a long model call cannot be protected by keeping
``SELECT ... FOR UPDATE`` open.

``lease_token`` and ``next_attempt_at`` are ``NOT NULL``. They are added with a
server default so existing rows backfill, then the default is dropped: the
application sets both explicitly on every write, and leaving a database default
in place would make it ambiguous which layer owns the value (ADR-0005).

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("lease_owner", sa.String(length=120), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("lease_token", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "agent_runs", sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agent_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Added nullable, then backfilled, then tightened. SQLite rejects a
    # non-constant default on ADD COLUMN, so `server_default=now()` is not
    # portable here — and an explicit backfill states the intent anyway: an
    # existing run becomes claimable at the moment it was created.
    op.add_column(
        "agent_runs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE agent_runs SET next_attempt_at = created_at WHERE next_attempt_at IS NULL")

    # Drop the constant default now that existing rows carry a value, so the
    # application remains the sole author of both columns.
    with op.batch_alter_table("agent_runs") as batch:
        batch.alter_column("lease_token", server_default=None)
        batch.alter_column(
            "next_attempt_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )

    op.create_index("ix_agent_runs_claimable", "agent_runs", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_runs_claimable", table_name="agent_runs")
    op.drop_column("agent_runs", "next_attempt_at")
    op.drop_column("agent_runs", "heartbeat_at")
    op.drop_column("agent_runs", "lease_expires_at")
    op.drop_column("agent_runs", "lease_acquired_at")
    op.drop_column("agent_runs", "lease_token")
    op.drop_column("agent_runs", "lease_owner")
