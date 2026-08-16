"""``constraint_effects`` — what an accepted boundary bears on (`SYN-5e`, D-126).

Additive over revision 0028. One new table, no existing column altered, no row
rewritten, nothing backfilled.

Doc 07 opens by saying a constraint is worth having for the consequences it
imposes, so this is where those consequences land: a ``synthesized_objects`` row
in the ``constraint`` domain, an extracted unknown or assumption, and how the
first bears on the second.

Identity is ``(constraint_object_id, knowledge_item_id)``. A boundary bears on
an item one way, so a synthesis rerun over unchanged evidence updates the
reading in place.

**Only accepted constraints have rows here**, which is why there is no status
column. An unaccepted boundary's effects are computed and reported by the run
and written nowhere: with both stored, every reader of this relation would have
to remember to filter, and the first one that forgets silently closes a question
the project still has.

Reversible: ``downgrade`` drops the table. Nothing else in the schema refers to
it, and no existing behaviour reads it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "constraint_effects",
        sa.Column("effect_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "constraint_object_id",
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
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "constraint_object_id", "knowledge_item_id", name="uq_constraint_effects_pair"
        ),
    )
    op.create_index(
        "ix_constraint_effects_item",
        "constraint_effects",
        ["project_id", "knowledge_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_constraint_effects_item", table_name="constraint_effects")
    op.drop_table("constraint_effects")
