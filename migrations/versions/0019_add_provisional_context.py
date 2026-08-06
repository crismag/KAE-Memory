"""Record the uncertainty a deliverable was generated under (N20.2).

Additive over revision 0018. One nullable column; no existing column changes
and no row is rewritten.

N20.1 pinned what was rendered and the options it was rendered with, which makes
a package reproduce the same **bytes**. Nothing recorded what it was uncertain
about, which is what makes it reproduce the same **claim**. A package generated
with four open questions and two unaccepted assumptions said something weaker
than the identical bytes say after those were settled, and a reader holding the
second cannot tell it apart from the first.

Deliberately one JSON column, for the same reason as `qualification`: written
once with its deliverable, never queried across projects, never updated. A
relation would buy joins nobody needs and a second thing to keep in step with an
immutable record.

Nullable, and **not backfilled**. Current assumption states and current open
questions are exactly what a historical record must not consult — reconstructing
them from today would produce a record of what the package would mean now, filed
under what it meant then. A deliverable recorded before this existed stays
readable and says honestly that its uncertainty cannot be proven.

Revision ID: 0019
Revises: 0018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "deliverables", sa.Column("provisional_context", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("deliverables", "provisional_context")
