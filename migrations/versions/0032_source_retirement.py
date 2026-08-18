"""``project_sources.retired_at`` — a source is stopped, not erased (`SRC-ACT`, `D-254`).

Additive over revision 0031. One nullable column, no existing column altered, no
row rewritten, nothing backfilled. Every existing source reads NULL, which is
what it already meant: nobody has retired it.

`D-230` is the owner's ruling — removing a source does not remove what it taught
KAE — and `D-254` is why that cannot be a ``DELETE``. The knowledge would in fact
survive, since nothing cascades from here to ``knowledge_items`` or ``messages``,
but `D-164` carries ``source_id`` on each run's ``input_context`` and
``SourceService.material`` groups ingested documents by it. Deleting the row
turns every document the source ever produced into *material naming no source*.
The knowledge outlives the deletion; the answer to *where did this come from*
does not.

**Not a fifth ``state``.** ``configured → readable → pinned → analyzed`` is a
progression, and retirement is orthogonal to every point on it — the shape
`ADR-0008` gave ``conflicted`` against its own ladder. A fifth value would make
*retired and pinned* inexpressible, and pinning is exactly what somebody would
want to still be able to read off a source they have stopped reading.

A timestamp rather than a boolean, because *when* is the question anybody asks
second and a boolean cannot be made to answer it later without a backfill that
would have to invent the answer.

Reversible: ``downgrade`` drops the column. Nothing else in the schema refers to
it, and code that predates it reads every source exactly as it did before.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "project_sources",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_sources", "retired_at")
