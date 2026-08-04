"""Run the retrieval evaluation set against a live corpus.

Answers one question: is semantic retrieval good enough to rely on, and where is
it not. A cosine query returning rows is not evidence of that — every query here
has an expected answer written before the run, and a wrong confident answer is
recorded as worse than no answer.

Usage::

    KAE_DATABASE_URL=... KAE_EMBEDDING=titan \\
        python scripts/development/evaluate-retrieval.py

Reports per-category hit rates, semantic against lexical, latency, and every
query that failed with the ranking that caused it.
"""

import os
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.retrieval.evaluation_set import CASES, EvalCase, QueryKind

from kae_memory.agents import provider
from kae_memory.application import MemoryService, RetrievalService

TOP_K = 5


@dataclass(frozen=True, slots=True)
class Outcome:
    """One query measured under one retrieval mode."""

    case: EvalCase
    mode: str
    texts: tuple[str, ...]
    latency_ms: float

    @property
    def rank(self) -> int | None:
        """1-indexed rank of the first acceptable result, or None."""

        for index, text in enumerate(self.texts, start=1):
            if any(marker.lower() in text.lower() for marker in self.case.relevant):
                return index
        return None

    @property
    def top1(self) -> bool:
        return self.rank == 1

    @property
    def top3(self) -> bool:
        return self.rank is not None and self.rank <= 3

    @property
    def misleading(self) -> bool:
        """A confident answer that should not have been given."""

        if not self.texts:
            return False
        first = self.texts[0].lower()
        if any(bad.lower() in first for bad in self.case.unacceptable):
            return True
        # A weak query returning anything at all is presenting noise as signal.
        return self.case.kind is QueryKind.WEAK


def _resolve(memory: MemoryService, name: str | None) -> object | None:
    if name is None:
        return None
    for project in memory.list_projects():
        if project.name == name:
            return project.id
    raise SystemExit(f"evaluation set names a project that does not exist: {name!r}")


def _run(retrieval: RetrievalService, case: EvalCase, project_id: object, mode: str) -> Outcome:
    started = time.perf_counter()
    if mode == "semantic":
        hits = retrieval.search(project_id, case.query, limit=TOP_K)  # type: ignore[arg-type]
    else:
        hits = retrieval.find(project_id, case.query, limit=TOP_K)  # type: ignore[arg-type]
    elapsed = (time.perf_counter() - started) * 1000
    return Outcome(case, mode, tuple(hit.text for hit in hits), elapsed)


def _rate(outcomes: Sequence[Outcome], attribute: str) -> float:
    if not outcomes:
        return 0.0
    return 100 * sum(bool(getattr(o, attribute)) for o in outcomes) / len(outcomes)


def main() -> int:
    """Evaluate and report."""

    url = os.environ.get("KAE_DATABASE_URL", "").strip()
    if not url:
        print("KAE_DATABASE_URL is not set", file=sys.stderr)
        return 2

    embedder, name = provider.build_embedder(os.environ)
    factory = sessionmaker(create_engine(url, pool_pre_ping=True))
    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, embedder)

    print(f"provider={name} ranks_by_meaning={provider.ranks_by_meaning(name)} top_k={TOP_K}")
    print(f"cases={len(CASES)}\n")

    results: dict[str, list[Outcome]] = {"semantic": [], "lexical": []}
    for case in CASES:
        project_id = _resolve(memory, case.project)
        for mode in ("semantic", "lexical"):
            results[mode].append(_run(retrieval, case, project_id, mode))

    print(f"{'category':<22}{'n':>3}{'sem top3':>10}{'lex top3':>10}{'sem top1':>10}")
    for kind in QueryKind:
        sem = [o for o in results["semantic"] if o.case.kind is kind]
        lex = [o for o in results["lexical"] if o.case.kind is kind]
        if kind is QueryKind.WEAK:
            print(
                f"{kind.value:<22}{len(sem):>3}"
                f"{100 - _rate(sem, 'misleading'):>9.0f}%{100 - _rate(lex, 'misleading'):>9.0f}%"
                f"{'(quiet)':>10}"
            )
            continue
        print(
            f"{kind.value:<22}{len(sem):>3}{_rate(sem, 'top3'):>9.0f}%"
            f"{_rate(lex, 'top3'):>9.0f}%{_rate(sem, 'top1'):>9.0f}%"
        )

    graded = [o for o in results["semantic"] if o.case.kind is not QueryKind.WEAK]
    graded_lex = [o for o in results["lexical"] if o.case.kind is not QueryKind.WEAK]
    ranks = [o.rank for o in graded if o.rank]
    mrr = statistics.mean([1 / r for r in ranks]) if ranks else 0.0

    print(f"\noverall semantic top-3: {_rate(graded, 'top3'):.0f}%   MRR: {mrr:.2f}")
    print(f"overall lexical  top-3: {_rate(graded_lex, 'top3'):.0f}%")

    for mode in ("semantic", "lexical"):
        lat = [o.latency_ms for o in results[mode]]
        print(f"{mode:<9} latency  median={statistics.median(lat):.0f}ms  max={max(lat):.0f}ms")

    print("\nfailures and weaknesses:")
    problems = 0
    for outcome in results["semantic"]:
        if outcome.case.kind is QueryKind.WEAK:
            if outcome.texts:
                problems += 1
                print(f"  [weak-noise] {outcome.case.query!r} returned {len(outcome.texts)}")
                print(f"               top: {outcome.texts[0][:70]}")
            continue
        if not outcome.top3:
            problems += 1
            lex = next(o for o in results["lexical"] if o.case is outcome.case)
            print(f"  [miss] {outcome.case.query!r}")
            print(f"         expected one of: {outcome.case.relevant}")
            print(
                f"         semantic top: {(outcome.texts[0][:70] if outcome.texts else '<none>')}"
            )
            print(f"         lexical  top3: {'yes' if lex.top3 else 'no'}")
    if not problems:
        print("  none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
