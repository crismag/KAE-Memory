"""Persistence- and transport-independent KAE-Memory domain contracts."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import (
    AgentId,
    ExecutionId,
    KnowledgeItemId,
    ProjectId,
    RelationshipId,
)
from .lifecycle import LifecycleState, ensure_transition


@dataclass(frozen=True, slots=True)
class Provenance:
    """Source and actor provenance required for every knowledge version."""

    source: str
    actor_id: AgentId
    execution_id: ExecutionId
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise DomainInvariantError("provenance source must not be empty")
        if self.recorded_at.tzinfo is None:
            raise DomainInvariantError("provenance timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Project:
    """Durable boundary for a software initiative."""

    id: ProjectId
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainInvariantError("project name must not be empty")


@dataclass(frozen=True, slots=True)
class Agent:
    """Registered agent identity and declared capabilities."""

    id: AgentId
    project_id: ProjectId
    role: str
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise DomainInvariantError("agent role must not be empty")


@dataclass(frozen=True, slots=True)
class KnowledgeVersion:
    """Immutable version in append-oriented knowledge history."""

    number: int
    content: str
    provenance: Provenance
    created_at: datetime

    def __post_init__(self) -> None:
        if self.number < 1:
            raise DomainInvariantError("knowledge version number must be positive")
        if not self.content.strip():
            raise DomainInvariantError("knowledge version content must not be empty")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("knowledge version timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    """Durable knowledge item with immutable append-oriented versions."""

    id: KnowledgeItemId
    project_id: ProjectId
    kind: str
    versions: tuple[KnowledgeVersion, ...]
    lifecycle: LifecycleState = LifecycleState.PROPOSED

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise DomainInvariantError("knowledge kind must not be empty")
        if not self.versions:
            raise DomainInvariantError("knowledge item requires at least one version")
        expected = tuple(range(1, len(self.versions) + 1))
        actual = tuple(version.number for version in self.versions)
        if actual != expected:
            raise DomainInvariantError("knowledge versions must be contiguous and ordered")

    @property
    def current_version(self) -> KnowledgeVersion:
        """Return the latest immutable version."""

        return self.versions[-1]

    def append_version(self, content: str, provenance: Provenance, created_at: datetime) -> "KnowledgeItem":
        """Return a new item with one additional version."""

        version = KnowledgeVersion(len(self.versions) + 1, content, provenance, created_at)
        return replace(self, versions=(*self.versions, version), lifecycle=LifecycleState.PROPOSED)

    def transition_to(self, target: LifecycleState) -> "KnowledgeItem":
        """Return a copy in a valid lifecycle state."""

        ensure_transition(self.lifecycle, target)
        return replace(self, lifecycle=target)


class RelationshipType(StrEnum):
    """Auditable relationship types between stable domain entities."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DERIVES_FROM = "derives_from"
    IMPLEMENTS = "implements"
    VALIDATES = "validates"
    SUPERSEDES = "supersedes"
    BLOCKS = "blocks"


@dataclass(frozen=True, slots=True)
class Relationship:
    """Typed edge between two stable knowledge identifiers."""

    id: RelationshipId
    project_id: ProjectId
    source_id: KnowledgeItemId
    target_id: KnowledgeItemId
    type: RelationshipType

    def __post_init__(self) -> None:
        if self.source_id == self.target_id:
            raise DomainInvariantError("relationship endpoints must be distinct")
