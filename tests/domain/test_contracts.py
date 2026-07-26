"""Tests for core KAE-Memory domain contracts."""

from datetime import UTC, datetime

import pytest

from kae_memory.domain import (
    AgentId,
    DomainInvariantError,
    ExecutionId,
    InvalidIdentifierError,
    InvalidLifecycleTransitionError,
    KnowledgeItem,
    KnowledgeItemId,
    KnowledgeVersion,
    LifecycleState,
    ProjectId,
    Provenance,
    Relationship,
    RelationshipId,
    RelationshipType,
)

NOW = datetime(2026, 7, 26, tzinfo=UTC)


def provenance() -> Provenance:
    return Provenance("interview", AgentId("agent-1"), ExecutionId("exec-1"), NOW)


def item() -> KnowledgeItem:
    version = KnowledgeVersion(1, "The system must preserve provenance.", provenance(), NOW)
    return KnowledgeItem(KnowledgeItemId("ki-1"), ProjectId("project-1"), "requirement", (version,))


def test_identifier_rejects_empty_value() -> None:
    with pytest.raises(InvalidIdentifierError):
        ProjectId("   ")


def test_knowledge_item_requires_contiguous_versions() -> None:
    version = KnowledgeVersion(2, "content", provenance(), NOW)
    with pytest.raises(DomainInvariantError):
        KnowledgeItem(KnowledgeItemId("ki-1"), ProjectId("p-1"), "fact", (version,))


def test_append_version_preserves_history() -> None:
    original = item()
    updated = original.append_version("Updated content", provenance(), NOW)
    assert len(original.versions) == 1
    assert len(updated.versions) == 2
    assert updated.current_version.number == 2
    assert updated.lifecycle is LifecycleState.PROPOSED


def test_valid_lifecycle_transition_returns_new_item() -> None:
    original = item()
    validated = original.transition_to(LifecycleState.VALIDATED)
    assert original.lifecycle is LifecycleState.PROPOSED
    assert validated.lifecycle is LifecycleState.VALIDATED


def test_invalid_lifecycle_transition_raises_typed_error() -> None:
    with pytest.raises(InvalidLifecycleTransitionError):
        item().transition_to(LifecycleState.SUPERSEDED)


def test_relationship_uses_stable_typed_identifiers() -> None:
    relationship = Relationship(
        RelationshipId("rel-1"),
        ProjectId("project-1"),
        KnowledgeItemId("ki-1"),
        KnowledgeItemId("ki-2"),
        RelationshipType.SUPPORTS,
    )
    assert relationship.type is RelationshipType.SUPPORTS


def test_relationship_rejects_self_reference() -> None:
    endpoint = KnowledgeItemId("ki-1")
    with pytest.raises(DomainInvariantError):
        Relationship(
            RelationshipId("rel-1"),
            ProjectId("project-1"),
            endpoint,
            endpoint,
            RelationshipType.SUPPORTS,
        )
