"""Semantic retrieval end to end.

These run a real ``VECTOR(1024)`` column, a real cosine operator, and a real
vector index on CockroachDB. Under the old SQLite suite none of this could have
been executed at all (ADR-0011).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicEmbeddingAdapter, is_normalised
from kae_memory.agents.embedding import EmbeddingProviderUnavailableError
from kae_memory.application import MemoryService, RetrievalService, WriteKnowledgeRequest
from kae_memory.domain.chunks import EmbeddingState, content_hash, split_text
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project
from kae_memory.persistence.chunk_repository import ChunkRepository

MOMENT = datetime(2026, 7, 27, tzinfo=UTC)


def _seed_knowledge(
    service: MemoryService, texts: list[tuple[str, str]]
) -> tuple[Project, tuple[KnowledgeItem, ...]]:
    """Create a project and confirm one knowledge item per (kind, content)."""

    project = service.create_project("Ministry reporting", key=f"proj-{id(texts)}")
    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "seed-1")
    items = service.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in texts
        ],
    )
    for item in items:
        service.confirm_knowledge(item.id)
    return project, items


def test_chunking_persists_unembedded_chunks(factory: sessionmaker[Session]) -> None:
    """Knowledge exists before any embedding does."""

    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
    project, items = _seed_knowledge(memory, [("rule", "Reporting cycles are configurable.")])

    chunks = retrieval.chunk_knowledge(items[0], project.name)

    assert len(chunks) == 1
    assert chunks[0].state is EmbeddingState.PENDING
    assert chunks[0].embedding_model is None
    # The metadata prefix rides along in the embedded text.
    assert "Type: rule" in chunks[0].text
    assert "Project: Ministry reporting" in chunks[0].text

    with factory() as db:
        stored = ChunkRepository(db).list_for_knowledge(items[0].id)
    assert len(stored) == 1
    assert stored[0].needs_embedding


def test_embedding_then_searching_returns_the_seeded_knowledge(
    factory: sessionmaker[Session],
) -> None:
    """A real cosine query over a real vector index."""

    memory = MemoryService(factory)
    embedder = DeterministicEmbeddingAdapter()
    retrieval = RetrievalService(factory, embedder)
    project, items = _seed_knowledge(
        memory,
        [
            ("rule", "The reporting cycle duration is configurable per ministry."),
            ("decision", "Store reporting configuration alongside the project record."),
            ("unknown", "Who approves a submitted report is undecided."),
        ],
    )
    for item in items:
        retrieval.chunk_knowledge(item, project.name)

    embedded = retrieval.embed_pending(project.id)
    assert embedded == 3

    # Query with a chunk's exact stored text. The deterministic embedder is
    # hash-derived, so it can prove the pipeline — vector written, index used,
    # nearest neighbour returned — but not that meaning ranks correctly. Ranking
    # quality is what the evaluation fixture measures, against the real model.
    with factory() as db:
        rule_chunk = ChunkRepository(db).list_for_knowledge(items[0].id)[0]

    hits = retrieval.search(project.id, rule_chunk.text)

    assert hits, "a vector search must return something once chunks are embedded"
    assert hits[0].distance == pytest.approx(0.0, abs=1e-6), "a chunk is nearest to its own text"
    assert hits[0].chunk_id == rule_chunk.id
    assert hits[0].kind is KnowledgeKind.RULE
    assert "cosine distance" in hits[0].why
    assert str(hits[0].knowledge_id) in hits[0].why


def test_search_is_scoped_to_one_project(factory: sessionmaker[Session]) -> None:
    """A project is the durable boundary. There are no cross-project reads."""

    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())

    mine, my_items = _seed_knowledge(memory, [("rule", "Reports are filed monthly.")])
    theirs, their_items = _seed_knowledge(memory, [("rule", "Reports are filed weekly.")])
    for item in my_items + their_items:
        retrieval.chunk_knowledge(item, mine.name if item.project_id == mine.id else theirs.name)
    retrieval.embed_pending(mine.id)
    retrieval.embed_pending(theirs.id)

    hits = retrieval.search(mine.id, "Reports are filed weekly.")

    assert hits, "the query should still match something inside its own project"
    returned = {str(hit.knowledge_id) for hit in hits}
    assert returned == {str(item.id) for item in my_items}
    assert str(their_items[0].id) not in returned


def test_search_can_filter_by_knowledge_kind(factory: sessionmaker[Session]) -> None:
    """Kind is a metadata filter on one index, not a separate index."""

    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
    project, items = _seed_knowledge(
        memory,
        [
            ("rule", "Cycles are configurable."),
            ("decision", "Cycles are stored as configuration."),
        ],
    )
    for item in items:
        retrieval.chunk_knowledge(item, project.name)
    retrieval.embed_pending(project.id)

    decisions = retrieval.search(project.id, "Cycles", kinds=[KnowledgeKind.DECISION])

    assert decisions
    assert {hit.kind for hit in decisions} == {KnowledgeKind.DECISION}


def test_embedding_failure_leaves_knowledge_intact(factory: sessionmaker[Session]) -> None:
    """Retrieval is an index over memory, not a precondition for it."""

    class BrokenEmbedder:
        model = "broken"

        def embed(self, texts: list[str]) -> object:
            raise EmbeddingProviderUnavailableError("provider down")

    memory = MemoryService(factory)
    project, items = _seed_knowledge(memory, [("rule", "Cycles are configurable.")])
    retrieval = RetrievalService(factory, BrokenEmbedder())  # type: ignore[arg-type]
    retrieval.chunk_knowledge(items[0], project.name)

    with pytest.raises(EmbeddingProviderUnavailableError):
        retrieval.embed_pending(project.id)

    # The authoritative knowledge is untouched, and the chunk stays retryable.
    confirmed = memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.VALIDATED)
    assert len(confirmed) == 1
    with factory() as db:
        chunks = ChunkRepository(db).list_for_knowledge(items[0].id)
    assert chunks[0].state is EmbeddingState.FAILED
    assert chunks[0].needs_embedding, "a failed embedding is retried, not abandoned"


def test_unembedded_chunks_are_never_returned(factory: sessionmaker[Session]) -> None:
    """A chunk with no vector cannot be ranked, so it must not appear."""

    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
    project, items = _seed_knowledge(memory, [("rule", "Cycles are configurable.")])
    retrieval.chunk_knowledge(items[0], project.name)

    assert retrieval.search(project.id, "Cycles") == ()


class TestChunking:
    def test_a_short_entity_stays_one_chunk(self) -> None:
        """Splitting one thought produces two chunks that each mean less."""

        assert len(split_text("The reporting cycle is configurable.")) == 1

    def test_a_long_document_splits_on_semantic_boundaries(self) -> None:
        paragraphs = "\n\n".join(f"Paragraph {index}. " * 60 for index in range(6))

        chunks = split_text(paragraphs)

        assert len(chunks) > 1
        assert all(chunk.strip() for chunk in chunks)
        # Boundaries fall between paragraphs, not mid-sentence.
        assert not any(chunk.startswith(" ") for chunk in chunks)

    def test_content_hash_detects_changed_text(self) -> None:
        assert content_hash("a") != content_hash("b")
        assert content_hash("a") == content_hash("a")


class TestDeterministicEmbedding:
    def test_same_text_embeds_identically(self) -> None:
        adapter = DeterministicEmbeddingAdapter()

        first = adapter.embed(["hello"]).vectors[0]
        second = adapter.embed(["hello"]).vectors[0]

        assert first == second

    def test_different_text_embeds_differently(self) -> None:
        adapter = DeterministicEmbeddingAdapter()

        vectors = adapter.embed(["hello", "goodbye"]).vectors

        assert vectors[0] != vectors[1]

    def test_vectors_are_unit_length_and_the_right_width(self) -> None:
        """Cosine distance is meaningless on unnormalised vectors."""

        adapter = DeterministicEmbeddingAdapter()

        vector = adapter.embed(["anything"]).vectors[0]

        assert len(vector) == 1024
        assert is_normalised(vector)
