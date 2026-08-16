"""Backfill ``knowledge_provenance_links.source_type`` (EPI-5a, D-105/D-106).

Data only. No column is added, altered or dropped — the column has been in the
schema since revision 0002 and nothing ever wrote it, so every producing link
in every deployment carries ``NULL``. ADR-0008 makes readiness derive from what
kind of source a statement came from, which cannot be answered while the field
that answers it is empty.

The rule here is the same one ``source_type_for_run`` applies to new writes, so
a backfilled row and a freshly written one agree:

- the ``architecture`` role derives from knowledge the project already holds and
  reaches nothing outside KAE — ``kae_inference``;
- a run whose ``input_context`` declares a ``source_type`` is believed;
- a run carrying a ``document`` was given one — ``imported_document``;
- anything else read a message in a session — ``user_statement``.

Message links carry no ``agent_run_id``, so they inherit from a sibling link on
the same knowledge item and fall back to ``user_statement``, which is what a
correction with no run behind it is.

``used_by`` links are left alone. They record that a run consumed knowledge,
which is not an origin.

Reversible: ``downgrade`` returns the column to ``NULL``, which is exactly the
state it was in.
"""

from __future__ import annotations

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | None = None
depends_on: str | None = None

PRODUCING = "('produced_by', 'derived_from_message')"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE knowledge_provenance_links AS l
        SET source_type = CASE
                WHEN r.agent_role = 'architecture' THEN 'kae_inference'
                WHEN r.input_context ->> 'source_type' IS NOT NULL
                    THEN r.input_context ->> 'source_type'
                WHEN r.input_context ->> 'document' IS NOT NULL
                    THEN 'imported_document'
                ELSE 'user_statement'
            END,
            source_reference = COALESCE(
                l.source_reference, r.input_context ->> 'document'
            )
        FROM agent_runs AS r
        WHERE l.agent_run_id = r.agent_run_id
          AND l.source_type IS NULL
          AND l.link_type IN {PRODUCING}
        """
    )
    op.execute(
        f"""
        UPDATE knowledge_provenance_links AS l
        SET source_type = COALESCE(
                (
                    SELECT sibling.source_type
                    FROM knowledge_provenance_links AS sibling
                    WHERE sibling.knowledge_item_id = l.knowledge_item_id
                      AND sibling.source_type IS NOT NULL
                    ORDER BY sibling.created_at
                    LIMIT 1
                ),
                'user_statement'
            )
        WHERE l.source_type IS NULL
          AND l.link_type IN {PRODUCING}
        """
    )


def downgrade() -> None:
    op.execute("UPDATE knowledge_provenance_links SET source_type = NULL")
