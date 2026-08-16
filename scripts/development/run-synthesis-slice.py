"""Run the synthesis slice over one project's real evidence (`SYN-3d`).

Reconciliation, then the goal synthesizer, then unknown synthesis — the three
steps `SYN-2`, `SYN-3b` and `SYN-3c` shipped, composed the way the deployment
composes them, against a database that holds a real corpus rather than the
golden fixture.

Reports the counts on both sides of the run. They are evidence, not targets: a
live corpus that compacts less than the fixture did is a finding about the
corpus, and tuning a radius until the numbers match is how `D-16` happened.

Writes only into revision `0026`'s tables — synthesized objects, their evidence
bindings, attention items and reconciliation events — plus the evidence *role*
of a clustered member, which changes no lifecycle and hides no row. Every step
is idempotent on its own key, so a second run replays rather than duplicating.

Usage::

    KAE_DATABASE_URL=... KAE_EMBEDDING=ollama \\
        python scripts/development/run-synthesis-slice.py --project <id>

    --project <id>   required; this runs against real data, so name it
    --dry-run        report the before counts and stop
"""

import argparse
import os
import sys

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from kae_memory.agents import provider
from kae_memory.agents.goal_judge import default_goal_judge
from kae_memory.application.goal_synthesis_service import GoalSynthesisService
from kae_memory.application.reconciliation_service import ReconciliationService
from kae_memory.application.unknown_synthesis_service import UnknownSynthesisService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.tables import (
    AttentionItemRow,
    KnowledgeItemRow,
    SynthesizedObjectRow,
)


def _counts(factory: sessionmaker, project_id: str) -> dict[str, int]:
    """Read what exists for this project across the three layers."""

    with factory() as session:
        return {
            "knowledge_items": session.scalar(
                select(func.count())
                .select_from(KnowledgeItemRow)
                .where(KnowledgeItemRow.project_id == project_id)
            )
            or 0,
            "synthesized_objects": session.scalar(
                select(func.count())
                .select_from(SynthesizedObjectRow)
                .where(SynthesizedObjectRow.project_id == project_id)
            )
            or 0,
            "attention_items": session.scalar(
                select(func.count())
                .select_from(AttentionItemRow)
                .where(AttentionItemRow.project_id == project_id)
            )
            or 0,
        }


def main() -> int:
    """Run the slice and print what each step concluded."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("KAE_DATABASE_URL", "").strip()
    if not url:
        print("KAE_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        embedder, embedder_name = provider.build_embedder(os.environ)
    except provider.ProviderConfigurationError as error:
        # Not fatal. Without statement-space vectors every observation stands
        # alone, which each report says of itself as `clustered=False` — a model
        # that was not compacted must not read like one with nothing to compact.
        print(f"no embedding provider: {error}", file=sys.stderr)
        embedder, embedder_name = None, "none"

    factory = sessionmaker(create_engine(url, pool_pre_ping=True))
    project_id = ProjectId(args.project)
    judge = default_goal_judge()

    before = _counts(factory, args.project)
    print(f"embedder={embedder_name} judge={'ollama' if judge else 'none'}")
    print(f"before: {before}")
    if args.dry_run:
        print("dry run — nothing written")
        return 0

    reconciliation = ReconciliationService(factory).reconcile(project_id)
    print(
        f"reconciliation: {reconciliation.edges_written} edges, "
        f"{reconciliation.roles_written} roles, "
        f"{len(reconciliation.affected)} affected sections, "
        f"{len(reconciliation.resolved_item_ids)} resolved"
    )

    goals = GoalSynthesisService(factory, judge=judge, embedder=embedder).synthesize(project_id)
    print(
        f"goals: {len(goals.promoted)} promoted, {len(goals.withheld)} withheld, "
        f"from {goals.considered} considered "
        f"(clustered={goals.clustered} judged={goals.judged} replayed={goals.replayed})"
    )

    unknowns = UnknownSynthesisService(factory, embedder=embedder).synthesize(project_id)
    print(
        f"unknowns: {unknowns.considered} considered, {unknowns.resolved} already answered, "
        f"{unknowns.themes} themes, {len(unknowns.attention)} raised, "
        f"{len(unknowns.withheld)} below the bound "
        f"(clustered={unknowns.clustered} ranked_by_blocking={unknowns.ranked_by_blocking})"
    )
    for _, question in unknowns.attention:
        print(f"  attention: {question}")

    print(f"after: {_counts(factory, args.project)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
