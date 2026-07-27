"""Public KAE-Memory domain contracts."""

from .errors import (
    DomainError,
    DomainInvariantError,
    InvalidIdentifierError,
    InvalidLifecycleTransitionError,
)
from .identifiers import AgentId, ExecutionId, KnowledgeItemId, ProjectId, RelationshipId
from .lifecycle import LifecycleState
from .models import (
    Agent,
    KnowledgeItem,
    KnowledgeVersion,
    Project,
    Provenance,
    Relationship,
    RelationshipType,
)

__all__ = [
    "Agent",
    "AgentId",
    "DomainError",
    "DomainInvariantError",
    "ExecutionId",
    "InvalidIdentifierError",
    "InvalidLifecycleTransitionError",
    "KnowledgeItem",
    "KnowledgeItemId",
    "KnowledgeVersion",
    "LifecycleState",
    "Project",
    "ProjectId",
    "Provenance",
    "Relationship",
    "RelationshipId",
    "RelationshipType",
]
