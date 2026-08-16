"""``acceptance_criteria`` — what a person says *done* looks like (`SYN-5b`, D-131).

Additive over revision 0029. One new table, no existing column altered, no row
rewritten, nothing backfilled.

`D-129` refused to let KAE write acceptance criteria: a criterion it generated
would make every requirement implementation-ready by the act of synthesising it,
which is `ADR-0008`'s objection in one line. Criteria arrive as evidence, and
their absence is the finding.

That leaves them with nowhere to live. A criterion is not derived from the
requirement's wording, and no ``KnowledgeKind`` names one, so this is the table
for the sentence a person writes against a requirement — doc 06's *Add
acceptance criteria* action.

Identity is ``(requirement_object_id, identity_key)``, the statement normalised
the way `identity_key_for` normalises everything else, so re-adding the same
criterion updates it in place rather than stacking a second.

**The synthesis run writes nothing here**, which is what makes a row mean
something: it exists because a person wrote it. There is no status column for a
reader to forget to filter on, for `D-126`'s reason.

Reversible: ``downgrade`` drops the table. Nothing else in the schema refers to
it, and no existing behaviour reads it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "acceptance_criteria",
        sa.Column("criterion_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "requirement_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=False,
        ),
        sa.Column("identity_key", sa.String(200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "requirement_object_id", "identity_key", name="uq_acceptance_criteria_wording"
        ),
    )
    op.create_index(
        "ix_acceptance_criteria_requirement",
        "acceptance_criteria",
        ["project_id", "requirement_object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_acceptance_criteria_requirement", table_name="acceptance_criteria")
    op.drop_table("acceptance_criteria")
