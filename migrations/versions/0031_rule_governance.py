"""``rule_attributions`` and ``rule_enforcement_mechanisms`` (`SYN-5c`, `D-133`).

Additive over revision 0030. Two new tables, no existing column altered, no row
rewritten, nothing backfilled.

`D-132` refused to let KAE decide either of these. A rule's authority comes from
where it came from and never from its wording, so the origin cannot be derived;
a rule is an enforceable control when a mechanism is named for it, and a
mechanism KAE named would make every rule enforceable by the act of synthesising
it. Both therefore arrive from a person, and neither has anywhere else to live.

**Two tables rather than one**, because a rule has exactly one origin and zero or
more mechanisms. Sharing a table would repeat the origin on every mechanism row —
one answer stored in several places, free to disagree after a rerun.

Identity is the rule for an attribution and ``(rule, normalised name)`` for a
mechanism, so re-stating either updates in place rather than stacking a second.

**No synthesis run writes to either**, which is what makes a row mean something:
it exists because a person wrote it. Neither table has a status column for a
reader to forget to filter on, for `D-126`'s reason. Whether an attributed
source was accepted is read from that source and stored nowhere here.

Reversible: ``downgrade`` drops both tables. Nothing else in the schema refers to
them, and no existing behaviour reads them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "rule_attributions",
        sa.Column("attribution_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "rule_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(64), nullable=False),
        sa.Column(
            "source_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("rule_object_id", name="uq_rule_attributions_rule"),
    )
    op.create_index(
        "ix_rule_attributions_project",
        "rule_attributions",
        ["project_id", "rule_object_id"],
    )

    op.create_table(
        "rule_enforcement_mechanisms",
        sa.Column("mechanism_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column(
            "rule_object_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("synthesized_objects.object_id", ondelete="NO ACTION"),
            nullable=False,
        ),
        sa.Column("identity_key", sa.String(200), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "rule_object_id", "identity_key", name="uq_rule_enforcement_mechanisms_name"
        ),
    )
    op.create_index(
        "ix_rule_enforcement_mechanisms_rule",
        "rule_enforcement_mechanisms",
        ["project_id", "rule_object_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_rule_enforcement_mechanisms_rule", table_name="rule_enforcement_mechanisms")
    op.drop_table("rule_enforcement_mechanisms")
    op.drop_index("ix_rule_attributions_project", table_name="rule_attributions")
    op.drop_table("rule_attributions")
