"""Re-embed knowledge into the current embedding space.

Run after changing the embedding model. Chunks embedded at an earlier version
hold vectors from a space the current search no longer queries, so they are
invisible to semantic retrieval until this has run — lexical search is
unaffected throughout.

Safe to interrupt and safe to rerun: each pass processes only what is still
outstanding. Safe to run twice at once: claiming is a compare-and-set, so two
runners divide the work rather than duplicating it.

Usage::

    KAE_DATABASE_URL=... KAE_EMBEDDING=titan \\
        python scripts/development/reembed-knowledge.py [options]

    --project <id>     limit to one project
    --batch-size <n>   chunks per pass (default 50)
    --max-chunks <n>   stop after this many, leaving the rest outstanding
    --dry-run          report what would be done, embed nothing
    --release-claims   return chunks stranded by a dead runner, then exit

Exits non-zero if any chunk failed, without rolling back the ones that
succeeded — a partial migration is progress, and the next run resumes.
"""

import argparse
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.agents import provider
from kae_memory.application import MemoryService, MigrationReport, ReembeddingService
from kae_memory.domain.chunks import EMBEDDING_VERSION
from kae_memory.domain.identifiers import ProjectId


def _report_line(report: MigrationReport) -> str:
    return (
        f"  attempted={report.attempted} succeeded={report.succeeded} "
        f"failed={report.failed} skipped={report.skipped} remaining={report.remaining}"
    )


def main() -> int:
    """Migrate outstanding chunks and report what happened."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-chunks", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--release-claims", action="store_true")
    args = parser.parse_args()

    url = os.environ.get("KAE_DATABASE_URL", "").strip()
    if not url:
        print("KAE_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        embedder, name = provider.build_embedder(os.environ)
    except provider.ProviderConfigurationError as error:
        print(f"embedding provider is not configured: {error}", file=sys.stderr)
        return 2

    factory = sessionmaker(create_engine(url, pool_pre_ping=True))
    service = ReembeddingService(factory, embedder)
    project_id = ProjectId(args.project) if args.project else None

    described = provider.describe(os.environ)
    print(f"provider={name} target_version={EMBEDDING_VERSION} {described}")
    if not described["ranks_by_meaning"]:
        # Not refused: re-embedding into the deterministic space is a legitimate
        # way to reset state. But nobody should do it by accident.
        print(
            "  note: this provider does not rank by meaning; the corpus will be "
            "searchable and semantically useless.",
            file=sys.stderr,
        )

    if args.release_claims:
        released = service.release_claims(project_id)
        print(f"released {released} stranded claim(s)")
        return 0

    outstanding = service.outstanding(project_id)
    print(f"outstanding: {outstanding} chunk(s)")
    if args.dry_run:
        memory = MemoryService(factory)
        for project in memory.list_projects():
            if project_id and project.id != project_id:
                continue
            count = service.outstanding(project.id)
            if count:
                print(f"  {project.name}: {count}")
        print("dry run — nothing embedded")
        return 0
    if not outstanding:
        return 0

    report = service.migrate(
        project_id,
        batch_size=args.batch_size,
        max_chunks=args.max_chunks,
        progress=lambda r: print(_report_line(r), flush=True),
    )

    print("\nfinal:")
    print(_report_line(report))
    print(f"  model={report.model} version={report.target_version} complete={report.complete}")
    for failure in report.failures:
        print(f"  FAILED {failure.chunk_id} [{failure.error_code}] {failure.detail}")

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
