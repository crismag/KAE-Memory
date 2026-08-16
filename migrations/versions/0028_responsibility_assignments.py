"""``responsibility_assignments`` — who is responsible for what (`SYN-5a`, D-121).

Additive over revision 0027. One new table, no existing column altered, no row
rewritten, nothing backfilled.

Doc 03's spine is the relation ``Role × Subject → Responsibility``, and this is
where it lands. The role is a ``synthesized_objects`` row in the ``actor``
domain; the subject is a readiness area key.

Identity is ``(role_object_id, subject_key)``. A role holds one letter over one
subject, so a synthesis rerun over unchanged evidence updates the letter in
place rather than stacking a second reading of the same sentence — the same
idempotence ``synthesized_objects`` gets from ``(project, domain, identity_key)``.

**No column holds the role's kind.** A persona is defined by holding no
responsibility anywhere, which is a query against this table; storing the answer
beside it would let the two disagree after a rerun.

Reversible: ``downgrade`` drops the table. Nothing else in the schema refers to
it, and no existing behaviour reads it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "responsibility_assignments",
        sa.Column("assignment_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "role_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=False,
        ),
        sa.Column("subject_key", sa.String(120), nullable=False),
        sa.Column("letter", sa.String(32), nullable=False),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "role_object_id", "subject_key", name="uq_responsibility_assignments_cell"
        ),
    )
    op.create_index(
        "ix_responsibility_assignments_project",
        "responsibility_assignments",
        ["project_id", "subject_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_responsibility_assignments_project", table_name="responsibility_assignments")
    op.drop_table("responsibility_assignments")
