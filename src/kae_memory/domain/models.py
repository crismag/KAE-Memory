"""Persistence- and transport-independent KAE-Memory domain contracts."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import (
    AgentId,
    AgentRunId,
    ExecutionId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    ProvenanceLinkId,
    RelationshipId,
)
from .lifecycle import LifecycleState, ensure_transition
from .workspace import ProjectStatus


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
    """Durable boundary for a software initiative.

    A project owns every session, run, and knowledge item derived within it. There
    are no cross-project reads.
    """

    id: ProjectId
    name: str
    key: str | None = None
    description: str | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainInvariantError("project name must not be empty")
        if self.key is not None and not self.key.strip():
            raise DomainInvariantError("project key must not be blank when provided")


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


class KnowledgeKind(StrEnum):
    """The authoritative vocabulary for what a knowledge item is.

    One vocabulary, used by extraction, persistence, and the interface alike.
    Because the column is a plain string, adding a value here needs no migration.
    """

    ACTOR = "actor"
    GOAL = "goal"
    RULE = "rule"
    CONSTRAINT = "constraint"
    REQUIREMENT = "requirement"
    DECISION = "decision"
    UNKNOWN = "unknown"
    ASSUMPTION = "assumption"


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
        if self.kind not in set(KnowledgeKind):
            raise DomainInvariantError(
                f"unknown knowledge kind: {self.kind!r}. "
                f"Valid kinds: {', '.join(sorted(KnowledgeKind))}"
            )
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

    def append_version(
        self, content: str, provenance: Provenance, created_at: datetime
    ) -> "KnowledgeItem":
        """Return a new item with one additional version."""

        version = KnowledgeVersion(len(self.versions) + 1, content, provenance, created_at)
        return replace(self, versions=(*self.versions, version), lifecycle=LifecycleState.PROPOSED)

    def transition_to(self, target: LifecycleState) -> "KnowledgeItem":
        """Return a copy in a valid lifecycle state."""

        ensure_transition(self.lifecycle, target)
        return replace(self, lifecycle=target)


class RelationshipType(StrEnum):
    """Auditable relationship types between stable domain entities.

    This enum is the single authoritative relationship vocabulary. ADR-0005 listed
    an alternative set while specifying the physical schema; the column is a plain
    string, so values can be added here later without a migration.
    """

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


class ProvenanceLinkType(StrEnum):
    """How a knowledge item relates to a run or a message."""

    PRODUCED_BY = "produced_by"
    USED_BY = "used_by"
    DERIVED_FROM_MESSAGE = "derived_from_message"


@dataclass(frozen=True, slots=True)
class ProvenanceLink:
    """Relational link from knowledge to the run or message it came from.

    ``Provenance`` on a version records who wrote it. These links additionally make
    "which run *used* this knowledge" and "which message produced it" answerable
    without parsing opaque values.
    """

    id: ProvenanceLinkId
    project_id: ProjectId
    knowledge_item_id: KnowledgeItemId
    link_type: ProvenanceLinkType
    created_at: datetime
    knowledge_version_number: int | None = None
    agent_run_id: AgentRunId | None = None
    message_id: MessageId | None = None
    source_type: str | None = None
    source_reference: str | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("provenance link created_at must be timezone-aware")
        if self.knowledge_version_number is not None and self.knowledge_version_number < 1:
            raise DomainInvariantError("provenance link version number must be positive")
        if self.link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE and self.message_id is None:
            raise DomainInvariantError("a message-derived link must reference a message")
        if (
            self.link_type in {ProvenanceLinkType.PRODUCED_BY, ProvenanceLinkType.USED_BY}
            and self.agent_run_id is None
        ):
            raise DomainInvariantError(f"a {self.link_type.value} link must reference an agent run")
