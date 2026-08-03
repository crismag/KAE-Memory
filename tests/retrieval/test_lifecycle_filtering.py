"""Rejected and superseded knowledge must not come back from search (T13).

The defect this closes was live: lifecycle appeared only inside the embedded
metadata prefix, where no query could reach it, so a statement a person had
explicitly ruled out was ranked and returned like any other. The development
corpus held one such item at the time of writing.

Searchable and authoritative are kept apart deliberately. Proposed knowledge is
returned, because a reviewer cannot accept what they cannot see; it is labelled,
because a caller that treats it as established fact is the failure the label
exists to prevent.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, RetrievalService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.knowledge_review import RejectionReason
from kae_memory.domain.lifecycle import AUTHORITATIVE, HISTORICAL, LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.persistence.chunk_repository import ChunkRepository

APPROVED = "Only an authorised approver may approve a report."
REJECTED = "Only an authorised approver may approve a memo."
PROPOSED = "Only an authorised approver may approve a summary."


def _write(memory: MemoryService, project_id: ProjectId, key: str, content: str) -> KnowledgeItem:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content=content, source="interview")]
    )[0]


def _embed(factory: sessionmaker[Session], project_id: ProjectId) -> None:
    embedder = DeterministicEmbeddingAdapter()
    with factory() as db:
        chunks = ChunkRepository(db)
        for chunk in chunks.list_needing_embedding(project_id, limit=100):
            result = embedder.embed([chunk.text])
            chunks.store_embedding(
                chunk.id, result.vectors[0], embedder.model, embedder.dimensions, chunk.created_at
            )
        db.commit()


@pytest.fixture
def corpus(factory: sessionmaker[Session]) -> tuple[MemoryService, RetrievalService, ProjectId]:
    """One project holding a validated, a rejected, and a proposed statement."""

    memory = MemoryService(factory)
    project_id = memory.create_project("Ministry Reporting", key="lifecycle").id

    validated = _write(memory, project_id, "l1", APPROVED)
    memory.review_confirm(project_id, validated.id, expected_version=1, actor_id="cris")

    turned_down = _write(memory, project_id, "l2", REJECTED)
    memory.review_reject(
        project_id,
        turned_down.id,
        expected_version=1,
        reason_code=RejectionReason.INCORRECT,
        actor_id="cris",
    )

    _write(memory, project_id, "l3", PROPOSED)
    _embed(factory, project_id)

    return memory, RetrievalService(factory, DeterministicEmbeddingAdapter()), project_id


def _texts(hits) -> str:
    return " || ".join(hit.text for hit in hits)


class TestRejectedIsExcluded:
    def test_lexical_search_does_not_return_rejected_knowledge(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "approver", limit=20)

        assert hits, "the query matches statements that were not rejected"
        assert REJECTED not in _texts(hits)

    def test_semantic_search_does_not_return_rejected_knowledge(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        _, retrieval, project_id = corpus

        hits = retrieval.search(project_id, REJECTED, limit=20, max_distance=None)

        assert REJECTED not in _texts(hits)

    def test_an_exact_query_for_rejected_text_returns_nothing_of_it(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        """The strongest form: even asking for it by its own words.

        Excluded in SQL rather than filtered afterwards — a rejected chunk that
        displaced a good one inside LIMIT would already be lost.
        """

        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "memo", limit=20)

        assert REJECTED not in _texts(hits)


class TestProposedRemainsVisible:
    def test_proposed_knowledge_is_still_returned(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        """Hiding it until confirmation would make review impossible."""

        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "approver", limit=20)

        assert PROPOSED in _texts(hits)

    def test_every_hit_reports_whether_a_person_confirmed_it(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "approver", limit=20)

        by_text = {hit.text: hit for hit in hits}
        confirmed = next(h for t, h in by_text.items() if APPROVED in t)
        unconfirmed = next(h for t, h in by_text.items() if PROPOSED in t)

        assert confirmed.lifecycle is LifecycleState.VALIDATED
        assert confirmed.authoritative is True
        assert unconfirmed.lifecycle is LifecycleState.PROPOSED
        assert unconfirmed.authoritative is False

    def test_the_label_is_read_live_not_from_the_embedded_text(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        """The chunk body still says 'Status: proposed' for a confirmed item.

        Nothing rewrites the metadata prefix when a person confirms, so a label
        taken from the text would report confirmed knowledge as unreviewed.
        """

        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "approver", limit=20)
        confirmed = next(hit for hit in hits if APPROVED in hit.text)

        assert "Status: proposed" in confirmed.text
        assert confirmed.authoritative is True


class TestAuthoritativeScope:
    def test_authoritative_retrieval_returns_only_confirmed_knowledge(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        """For callers generating output rather than showing it for review."""

        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "approver", limit=20, lifecycle=AUTHORITATIVE)

        assert APPROVED in _texts(hits)
        assert PROPOSED not in _texts(hits)
        assert REJECTED not in _texts(hits)

    def test_semantic_authoritative_scope_matches(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        _, retrieval, project_id = corpus

        hits = retrieval.search(project_id, APPROVED, limit=20, lifecycle=AUTHORITATIVE)

        assert all(hit.authoritative for hit in hits)

    def test_historical_scope_can_still_reach_rejected_knowledge(
        self, corpus: tuple[MemoryService, RetrievalService, ProjectId]
    ) -> None:
        """Rejection is not deletion. Diagnostics must be able to find it."""

        _, retrieval, project_id = corpus

        hits = retrieval.find(project_id, "memo", limit=20, lifecycle=HISTORICAL)

        assert REJECTED in _texts(hits)


class TestSupersededIsExcluded:
    def test_a_superseded_statement_stops_being_returned(
        self,
        factory: sessionmaker[Session],
        corpus: tuple[MemoryService, RetrievalService, ProjectId],
    ) -> None:
        memory, retrieval, project_id = corpus
        old = _write(memory, project_id, "l4", "Reports are filed quarterly.")
        memory.confirm_knowledge(old.id)
        new = _write(memory, project_id, "l5", "Reports are filed monthly.")
        memory.supersede_knowledge(old.id, new.id)
        _embed(factory, project_id)

        hits = retrieval.find(project_id, "quarterly", limit=20)

        assert "quarterly" not in _texts(hits)
