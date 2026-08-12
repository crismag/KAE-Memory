"""Where a project's material comes from, and what was pinned (`D-21`).

Additive over revision 0024. One new table, no column altered, no row rewritten,
nothing backfilled.

`AUD-005` has been open since the audit: Studio's `AcquisitionService` held
`self._sources: dict`, so a person who connected a repository, set its include
and exclude paths, and pinned a revision lost every part of it on the next
deploy. `ADR-0004` ruled that KAE-Memory owns the source reference — location,
pinned revision, digest, disposition — and recorded that no such table existed.
This is that table.

**It never holds the content.** A source names material; the material itself
lives where the ruling put it. A repository read at volume belongs in the user's
own repository with a coordinate here, which is the failure this whole decision
exists to prevent.

**`disposition` is nullable on purpose.** `ADR-0004` defines five and they gate
ingestion at volume. Defaulting to `MEMORY` would let a source nobody has
classified pass for one somebody decided to keep, which is the more expensive of
the two mistakes and the harder one to see.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "project_sources",
        sa.Column("source_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("location", sa.String(600), nullable=False),
        sa.Column("connection_id", sa.Uuid(as_uuid=False), nullable=True),
        # Same JSONB the setup tables use (`0020`), for the same reason:
        # this is Studio's shape and Memory has no rule that reads inside it.
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("pinned_revision", sa.String(120), nullable=True),
        sa.Column("digest", sa.String(120), nullable=True),
        sa.Column("disposition", sa.String(40), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One source per location per kind. Registering the same repository
        # twice is one source registered twice, so a caller that loses its
        # response can retry — the rule projects and modules already follow.
        sa.UniqueConstraint("project_id", "kind", "location", name="uq_project_sources_location"),
    )
    op.create_index("ix_project_sources_project", "project_sources", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_sources_project", table_name="project_sources")
    op.drop_table("project_sources")
