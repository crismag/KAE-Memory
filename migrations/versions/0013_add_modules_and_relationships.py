"""Add modules and structural relationships (N17, ADR-0025).

Additive over revision 0012. Two new tables; nothing existing is altered.

Separate from ``knowledge_relationships`` deliberately. ADR-0025 settled that
there are two vocabularies — epistemic edges between statements, structural
edges between parts of a system — and one table would make every read filter
for the half it did not want, with a plain string column as the only thing
keeping them apart.

The constraints carry rules the application would otherwise be the only thing
enforcing:

* exactly one target, module or statement, never both and never neither;
* no self-edges, because a module depending on itself is a typo rather than a
  cycle worth diagnosing;
* an edge is unique, because a duplicated ``owns`` would defeat the exclusivity
  rule it exists to support.

Cycles are **not** enforceable in DDL and are refused at write time instead.
That is stated here so a later reader does not assume the database is checking
something it cannot.

Revision ID: 0013
Revises: 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "modules",
        sa.Column("module_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("module_id"),
        sa.UniqueConstraint("project_id", "key", name="uq_modules_project_key"),
    )
    op.create_index("ix_modules_project", "modules", ["project_id"])

    op.create_table(
        "module_relationships",
        sa.Column("module_relationship_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("source_module_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("relation", sa.String(length=40), nullable=False),
        sa.Column("target_module_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("target_knowledge_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("module_relationship_id"),
        sa.ForeignKeyConstraint(["source_module_id"], ["modules.module_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_module_id"], ["modules.module_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_module_id",
            "relation",
            "target_module_id",
            "target_knowledge_id",
            name="uq_module_relationships_edge",
        ),
        sa.CheckConstraint(
            "(target_module_id IS NULL) <> (target_knowledge_id IS NULL)",
            name="ck_module_relationships_one_target",
        ),
        sa.CheckConstraint(
            "target_module_id IS NULL OR target_module_id <> source_module_id",
            name="ck_module_relationships_no_self_edge",
        ),
    )
    op.create_index(
        "ix_module_relationships_project", "module_relationships", ["project_id", "relation"]
    )
    op.create_index("ix_module_relationships_source", "module_relationships", ["source_module_id"])
    op.create_index("ix_module_relationships_target", "module_relationships", ["target_module_id"])


def downgrade() -> None:
    op.drop_index("ix_module_relationships_target", table_name="module_relationships")
    op.drop_index("ix_module_relationships_source", table_name="module_relationships")
    op.drop_index("ix_module_relationships_project", table_name="module_relationships")
    op.drop_table("module_relationships")
    op.drop_index("ix_modules_project", table_name="modules")
    op.drop_table("modules")
