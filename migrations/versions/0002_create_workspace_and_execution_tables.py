"""Create workspace and execution tables.

Adds projects, sessions, agent_runs, messages, knowledge_relationships, and
knowledge_provenance_links. Additive: revision 0001 is not modified, and the
existing knowledge tables remain the authoritative durable memory.

References into the existing knowledge tables are String(64) because
knowledge_items.id is String(64), not a UUID column. See ADR-0005.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_id"),
        sa.UniqueConstraint("project_key"),
    )
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("session_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "ix_sessions_project_started", "sessions", ["project_id", "started_at"], unique=False
    )
    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("session_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("agent_role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("attempt_number", sa.BigInteger(), nullable=False),
        sa.Column(
            "input_context",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "output_summary",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "continuation_state",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
        ),
        sa.PrimaryKeyConstraint("agent_run_id"),
        sa.UniqueConstraint("project_id", "idempotency_key", "attempt_number"),
    )
    op.create_index(
        "ix_agent_runs_project_created", "agent_runs", ["project_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_agent_runs_project_status", "agent_runs", ["project_id", "status"], unique=False
    )
    op.create_index(
        "ix_agent_runs_session_created", "agent_runs", ["session_id", "created_at"], unique=False
    )
    op.create_table(
        "knowledge_relationships",
        sa.Column("relationship_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("source_knowledge_item_id", sa.String(length=64), nullable=False),
        sa.Column("target_knowledge_item_id", sa.String(length=64), nullable=False),
        sa.Column("relationship_type", sa.String(length=40), nullable=False),
        sa.Column("created_by_agent_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_knowledge_item_id <> target_knowledge_item_id",
            name="ck_knowledge_relationships_distinct_endpoints",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_run_id"],
            ["agent_runs.agent_run_id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_knowledge_item_id"],
            ["knowledge_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_knowledge_item_id"],
            ["knowledge_items.id"],
        ),
        sa.PrimaryKeyConstraint("relationship_id"),
        sa.UniqueConstraint(
            "source_knowledge_item_id", "target_knowledge_item_id", "relationship_type"
        ),
    )
    op.create_index(
        "ix_knowledge_relationships_project_source",
        "knowledge_relationships",
        ["project_id", "source_knowledge_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_relationships_project_target",
        "knowledge_relationships",
        ["project_id", "target_knowledge_item_id"],
        unique=False,
    )
    op.create_table(
        "messages",
        sa.Column("message_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("session_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("sequence_number", sa.BigInteger(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column("message_type", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.agent_run_id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.session_id"],
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint("session_id", "sequence_number"),
    )
    op.create_index(
        "ix_messages_project_created", "messages", ["project_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_messages_session_sequence", "messages", ["session_id", "sequence_number"], unique=False
    )
    op.create_table(
        "knowledge_provenance_links",
        sa.Column("provenance_link_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("knowledge_item_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_version_number", sa.BigInteger(), nullable=True),
        sa.Column("agent_run_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("message_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("link_type", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.agent_run_id"],
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_item_id"],
            ["knowledge_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.message_id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
        ),
        sa.PrimaryKeyConstraint("provenance_link_id"),
    )
    op.create_index(
        "ix_provenance_links_agent_run",
        "knowledge_provenance_links",
        ["agent_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_provenance_links_item_type",
        "knowledge_provenance_links",
        ["knowledge_item_id", "link_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provenance_links_item_type", table_name="knowledge_provenance_links")
    op.drop_index("ix_provenance_links_agent_run", table_name="knowledge_provenance_links")
    op.drop_table("knowledge_provenance_links")
    op.drop_index("ix_messages_session_sequence", table_name="messages")
    op.drop_index("ix_messages_project_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_knowledge_relationships_project_target", table_name="knowledge_relationships")
    op.drop_index("ix_knowledge_relationships_project_source", table_name="knowledge_relationships")
    op.drop_table("knowledge_relationships")
    op.drop_index("ix_agent_runs_session_created", table_name="agent_runs")
    op.drop_index("ix_agent_runs_project_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_project_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_sessions_project_started", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("projects")
