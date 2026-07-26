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
