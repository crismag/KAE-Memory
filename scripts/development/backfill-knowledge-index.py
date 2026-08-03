"""Index knowledge written before indexing was part of the write path.

Knowledge created before that fix committed without chunks, so no search could
reach it. This walks every project, chunks whatever is missing, and reports what
changed.

Uses the same `RetrievalService.chunk_knowledge` the product uses; it is
idempotent, so an already-indexed item is left alone and the script is safe to
re-run. Deliberately not a bespoke seeding path — a backfill that bypassed the
product lifecycle would leave rows that production could never have produced.

Embedding is not performed here. Chunks land pending, lexical search works
immediately, and vectors follow through the normal embedding pass.

Usage::

    KAE_DATABASE_URL=... python scripts/development/backfill-knowledge-index.py [--embed]
"""

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.agents import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, RetrievalService


def main() -> int:
    """Chunk every unindexed knowledge item, project by project."""

    url = os.environ.get("KAE_DATABASE_URL", "").strip()
    if not url:
        print("KAE_DATABASE_URL is not set", file=sys.stderr)
        return 2

    embed = "--embed" in sys.argv
    factory = sessionmaker(create_engine(url, pool_pre_ping=True))
    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())

    print(f"{'project':<24}{'items':>7}{'before':>8}{'after':>7}{'embedded':>10}")
    for project in memory.list_projects():
        before = retrieval.indexing_status(project.id)
        for item in memory.retrieve_knowledge(project.id, lifecycle=None):
            retrieval.chunk_knowledge(item, project.name)
        if embed:
            retrieval.embed_pending(project.id, limit=1000)
        after = retrieval.indexing_status(project.id)
        print(
            f"{project.name:<24}{after.knowledge_items:>7}{before.chunks:>8}"
            f"{after.chunks:>7}{after.embedded_chunks:>10}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
