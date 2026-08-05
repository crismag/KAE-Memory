"""Modules and the edges between them (N17, ADR-0025).

A module is the unit a person implements. The project answers "what is this
system"; a module answers "what do I build next, and what do I need to know to
build it without reading everything".

The vocabulary was settled first (N16) because names outlive the model that
stores them. What this adds is the model, and the rules the vocabulary declared
but could not enforce on its own:

**`depends_on` and `owns` stay acyclic.** A build order needs the first. The
second because two modules that each own the target own nothing — the point of
ownership is that exactly one part is answerable.

**`owns` is exclusive.** One target, one owner. "Never let a module own data
another module also owns" is the rule the whole distinction exists for.

**No self-edges.** A module depending on itself is not a cycle worth
diagnosing; it is a typo, and reporting it as a cycle would bury the real ones.

Cycles are refused at write time rather than detected at read time. A graph that
is only checked when traversed is a graph that stores the state it cannot
answer from, and the caller who finds out is the one who least caused it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import Identifier, ProjectId
from .relationships import ACYCLIC, EXCLUSIVE, ModuleRelation


@dataclass(frozen=True, slots=True)
class ModuleId(Identifier):
    """Stable module identifier."""


class ModuleStatus(StrEnum):
    """Where a module is in its own life, not in the work.

    Deliberately not a progress field. How far along an implementation is
    belongs to operational state (T24), which decays differently and is settled
    by different evidence. This says whether the module is part of the system
    being defined.
    """

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class Module:
    """One part of the system being defined."""

    id: ModuleId
    project_id: ProjectId
    key: str
    name: str
    summary: str = ""
    status: ModuleStatus = ModuleStatus.PROPOSED
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise DomainInvariantError("a module needs a key")
        if not self.name.strip():
            raise DomainInvariantError("a module needs a name")


@dataclass(frozen=True, slots=True)
class ModuleEdge:
    """A directed structural edge.

    ``target_module`` and ``target_knowledge`` are exclusive. `depends_on`,
    `owns`, `exposes`, and `consumes` relate a module to a module; `satisfies`
    and `verified_by` relate a module to a statement. A single nullable pair
    rather than two tables, because the traversal that needs one needs the
    other in the same walk.
    """

    source: ModuleId
    relation: ModuleRelation
    target_module: ModuleId | None = None
    target_knowledge: str | None = None

    def __post_init__(self) -> None:
        if (self.target_module is None) == (self.target_knowledge is None):
            raise DomainInvariantError(
                "an edge names exactly one target: a module or a knowledge statement"
            )
        if self.relation in KNOWLEDGE_TARGETED and self.target_module is not None:
            raise DomainInvariantError(
                f"{self.relation.value} relates a module to a statement, not to a module"
            )
        if self.relation not in KNOWLEDGE_TARGETED and self.target_knowledge is not None:
            raise DomainInvariantError(
                f"{self.relation.value} relates a module to a module, not to a statement"
            )
        if self.target_module is not None and str(self.target_module) == str(self.source):
            # Not reported as a cycle. A self-edge is a typo, and calling it a
            # cycle would bury the real ones in the same error.
            raise DomainInvariantError(f"a module cannot {self.relation.value} itself")


KNOWLEDGE_TARGETED: frozenset[ModuleRelation] = frozenset(
    {ModuleRelation.SATISFIES, ModuleRelation.VERIFIED_BY}
)
"""Relations whose target is a statement rather than a module."""


class CyclicModuleGraphError(DomainInvariantError):
    """An edge would close a cycle in a relation that must stay acyclic."""


class DuplicateOwnershipError(DomainInvariantError):
    """A target already has an owner, and ownership is exclusive."""


@dataclass(frozen=True, slots=True)
class ModuleGraph:
    """The edges of one project, and what can be asked of them.

    Constructed from stored edges rather than maintained incrementally. A
    project's module count is small — tens, not millions — and an incremental
    index would be a second representation to keep true.
    """

    edges: tuple[ModuleEdge, ...] = field(default_factory=tuple)

    def outgoing(self, module: ModuleId, relation: ModuleRelation) -> tuple[ModuleId, ...]:
        """Modules this one points at through ``relation``."""

        return tuple(
            edge.target_module
            for edge in self.edges
            if str(edge.source) == str(module)
            and edge.relation is relation
            and edge.target_module is not None
        )

    def incoming(self, module: ModuleId, relation: ModuleRelation) -> tuple[ModuleId, ...]:
        """Modules pointing at this one through ``relation``."""

        return tuple(
            edge.source
            for edge in self.edges
            if edge.target_module is not None
            and str(edge.target_module) == str(module)
            and edge.relation is relation
        )

    def knowledge(self, module: ModuleId, relation: ModuleRelation) -> tuple[str, ...]:
        """Statements this module points at through ``relation``."""

        return tuple(
            edge.target_knowledge
            for edge in self.edges
            if str(edge.source) == str(module)
            and edge.relation is relation
            and edge.target_knowledge is not None
        )

    def would_cycle(self, edge: ModuleEdge) -> bool:
        """Whether adding ``edge`` closes a cycle in an acyclic relation.

        Checked before the write. A graph validated only when traversed stores
        state it cannot answer from, and the caller who discovers that is the
        one who least caused it.
        """

        if edge.relation not in ACYCLIC or edge.target_module is None:
            return False
        # Does the target already reach the source? If so, pointing source at
        # target closes the loop.
        return self.reaches(edge.target_module, edge.source, edge.relation)

    def reaches(self, start: ModuleId, goal: ModuleId, relation: ModuleRelation) -> bool:
        """Whether ``goal`` is reachable from ``start`` following ``relation``."""

        seen: set[str] = set()
        frontier = [start]
        while frontier:
            current = frontier.pop()
            key = str(current)
            if key == str(goal):
                return True
            if key in seen:
                continue
            seen.add(key)
            frontier.extend(self.outgoing(current, relation))
        return False

    def owner_of(self, target: ModuleId) -> ModuleId | None:
        """The single module answerable for ``target``, if one is recorded."""

        owners = self.incoming(target, ModuleRelation.OWNS)
        return owners[0] if owners else None

    def build_order(self, modules: tuple[ModuleId, ...]) -> tuple[ModuleId, ...]:
        """Return modules in an order where every dependency precedes its dependent.

        Kahn's algorithm over `depends_on`. Ties are broken by identifier so the
        answer is stable: a build order that varies between calls cannot be
        compared to the previous one, which is most of what a build order is
        for.

        Raises rather than returning a partial order if a cycle exists. That
        should be unreachable — cycles are refused at write time — and a
        silently truncated order would be worse than the error, because it
        looks like an answer.
        """

        remaining = {str(module): module for module in modules}
        pending = {
            key: [
                str(dependency)
                for dependency in self.outgoing(module, ModuleRelation.DEPENDS_ON)
                if str(dependency) in remaining
            ]
            for key, module in remaining.items()
        }

        ordered: list[ModuleId] = []
        while pending:
            ready = sorted(key for key, needs in pending.items() if not needs)
            if not ready:
                raise CyclicModuleGraphError(
                    f"cannot order {sorted(pending)}: a depends_on cycle exists, which "
                    f"the write path should have refused"
                )
            for key in ready:
                ordered.append(remaining[key])
                del pending[key]
            for needs in pending.values():
                needs[:] = [need for need in needs if need not in ready]
        return tuple(ordered)


def ensure_edge_allowed(graph: ModuleGraph, edge: ModuleEdge) -> None:
    """Refuse an edge the graph's rules do not permit."""

    if graph.would_cycle(edge):
        raise CyclicModuleGraphError(
            f"{edge.source} cannot {edge.relation.value} {edge.target_module}: "
            f"the target already reaches the source, so this closes a cycle"
        )
    if edge.relation in EXCLUSIVE and edge.target_module is not None:
        existing = graph.owner_of(edge.target_module)
        if existing is not None and str(existing) != str(edge.source):
            raise DuplicateOwnershipError(
                f"{edge.target_module} is already owned by {existing}. Ownership is "
                f"exclusive: two owners means nobody is answerable."
            )
