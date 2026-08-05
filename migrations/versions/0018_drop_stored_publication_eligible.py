"""Remove the stored `publication_eligible` column (N20.1 follow-up).

Eligibility is derived. `Deliverable.publication_eligible` computes it from the
render inputs and the statement pins, and every consumer — the HTTP schema, the
MCP payload, and the capability readiness service — reads that property. The
column was written at record time and **read by nothing**.

Manual testing made the cost concrete. A pre-fix row held `false` while the
derived property correctly reported `true`, so the table and the API disagreed
about the same deliverable. Two sources of truth where one is unread is not
redundancy; it is a trap for whoever queries the table directly.

Dropped rather than synchronised, because synchronising would mean maintaining
a value nobody reads. If eligibility ever needs to be filtered in SQL, it comes
back as a generated column or an index over the fields it derives from — both
of which cannot drift.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_deliverables_publication_eligible", table_name="deliverables")
    op.drop_column("deliverables", "publication_eligible")


def downgrade() -> None:
    op.add_column(
        "deliverables",
        sa.Column("publication_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_deliverables_publication_eligible",
        "deliverables",
        ["project_id", "publication_eligible"],
    )
