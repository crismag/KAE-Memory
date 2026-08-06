"""Publication attempt history (N29).

Additive over revision 0020. One new table; no existing table changes.

**Separate from `deliverables`, and the separation is the point.** An attempt is
an event; a deliverable is a record of an output that exists. Storing attempts
on the deliverable would mean a failed publication writing to an immutable
record, and would make "we could not reach S3" look like a property of the
document rather than of one attempt at one destination.

Append-oriented: a retry is a **new row**, never an update. "It failed twice and
then worked" is exactly the history an operator needs when it fails a third
time, and an overwriting design destroys it.

**No column for a download URL.** A presigned URL is a credential with a timer;
stored, it is useless by the time anyone reads it and dangerous until then.
`external_reference` names what was written — an object key, a commit SHA, a
path relative to a configured root — and the domain refuses one carrying a
signature.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_attempts",
        sa.Column("attempt_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("deliverable_id", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("package_hash", sa.String(120), nullable=True),
        sa.Column("package_size", sa.BigInteger(), nullable=True),
        sa.Column("external_reference", sa.Text(), nullable=True),
        sa.Column("verification_passed", sa.Boolean(), nullable=True),
        sa.Column("error_category", sa.String(40), nullable=False, server_default="none"),
        sa.Column("error_detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_by", sa.String(120), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Index("ix_publication_attempts_deliverable", "deliverable_id", "requested_at"),
        sa.Index("ix_publication_attempts_project", "project_id", "state"),
    )


def downgrade() -> None:
    op.drop_table("publication_attempts")
