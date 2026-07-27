"""The retrieval evaluation fixture.

ADR-0008 is explicit that creating embeddings and an index is not evidence that
retrieval works: a vector index will happily return the eight least-wrong answers
to a query it fundamentally cannot serve. Acceptance requires the expected
knowledge item to appear in the top-k for a fixed set of representative queries.

**What this file can and cannot prove.** The suite runs offline against the
deterministic, hash-derived embedder, which has no notion of meaning. Against it
the fixture verifies the *harness*: that every query runs, that scoring and
ranking work, that top-k is respected, and that a regression in the retrieval
path is caught. It cannot verify that semantically related text ranks highly,
because the embedder does not model semantics.

Ranking *quality* is measured by running the same fixture against Titan, which is
a live provider call and therefore opt-in — never in CI. Set
``KAE_EVAL_LIVE_EMBEDDING=1`` with AWS credentials to run it that way. The
distinction matters: passing here means the plumbing is sound, not that recall is
good, and only the live run answers the second question.
"""

import os
from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicEmbeddingAdapter
from kae_memory.agents.embedding import EmbeddingPort
from kae_memory.application import MemoryService, RetrievalService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId

TOP_K = 8
"""ADR-0008's approved default retrieval limit."""


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One query and the knowledge it should surface."""

    query: str
    expected_contains: str
    why_it_matters: str


CORPUS: list[tuple[str, str]] = [
    (
        "decision",
        "A dedicated worker claims agent runs using renewable CockroachDB leases "
        "and fencing tokens.",
    ),
    ("decision", "Recovery after worker death resumes from the latest durable checkpoint."),
    ("rule", "The reporting cycle duration is configurable per ministry organisation."),
    ("rule", "Corrections supersede prior knowledge versions rather than deleting them."),
    ("requirement", "Every knowledge version carries provenance identifying its source and actor."),
    ("requirement", "A user submission is persisted verbatim before any interpretation occurs."),
    ("requirement", "Confirmed project knowledge is retrievable in a later session."),
    (
        "constraint",
        "CockroachDB MCP is used for inspection and management only, never domain writes.",
    ),
    ("constraint", "The application never holds a transaction open across an external model call."),
    ("actor", "Ministry coordinators submit monthly reports for review."),
    ("actor", "A human reviewer confirms, rejects, or revises candidate knowledge."),
    ("goal", "Replace the physical reporting binder used by ministry coordinators."),
    ("goal", "Prove that engineering memory survives across agent sessions."),
    ("unknown", "Who approves a submitted report before it is filed is undecided."),
    ("unknown", "The retention period for superseded knowledge versions is undecided."),
    ("assumption", "CockroachDB remains the durable memory foundation for the release."),
    ("assumption", "One worker with one active run is sufficient for the demonstration."),
    ("decision", "Embeddings attach to knowledge chunks rather than to whole entities."),
]
"""Eighteen items across all knowledge kinds, inside ADR-0008's 15-25 band."""

CASES: list[EvalCase] = [
    EvalCase(
        query="How does KAE recover after its worker dies?",
        expected_contains="resumes from the latest durable checkpoint",
        why_it_matters="Recovery is the central demonstration proof.",
    ),
    EvalCase(
        query="What happens to a fact when the user corrects it?",
        expected_contains="supersede prior knowledge versions",
        why_it_matters="Supersession without deletion is a product promise.",
    ),
    EvalCase(
        query="Can an agent write directly to the database?",
        expected_contains="inspection and management only",
        why_it_matters="The MCP write boundary protects the audit trail.",
    ),
    EvalCase(
        query="How do we know where a piece of knowledge came from?",
        expected_contains="provenance identifying its source",
        why_it_matters="Provenance is what makes the blueprint auditable.",
    ),
    EvalCase(
        query="Who files the reports?",
        expected_contains="Ministry coordinators submit monthly reports",
        why_it_matters="Actor retrieval drives the discovery workspace.",
    ),
    EvalCase(
        query="What is still undecided about report approval?",
        expected_contains="Who approves a submitted report",
        why_it_matters="Surfacing gaps is half the product.",
    ),
    EvalCase(
        query="Is the reporting schedule fixed?",
        expected_contains="reporting cycle duration is configurable",
        why_it_matters="The correction beat of the demo depends on this rule.",
    ),
    EvalCase(
        query="Why is the user's original wording kept?",
        expected_contains="persisted verbatim before any interpretation",
        why_it_matters="Verbatim capture is what provenance points back to.",
    ),
]
"""Eight cases spanning recovery, supersession, boundaries, provenance, actors,
gaps, rules, and verbatim capture."""


