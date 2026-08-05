"""Add durable deliverable identity (N20).

Additive over revision 0013. One new table; nothing existing is altered.

A deliverable is a durable record that this project produced this output, at
this knowledge revision, with this content. `assemble_context` produces a
description and forgets it — `package_id` is a fresh UUID per call, deliberately,
because an assembly is a computation and giving a computation an identity that
outlives it invites a client to store an id resolving to nothing.

**No artifact bytes.** The row holds the manifest, the hashes, and what each
artifact would contain. Rendering and storing content is revision N21's concern
and belongs to whoever owns the destination; a relational row competing with a
file store for that job would be the worst of both.

The unique index on ``identity_hash`` is what makes "recording the same output
twice is one deliverable" true under concurrency. A lookup before an insert
races, and two racing recordings of one output would mint two ids and report a
change the project did not make.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "deliverables",
        sa.Column("deliverable_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("module_key", sa.String(length=120), nullable=True),
        sa.Column("knowledge_revision", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(length=120), nullable=False),
        sa.Column("generator_version", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("artifacts", JSONB, nullable=False),
        sa.Column("manifest", JSONB, nullable=False),
        sa.Column("source_knowledge", JSONB, nullable=False),
        sa.Column("recorded_by", sa.String(length=120), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by", sa.Uuid(as_uuid=False), nullable=True),
        sa.PrimaryKeyConstraint("deliverable_id"),
        sa.UniqueConstraint("identity_hash", name="uq_deliverables_identity"),
        sa.CheckConstraint("knowledge_revision >= 0", name="ck_deliverables_revision"),
    )
    op.create_index("ix_deliverables_project_state", "deliverables", ["project_id", "state"])
    op.create_index(
        "ix_deliverables_project_recorded", "deliverables", ["project_id", "recorded_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_deliverables_project_recorded", table_name="deliverables")
    op.drop_index("ix_deliverables_project_state", table_name="deliverables")
    op.drop_table("deliverables")
