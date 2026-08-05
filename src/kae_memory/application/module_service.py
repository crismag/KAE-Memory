"""Modules, their edges, and what the graph can answer (N17, N18).

The write path the platform never had. `record_contradiction` was the only
thing that created an edge, which is why the dependency graph, the build order,
and module-scoped context were all blocked behind one missing capability rather
than five.

Rules are enforced **here and at write time**, not at read time. A graph
checked only when traversed stores state it cannot answer from, and the caller
who discovers that is the one who least caused it. The database carries what
DDL can express — one target, no self-edges, no duplicate edge — and cycles and
exclusive ownership are refused in this layer because no constraint can see the
whole graph.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.modules import (
    KNOWLEDGE_TARGETED,
    Module,
    ModuleEdge,
    ModuleGraph,
    ModuleId,
    ModuleStatus,
    ensure_edge_allowed,
)
from kae_memory.domain.relationships import ModuleRelation
from kae_memory.persistence.tables import ModuleRelationshipRow, ModuleRow
from kae_memory.persistence.transactions import run_transaction


class ModuleNotFoundError(LookupError):
    """No module with that key or id exists in this project."""


@dataclass(frozen=True, slots=True)
class ModuleNeighbourhood:
    """What one module touches, in both directions (N18).

    Dependencies and dependents are both here because they answer opposite
    questions a reader needs together: what must exist before I build this, and
    what breaks if I change it.
    """

    module: Module
    depends_on: tuple[Module, ...] = ()
    dependents: tuple[Module, ...] = ()
    exposes: tuple[Module, ...] = ()
    consumes: tuple[Module, ...] = ()
    owns: tuple[Module, ...] = ()
    owned_by: Module | None = None
    satisfies: tuple[str, ...] = ()
    verified_by: tuple[str, ...] = ()


class ModuleService:
    """Create modules, relate them, and traverse the result."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    # -- writes ------------------------------------------------------------

    def define(self, project_id: ProjectId, key: str, name: str, summary: str = "") -> Module:
        """Create a module, or return the one that already has this key.

        Idempotent by key, like project creation and for the same reason: an
        agent that loses its response can retry without first checking whether
        it succeeded.
        """

        def operation(session: DbSession) -> Module:
            existing = session.scalars(
                select(ModuleRow).where(
                    ModuleRow.project_id == str(project_id), ModuleRow.key == key.strip()
                )
            ).first()
            if existing is not None:
                return _as_module(existing)

            row = ModuleRow(
                module_id=str(uuid4()),
                project_id=str(project_id),
                key=key.strip(),
                name=name.strip(),
                summary=summary.strip(),
                status=ModuleStatus.PROPOSED.value,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return _as_module(row)

        return run_transaction(self._session_factory, operation)

    def relate(
        self,
        project_id: ProjectId,
        source_key: str,
        relation: ModuleRelation,
        target_key: str | None = None,
        knowledge_id: str | None = None,
    ) -> ModuleEdge:
        """Record one structural edge, refusing what the graph does not permit.

        The cycle check reads the whole project's edges first. That is a full
        read per write, and it is the right trade at this scale: a project has
        tens of modules, and the alternative is storing a graph that cannot
        answer the question it exists for.
        """

        def operation(session: DbSession) -> ModuleEdge:
            source = _require_module(session, project_id, source_key)
            target_module: ModuleId | None = None
            if relation not in KNOWLEDGE_TARGETED:
                if not target_key:
                    raise DomainInvariantError(f"{relation.value} needs a target module")
                target_module = _require_module(session, project_id, target_key).id

            edge = ModuleEdge(
                source=source.id,
                relation=relation,
                target_module=target_module,
                target_knowledge=knowledge_id.strip() if knowledge_id else None,
            )
            ensure_edge_allowed(_graph(session, project_id), edge)

            session.add(
                ModuleRelationshipRow(
                    module_relationship_id=str(uuid4()),
                    project_id=str(project_id),
                    source_module_id=str(edge.source),
                    relation=edge.relation.value,
                    target_module_id=str(edge.target_module) if edge.target_module else None,
                    target_knowledge_id=edge.target_knowledge,
                    created_at=datetime.now(UTC),
                )
            )
            return edge

        return run_transaction(self._session_factory, operation)

    def confirm(self, project_id: ProjectId, key: str) -> Module:
        """Record that a person accepted this module as part of the system."""

        def operation(session: DbSession) -> Module:
            row = _require_row(session, project_id, key)
            row.status = ModuleStatus.CONFIRMED.value
            session.flush()
            return _as_module(row)

        return run_transaction(self._session_factory, operation)

    # -- reads -------------------------------------------------------------

    def list_modules(self, project_id: ProjectId) -> tuple[Module, ...]:
        def operation(session: DbSession) -> tuple[Module, ...]:
            rows = session.scalars(
                select(ModuleRow)
                .where(ModuleRow.project_id == str(project_id))
                .order_by(ModuleRow.key)
            ).all()
            return tuple(_as_module(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def get(self, project_id: ProjectId, key: str) -> Module:
        def operation(session: DbSession) -> Module:
            return _as_module(_require_row(session, project_id, key))

        return run_transaction(self._session_factory, operation)

    def graph(self, project_id: ProjectId) -> ModuleGraph:
        def operation(session: DbSession) -> ModuleGraph:
            return _graph(session, project_id)

        return run_transaction(self._session_factory, operation)

    def neighbourhood(self, project_id: ProjectId, key: str) -> ModuleNeighbourhood:
        """What one module touches, in both directions (N18)."""

        def operation(session: DbSession) -> ModuleNeighbourhood:
            module = _as_module(_require_row(session, project_id, key))
            graph = _graph(session, project_id)
            by_id = {
                str(row.module_id): _as_module(row)
                for row in session.scalars(
                    select(ModuleRow).where(ModuleRow.project_id == str(project_id))
                ).all()
            }

            def named(ids: Sequence[ModuleId]) -> tuple[Module, ...]:
                return tuple(by_id[str(i)] for i in ids if str(i) in by_id)

            owner = graph.owner_of(module.id)
            return ModuleNeighbourhood(
                module=module,
                depends_on=named(graph.outgoing(module.id, ModuleRelation.DEPENDS_ON)),
                dependents=named(graph.incoming(module.id, ModuleRelation.DEPENDS_ON)),
                exposes=named(graph.outgoing(module.id, ModuleRelation.EXPOSES)),
                consumes=named(graph.outgoing(module.id, ModuleRelation.CONSUMES)),
                owns=named(graph.outgoing(module.id, ModuleRelation.OWNS)),
                owned_by=by_id.get(str(owner)) if owner else None,
                satisfies=graph.knowledge(module.id, ModuleRelation.SATISFIES),
                verified_by=graph.knowledge(module.id, ModuleRelation.VERIFIED_BY),
            )

        return run_transaction(self._session_factory, operation)

    def build_order(self, project_id: ProjectId) -> tuple[Module, ...]:
        """Return every module in an order where dependencies come first (N18)."""

        def operation(session: DbSession) -> tuple[Module, ...]:
            rows = session.scalars(
                select(ModuleRow).where(ModuleRow.project_id == str(project_id))
            ).all()
            by_id = {str(row.module_id): _as_module(row) for row in rows}
            ordered = _graph(session, project_id).build_order(
                tuple(module.id for module in by_id.values())
            )
            return tuple(by_id[str(module_id)] for module_id in ordered)

        return run_transaction(self._session_factory, operation)


def _graph(session: DbSession, project_id: ProjectId) -> ModuleGraph:
    rows = session.scalars(
        select(ModuleRelationshipRow).where(ModuleRelationshipRow.project_id == str(project_id))
    ).all()
    return ModuleGraph(
        edges=tuple(
            ModuleEdge(
                source=ModuleId(str(row.source_module_id)),
                relation=ModuleRelation(row.relation),
                target_module=(
                    ModuleId(str(row.target_module_id)) if row.target_module_id else None
                ),
                target_knowledge=row.target_knowledge_id,
            )
            for row in rows
        )
    )


def _require_row(session: DbSession, project_id: ProjectId, key: str) -> ModuleRow:
    row = session.scalars(
        select(ModuleRow).where(
            ModuleRow.project_id == str(project_id), ModuleRow.key == key.strip()
        )
    ).first()
    if row is None:
        raise ModuleNotFoundError(f"no module {key!r} in this project")
    return row


def _require_module(session: DbSession, project_id: ProjectId, key: str) -> Module:
    return _as_module(_require_row(session, project_id, key))


def _as_module(row: ModuleRow) -> Module:
    return Module(
        id=ModuleId(str(row.module_id)),
        project_id=ProjectId(str(row.project_id)),
        key=row.key,
        name=row.name,
        summary=row.summary or "",
        status=ModuleStatus(row.status),
        created_at=row.created_at,
    )
