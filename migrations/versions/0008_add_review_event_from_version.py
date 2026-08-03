"""Record the version a correction moved away from.

Additive over revision 0007. One nullable column; nothing existing is altered.

Confirmation and rejection decide *about* a version without changing it, so one
``version_number`` said everything. A correction appends a version, and an event
carrying only one number cannot answer which wording was replaced by which.
Deriving "resulting = prior + 1" would work until the first time it did not, and
an audit trail is the wrong place to hold an assumption like that.

NULL for confirmations and rejections, because there is no prior version to name
— not "unknown", but "no version changed".

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_review_events",
        sa.Column("from_version_number", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_review_events", "from_version_number")
