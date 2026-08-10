"""Which claim inside an area a statement establishes (RUN-D14).

Additive over revision 0022. One nullable column on an existing table, no
backfill, no data rewritten.

**Why nullable, and why that is the honest reading.** Every link written before
this existed said "this statement is about the problem and value of this
project". That is still true — it simply does not say *which half*. A NULL here
means exactly that, and it is different from a claim nobody has established.

So an unclaimed link still counts toward its area, and a divided area with only
unclaimed links reaches `partial` and never `sufficient`. Backfilling a guess —
"most of these are probably problem statements" — would manufacture coverage
from a hunch, which is the failure the whole readiness model exists to prevent.

**Why a column rather than a claim table.** A statement establishes at most one
claim inside one area, and the link row already carries that pair. A separate
table would model a many-to-many nobody needs and give two places to look for
one fact.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_area_links",
        sa.Column("claim_key", sa.String(80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_area_links", "claim_key")
