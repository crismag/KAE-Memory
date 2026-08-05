"""Add observation classifications and operational updates (T24).

Additive over revision 0010. Two new tables; nothing existing is altered, so
every prior row and query is untouched. In particular ``messages`` is not
touched: the submitted observation stays exactly as it was stored, and
everything derived from it points back at it.

Two tables rather than columns on ``messages``, because one observation
produces several classified spans and a span is not a property of the message.
Two tables rather than one, because a classification says what a span *was* and
an operational update says where the work *stands* — the first is immutable
once written, the second transitions.

Neither table is ``knowledge_items``. That table feeds readiness, and routing a
classified fragment into it would inflate coverage with text nobody proposed as
a requirement.

Idempotency lives in the unique indexes, not in application code, for the same
reason as revisions 0006 and 0007: a read-then-insert races, and two workers
replaying one classification would both find nothing and both write.

``project_id`` is a plain string carrying no foreign key, matching the
convention every table since 0001 has followed. ``message_id`` does carry one,
because a classification of a deleted observation is a record of nothing.

Written by hand for the same reason as revisions 0004 to 0010: autogenerate
reports cosmetic differences that are not real changes.

Revision ID: 0011
Revises: 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "observation_classifications",
        sa.Column("classification_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("classifier_name", sa.String(length=120), nullable=False),
        sa.Column("classifier_version", sa.String(length=40), nullable=False),
        sa.Column("semantic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column("retention_tier", sa.String(length=20), nullable=False),
        sa.Column("route", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("span_start", sa.BigInteger(), nullable=False),
        sa.Column("span_end", sa.BigInteger(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("extracted_fields", JSONB, nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("superseded_by", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("classification_id"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.message_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "message_id",
            "classifier_name",
            "classifier_version",
            "span_start",
            "span_end",
            name="uq_observation_classifications_span",
        ),
        sa.CheckConstraint("span_end > span_start", name="ck_observation_classifications_span"),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_observation_classifications_confidence",
        ),
    )
    op.create_index(
        "ix_observation_classifications_message",
        "observation_classifications",
        ["message_id", "span_start"],
    )
    op.create_index(
        "ix_observation_classifications_project_tier",
        "observation_classifications",
        ["project_id", "retention_tier"],
    )

    op.create_table(
        "operational_updates",
        sa.Column("operational_update_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("classification_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("reported_status", sa.String(length=40), nullable=True),
        sa.Column("current_status", sa.String(length=40), nullable=True),
        sa.Column("transition_type", sa.String(length=40), nullable=True),
        sa.Column("authority", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("verification", sa.String(length=20), nullable=True),
        sa.Column("effective_date", sa.String(length=40), nullable=True),
        sa.Column("date_role", sa.String(length=20), nullable=True),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("operational_update_id"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.message_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_operational_updates_project_idempotency",
        ),
    )
    op.create_index(
        "ix_operational_updates_project_state",
        "operational_updates",
        ["project_id", "state"],
    )
    op.create_index(
        "ix_operational_updates_subject",
        "operational_updates",
        ["project_id", "subject"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_updates_subject", table_name="operational_updates")
    op.drop_index("ix_operational_updates_project_state", table_name="operational_updates")
    op.drop_table("operational_updates")
    op.drop_index(
        "ix_observation_classifications_project_tier", table_name="observation_classifications"
    )
    op.drop_index(
        "ix_observation_classifications_message", table_name="observation_classifications"
    )
    op.drop_table("observation_classifications")
