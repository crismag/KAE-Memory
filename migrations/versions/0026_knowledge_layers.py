"""Evidence, synthesized model, and attention — storage separation (ADR-0007).

Additive over revision 0025. Five new tables, no existing column altered, no
row rewritten, nothing backfilled.

``knowledge_items`` remain extracted evidence. Their ``lifecycle`` is still
statement confirmation. These tables are the other two layers: the synthesized
project model, and the human-attention queue. A project with 175 extracted
rows and zero synthesized objects is a valid Phase 1 state, not an empty
database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_evidence_roles",
        sa.Column(
            "knowledge_item_id",
            sa.String(64),
            sa.ForeignKey("knowledge_items.id", ondelete="NO ACTION"),
            primary_key=True,
        ),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_knowledge_evidence_roles_project",
        "knowledge_evidence_roles",
        ["project_id", "role"],
    )

    op.create_table(
        "synthesized_objects",
        sa.Column("object_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("domain", sa.String(80), nullable=False),
        sa.Column("identity_key", sa.String(200), nullable=False),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.String(32), nullable=False),
        sa.Column("authority", sa.String(32), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "domain", "identity_key", name="uq_synthesized_objects_identity"
        ),
    )
    op.create_index(
        "ix_synthesized_objects_project",
        "synthesized_objects",
        ["project_id", "domain"],
    )

    op.create_table(
        "synthesized_evidence_links",
        sa.Column("link_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "synthesized_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_item_id",
            sa.String(64),
            sa.ForeignKey("knowledge_items.id", ondelete="NO ACTION"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "synthesized_object_id",
            "knowledge_item_id",
            name="uq_synthesized_evidence_links_pair",
        ),
    )
    op.create_index(
        "ix_synthesized_evidence_links_project",
        "synthesized_evidence_links",
        ["project_id"],
    )
    op.create_index(
        "ix_synthesized_evidence_links_item",
        "synthesized_evidence_links",
        ["knowledge_item_id"],
    )

    op.create_table(
        "attention_items",
        sa.Column("item_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(400), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("identity_key", sa.String(200), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column(
            "synthesized_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=True,
        ),
        sa.Column("priority", sa.BigInteger(), nullable=False),
        sa.Column("actions", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_attention_items_project_status",
        "attention_items",
        ["project_id", "status"],
    )
    op.create_index(
        "uq_attention_items_identity",
        "attention_items",
        ["project_id", "identity_key"],
        unique=True,
        postgresql_where=sa.text("identity_key IS NOT NULL"),
    )

    op.create_table(
        "reconciliation_events",
        sa.Column("event_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_reconciliation_events_key"),
    )
    op.create_index(
        "ix_reconciliation_events_project",
        "reconciliation_events",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_events_project", table_name="reconciliation_events")
    op.drop_table("reconciliation_events")
    op.drop_index("uq_attention_items_identity", table_name="attention_items")
    op.drop_index("ix_attention_items_project_status", table_name="attention_items")
    op.drop_table("attention_items")
    op.drop_index("ix_synthesized_evidence_links_item", table_name="synthesized_evidence_links")
    op.drop_index("ix_synthesized_evidence_links_project", table_name="synthesized_evidence_links")
    op.drop_table("synthesized_evidence_links")
    op.drop_index("ix_synthesized_objects_project", table_name="synthesized_objects")
    op.drop_table("synthesized_objects")
    op.drop_index("ix_knowledge_evidence_roles_project", table_name="knowledge_evidence_roles")
    op.drop_table("knowledge_evidence_roles")