def _live_embedder() -> EmbeddingPort | None:
    """Return the Titan adapter when a live evaluation is explicitly requested."""

    if os.environ.get("KAE_EVAL_LIVE_EMBEDDING") != "1":
        return None
    from kae_memory.agents.titan import TitanEmbeddingAdapter

    return TitanEmbeddingAdapter(region=os.environ.get("AWS_REGION", "us-east-1"))


@pytest.fixture
def evaluated(factory: sessionmaker[Session]) -> tuple[RetrievalService, ProjectId]:
    """Seed the corpus, chunk it, embed it, and return a ready service."""

    memory = MemoryService(factory)
    project = memory.create_project("KAE evaluation", key="kae-eval")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "eval-seed")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="evaluation corpus")
            for kind, content in CORPUS
        ],
    )
    for item in items:
        memory.confirm_knowledge(item.id)

    retrieval = RetrievalService(factory, _live_embedder() or DeterministicEmbeddingAdapter())
    for item in items:
        retrieval.chunk_knowledge(item, project.name)
    embedded = retrieval.embed_pending(project.id, limit=200)
    assert embedded == len(CORPUS)

    return retrieval, project.id


def test_every_case_returns_results_within_the_top_k(
    evaluated: tuple[RetrievalService, ProjectId],
) -> None:
    """The harness runs: every query is answerable and top-k is respected."""

    retrieval, project_id = evaluated

    for case in CASES:
        hits = retrieval.search(project_id, case.query, limit=TOP_K)
        assert hits, f"no results at all for {case.query!r}"
        assert len(hits) <= TOP_K
        assert all(hit.why for hit in hits), "every hit must explain itself"


def test_results_are_ranked_by_ascending_distance(
    evaluated: tuple[RetrievalService, ProjectId],
) -> None:
    """Nearest first. A ranking bug would make top-k meaningless."""

    retrieval, project_id = evaluated

    hits = retrieval.search(project_id, CASES[0].query, limit=TOP_K)

    distances = [hit.distance for hit in hits]
    assert distances == sorted(distances)


def test_scoring_reports_recall_at_k(evaluated: tuple[RetrievalService, ProjectId]) -> None:
    """Score the fixture and report recall.

    Against the deterministic embedder recall is expected to be near zero — it
    has no semantics — so this asserts the *scoring* works and prints the number.
    Under ``KAE_EVAL_LIVE_EMBEDDING=1`` the same code measures real quality, and
    the threshold below is enforced.
    """

    retrieval, project_id = evaluated
    live = os.environ.get("KAE_EVAL_LIVE_EMBEDDING") == "1"

    matched: list[str] = []
    missed: list[str] = []
    for case in CASES:
        hits = retrieval.search(project_id, case.query, limit=TOP_K)
        found = any(case.expected_contains.lower() in hit.text.lower() for hit in hits)
        (matched if found else missed).append(case.query)

    recall = len(matched) / len(CASES)
    # Chance-level recall is roughly TOP_K / len(CORPUS): with 8 of 18 items
    # returned, a random ranker scores about 44%. Anything near that number is
    # noise, which is exactly what the deterministic embedder should produce.
    chance = TOP_K / len(CORPUS)
    print(f"\nrecall@{TOP_K}: {recall:.0%} ({len(matched)}/{len(CASES)})")
    print(f"chance level: {chance:.0%} — recall near this means no semantic signal")
    print(f"embedder: {'Titan (live)' if live else 'deterministic (no semantics)'}")
    for query in missed:
        print(f"  missed: {query}")

    assert len(matched) + len(missed) == len(CASES), "every case must be scored"
    if live:
        assert recall >= 0.75, (
            f"recall@{TOP_K} was {recall:.0%}; the approved model should surface the "
            "expected item for at least three quarters of the fixture"
        )
