"""Pin the inputs a deliverable was rendered from (N20.1).

Additive over revision 0014. Three nullable columns and one boolean; no
existing column changes and no row is rewritten.

Revision 0014 recorded `source_knowledge` as identifiers. Assembly reads
`current_version`, so a corrected statement changes what a re-render produces
while those identifiers stay the same — the deliverable would appear
reproducible and would not be. Knowledge versions are immutable and
append-only, which is what makes a pinned `(knowledge_id, version)` a promise
rather than a hope.

Statements are not the only input. `render_inputs` captures the rest: purpose,
scope, whether proposed statements were included, the ordering contract, the
generator version, the package schema, the knowledge revision, and — for
module scope — a fingerprint of the module graph that decided what the scope
contained.

**Existing rows are not backfilled.** Their exact inputs cannot be proven, and
a fabricated pin is worse than an absent one: it would make an unprovable claim
look proven. They stay readable, and `publication_eligible` is `false` for
them, which is why the column defaults to false rather than true.

Artifact hashes are untouched and remain the final proof. Eligibility says the
inputs exist to attempt reproduction; only the hash says the attempt succeeded.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.add_column("deliverables", sa.Column("statement_pins", JSONB, nullable=True))
    op.add_column("deliverables", sa.Column("render_inputs", JSONB, nullable=True))
    op.add_column(
        "deliverables",
        sa.Column(
            "publication_eligible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_deliverables_publication_eligible",
        "deliverables",
        ["project_id", "publication_eligible"],
    )


def downgrade() -> None:
    op.drop_index("ix_deliverables_publication_eligible", table_name="deliverables")
    op.drop_column("deliverables", "publication_eligible")
    op.drop_column("deliverables", "render_inputs")
    op.drop_column("deliverables", "statement_pins")
