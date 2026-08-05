"""Record what a deliverable is for, and what a person accepted (N38).

Additive over revision 0016. One nullable column; no existing column changes
and no row is rewritten.

N20 and N20.1 pin *what was rendered*. Nothing recorded what it was rendered
**for**, nor that a person looked at a sparse project and decided the current
knowledge boundary was enough for this one generation. Both are facts about the
deliverable that a later reader needs and cannot reconstruct.

Deliberately one JSON column rather than a table. A qualification is written
once with its deliverable, never queried across projects, and never updated —
the shape of a document rather than a relation. Splitting it would buy joins
nobody needs and a second thing to keep in step with an immutable record.

Nullable, and not backfilled. A deliverable recorded before qualification
existed has none, and inventing one would describe a package nobody described.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deliverables", sa.Column("qualification", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("deliverables", "qualification")
