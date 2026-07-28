"""Stable identifier value objects for KAE-Memory domain entities."""

from dataclasses import dataclass

from .errors import InvalidIdentifierError


@dataclass(frozen=True, slots=True)
class Identifier:
    """Immutable, non-empty stable identifier."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise InvalidIdentifierError("identifier must not be empty")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ProjectId(Identifier):
    """Stable project identifier."""


@dataclass(frozen=True, slots=True)
class AgentId(Identifier):
    """Stable agent identifier."""


@dataclass(frozen=True, slots=True)
class ExecutionId(Identifier):
    """Stable execution identifier."""


@dataclass(frozen=True, slots=True)
class KnowledgeItemId(Identifier):
    """Stable knowledge-item identifier."""


@dataclass(frozen=True, slots=True)
class RelationshipId(Identifier):
    """Stable relationship identifier."""


@dataclass(frozen=True, slots=True)
class ChunkId(Identifier):
    """Stable knowledge-chunk identifier."""


@dataclass(frozen=True, slots=True)
class ProvenanceLinkId(Identifier):
    """Stable provenance-link identifier."""


@dataclass(frozen=True, slots=True)
class SessionId(Identifier):
    """Stable session identifier."""


@dataclass(frozen=True, slots=True)
class MessageId(Identifier):
    """Stable message identifier."""


@dataclass(frozen=True, slots=True)
class AgentRunId(Identifier):
    """Stable agent-run identifier.

    An ``AgentRunId`` is the value recorded as ``Provenance.execution_id``, so a
    knowledge version always resolves to the execution that produced it.
    """


@dataclass(frozen=True, slots=True)
class BlockerId(Identifier):
    """Stable blocker identifier."""


@dataclass(frozen=True, slots=True)
class AreaLinkId(Identifier):
    """Stable knowledge-to-readiness-area link identifier."""


@dataclass(frozen=True, slots=True)
class SnapshotId(Identifier):
    """Stable readiness-snapshot identifier."""
