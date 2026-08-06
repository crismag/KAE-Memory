"""Preliminary setup: questions, configuration, targets, connections (N25-N28).

Additive over revision 0019. Four new tables; no existing table changes.

**Four rather than one**, and the shapes differ enough that combining them would
cost more than the joins save:

`setup_questions` is deliberately **not** part of `messages`. A clarification is
derived from a finding, has no identity until materialised, and is answerable
only through the finding that produced it. A setup question has no finding,
targets a configuration field rather than a statement, and records whether its
answer becomes the project default. Forcing them together would need a purpose
discriminator plus four columns meaning nothing for half the rows, and every
query would have to remember which half it was reading.

`project_configuration` is one row per field rather than one row per project
with many columns. A field carries a state, evidence, a derivation, and who
confirmed it — that is a record, not a value, and a wide table would need those
five columns per field. One row per field also means adding a field is data
rather than a migration.

`publication_targets` and `provider_connections` are separate because a target
is a product decision and a connection is a runtime permission. A token expiring
must not erase a decision about where to publish. **Neither table has a
credential column**, and that is structural: a column that existed would be
serialised by some response eventually, written in a hurry by someone who did
not know it was there.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "setup_questions",
        sa.Column("setup_question_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("field_name", sa.String(120), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suggested_answer", sa.Text(), nullable=True),
        sa.Column("suggestion_evidence", sa.Text(), nullable=True),
        sa.Column("policy", sa.String(40), nullable=False),
        sa.Column("disposition", sa.String(40), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by", sa.String(120), nullable=True),
        sa.Column("becomes_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revisitable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        # One question per field per project. Asking someone the same thing
        # twice is the failure the clarification queue already learned to avoid.
        sa.UniqueConstraint("project_id", "field_name", name="uq_setup_questions_field"),
        sa.Index("ix_setup_questions_project", "project_id", "disposition"),
    )

    op.create_table(
        "project_configuration",
        sa.Column("project_id", sa.String(64), primary_key=True),
        sa.Column("field_name", sa.String(120), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
        sa.Column("derived_from_knowledge_id", sa.String(64), nullable=True),
        sa.Column("confirmed_by", sa.String(120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "provider_connections",
        sa.Column("connection_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        # A *reference* to a credential — an environment variable name, a
        # secret-manager path. Never a credential. There is no column for one.
        sa.Column("credential_reference", sa.String(400), nullable=True),
        sa.Column("authorized_by", sa.String(120), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Index("ix_provider_connections_project", "project_id", "provider"),
    )

    op.create_table(
        "publication_targets",
        sa.Column("target_id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("configuration", postgresql.JSONB(), nullable=True),
        sa.Column("connection_id", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_publication_targets_name"),
        sa.Index("ix_publication_targets_project", "project_id", "purpose"),
    )
    # At most one default per purpose, enforced by the index rather than by a
    # read-then-write. Two concurrent "make this the default" calls would both
    # find no existing default and both succeed.
    op.create_index(
        "uq_publication_targets_default",
        "publication_targets",
        ["project_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_publication_targets_default", table_name="publication_targets")
    op.drop_table("publication_targets")
    op.drop_table("provider_connections")
    op.drop_table("project_configuration")
    op.drop_table("setup_questions")
