"""Record supersession by classifier version, not by row id (N4).

Additive-equivalent over revision 0011. `observation_classifications` gained a
`superseded_by` UUID column in 0011, and nothing ever wrote it — the repository
method that would have was never called. The type error therefore survived the
tests that shipped with it, and appeared the moment N4 wired a caller:

    invalid input syntax for type uuid: "1.0"

A UUID was the wrong shape for what supersession means here. One old
classification is not replaced by one new row; a whole result set is retired
when a **classifier version** is upgraded, and the useful question a history
view asks is "which version retired this", not "which row". So the column
becomes the version string it always wanted to be.

No data is lost, because no row can hold a value: the column was unwritten by
construction. That is the same fact from two directions — a column nothing
writes is a column whose type nothing checks.

Revision ID: 0012
Revises: 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("observation_classifications", "superseded_by")
    op.add_column(
        "observation_classifications",
        sa.Column("superseded_by_version", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("observation_classifications", "superseded_by_version")
    op.add_column(
        "observation_classifications",
        sa.Column("superseded_by", sa.Uuid(as_uuid=False), nullable=True),
    )
