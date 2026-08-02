"""Add idempotency to message ingestion.

Additive over revision 0005 (ADR-0018). Two nullable columns on ``messages``
and one unique index.

The columns are nullable so every existing row is untouched, and CockroachDB
permits many NULLs in a unique index — messages recorded without a key keep
working exactly as before.

The guarantee lives in the index, not in application code. A read-then-insert
races: two concurrent retries can both find nothing and both insert. The
constraint is what makes "exactly one record" true under concurrency, and the
service handles the resulting violation rather than trying to avoid it.

``payload_fingerprint`` is a SHA-256 over the normalised payload. Sameness is
decided by comparing fingerprints, never by comparing free text, so a
reformatted resubmission of the same content is still recognised as a replay.

Written by hand for the same reason as revisions 0004 and 0005: autogenerate
against CockroachDB reports cosmetic differences that are not real changes.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("idempotency_key", sa.String(length=200), nullable=True))
    op.add_column("messages", sa.Column("payload_fingerprint", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_messages_project_idempotency",
        "messages",
        ["project_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_messages_project_idempotency", table_name="messages")
    op.drop_column("messages", "payload_fingerprint")
    op.drop_column("messages", "idempotency_key")
