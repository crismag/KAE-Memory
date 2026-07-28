"""Add blueprint readiness, blockers, area links, and contradiction resolution.

Additive over revision 0004 (ADR-0012). Four new tables, one new column on
``projects``, and two on ``knowledge_relationships``.

``projects.knowledge_revision`` is a monotonic counter rather than a timestamp:
timestamps collide under concurrent writes and leave "did anything change since
this snapshot?" ambiguous. It is added with a constant default, so it can be
``NOT NULL`` in a single statement.

Written by hand for the same reason as revision 0004: autogenerate against
CockroachDB reports cosmetic differences that are not real changes.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("knowledge_revision", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "knowledge_relationships",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_relationships",
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )

    op.create_table(
        "readiness_templates",
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("template_key", "version"),
    )

    op.create_table(
        "knowledge_area_links",
        sa.Column("area_link_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("knowledge_item_id", sa.String(length=64), nullable=False),
        sa.Column("area_key", sa.String(length=80), nullable=False),
        sa.Column("assigned_by_agent_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.ForeignKeyConstraint(["knowledge_item_id"], ["knowledge_items.id"]),
        sa.ForeignKeyConstraint(["assigned_by_agent_run_id"], ["agent_runs.agent_run_id"]),
        sa.PrimaryKeyConstraint("area_link_id"),
        sa.UniqueConstraint("knowledge_item_id", "area_key"),
    )
    op.create_index(
        "ix_knowledge_area_links_project_area", "knowledge_area_links", ["project_id", "area_key"]
    )

    op.create_table(
        "discovery_blockers",
        sa.Column("blocker_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("area_key", sa.String(length=80), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.PrimaryKeyConstraint("blocker_id"),
    )
    op.create_index(
        "ix_discovery_blockers_project_status", "discovery_blockers", ["project_id", "status"]
    )

    op.create_table(
        "readiness_snapshots",
        sa.Column("snapshot_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("template_version", sa.BigInteger(), nullable=False),
        sa.Column("calculation_version", sa.BigInteger(), nullable=False),
        sa.Column("knowledge_revision", sa.BigInteger(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("draft_eligible", sa.Boolean(), nullable=False),
        sa.Column("implementation_eligible", sa.Boolean(), nullable=False),
        sa.Column("mandatory_area_count", sa.BigInteger(), nullable=False),
        sa.Column("mandatory_area_sufficient_count", sa.BigInteger(), nullable=False),
        sa.Column("open_blocker_count", sa.BigInteger(), nullable=False),
        sa.Column("critical_blocker_count", sa.BigInteger(), nullable=False),
        sa.Column("unresolved_contradiction_count", sa.BigInteger(), nullable=False),
        sa.Column("area_results", postgresql.JSONB(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index(
        "ix_readiness_snapshots_project_calculated",
        "readiness_snapshots",
        ["project_id", "calculated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_readiness_snapshots_project_calculated", table_name="readiness_snapshots")
    op.drop_table("readiness_snapshots")
    op.drop_index("ix_discovery_blockers_project_status", table_name="discovery_blockers")
    op.drop_table("discovery_blockers")
    op.drop_index("ix_knowledge_area_links_project_area", table_name="knowledge_area_links")
    op.drop_table("knowledge_area_links")
    op.drop_table("readiness_templates")
    op.drop_column("knowledge_relationships", "resolution_note")
    op.drop_column("knowledge_relationships", "resolved_at")
    op.drop_column("projects", "knowledge_revision")
