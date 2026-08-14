"""Deterministic evidence-graph reconciliation (Phase 2).

Classifies support, conflict, and stale-unknown resolution, then writes
``KnowledgeRelation`` edges and ``EvidenceRole`` values. Does not mint
synthesized objects, raise attention, or change ``LifecycleState``.

Rerunning unchanged evidence with the same idempotency key returns the same
change event and writes nothing further.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.synthesis_service import payload_fingerprint
from kae_memory.domain.chunks import EmbeddingState
from kae_memory.domain.errors import IdempotencyConflictError, KnowledgeNotFoundError
from kae_memory.domain.identifiers import (
    KnowledgeItemId,
    ProjectId,
    ReconciliationEventId,
    RelationshipId,
)
from kae_memory.domain.lifecycle import RETRIEVABLE
from kae_memory.domain.models import Relationship
from kae_memory.domain.reconciliation import (
    NEIGHBORHOOD_LIMIT,
    AffectedSection,
    EvidenceSnapshot,
    IntendedGraph,
    Neighbor,
    Neighborhood,
    NeighborhoodMeasure,
    lexical_neighborhood,
    plan_reconciliation,
    semantic_neighborhood,
    snapshot_from_item,
)
from kae_memory.domain.synthesis import (
    ChangeTrigger,
    EvidenceRole,
    EvidenceRoleRecord,
    ReconciliationEvent,
)
from kae_memory.persistence.chunk_repository import ChunkRepository
from kae_memory.persistence.readiness_repositories import (
    RelationshipRepository,
    bump_knowledge_revision,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.synthesis_repository import SynthesisRepository
from kae_memory.persistence.transactions import run_transaction


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def evidence_digest(snapshots: Sequence[EvidenceSnapshot]) -> str:
    """Stable digest of retrievable evidence identity, kind, lifecycle, and text."""

    material = "\n".join(
        f"{item.id}\t{item.kind}\t{item.lifecycle.value}\t{item.content}"
        for item in sorted(snapshots, key=lambda item: str(item.id))
    )
    return hashlib.sha256(material.encode()).hexdigest()


def graph_summary(graph: IntendedGraph, digest: str) -> str:
    """Human-readable payload for the change event, including the evidence digest."""

    supports = sum(1 for edge in graph.edges if edge.type.value == "supports")
    resolved = sum(1 for edge in graph.edges if edge.type.value == "supersedes")
    contradicts = sum(1 for edge in graph.edges if edge.type.value == "contradicts")
    return f"supports={supports} resolved={resolved} contradicts={contradicts} digest={digest[:16]}"


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """What one reconciliation pass concluded, including a replay."""

    project_id: ProjectId
    replayed: bool
    event: ReconciliationEvent
    graph: IntendedGraph
    edges_written: int
    roles_written: int
    affected: tuple[AffectedSection, ...]
    resolved_item_ids: tuple[KnowledgeItemId, ...]


class ReconciliationService:
    """Run the deterministic half of the reconciliation cycle."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    def reconcile(
        self,
        project_id: ProjectId,
        *,
        idempotency_key: str | None = None,
        item_ids: Sequence[KnowledgeItemId] | None = None,
    ) -> ReconciliationReport:
        """Classify retrievable evidence and persist the resulting graph.

        Does not create synthesized objects or attention items. Does not retire
        extracted rows via ``LifecycleState``.
        """

        def operation(session: DbSession) -> ReconciliationReport:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            stored = knowledge.list_for_project(project_id, None)
            retrievable = tuple(item for item in stored if item.lifecycle in RETRIEVABLE)
            snapshots = tuple(snapshot_from_item(item) for item in retrievable)
            focus = _resolve_focus(item_ids, snapshots)
            graph = plan_reconciliation(snapshots, focus)
            digest = evidence_digest(snapshots)
            key = (idempotency_key or f"reconciliation:{digest[:16]}").strip()
            summary = graph_summary(graph, digest)
            fingerprint = payload_fingerprint(ChangeTrigger.RECONCILIATION, summary)

            synthesis = SynthesisRepository(session)
            existing = synthesis.get_event_by_key(project_id, key)
            if existing is not None:
                if existing.payload_fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        f"reconciliation key {key!r} was recorded as "
                        f"{existing.trigger.value}: {existing.summary!r}"
                    )
                return ReconciliationReport(
                    project_id=project_id,
                    replayed=True,
                    event=existing,
                    graph=graph,
                    edges_written=0,
                    roles_written=0,
                    affected=graph.affected,
                    resolved_item_ids=graph.resolved_item_ids,
                )

            relationships = RelationshipRepository(session)
            now = _now()
            edges_written = _persist_edges(relationships, project_id, graph, now)
            roles_written = _persist_roles(synthesis, project_id, graph, now)
            if edges_written or roles_written:
                bump_knowledge_revision(session, project_id)
            event = ReconciliationEvent(
                id=ReconciliationEventId(_new_id()),
                project_id=project_id,
                idempotency_key=key,
                trigger=ChangeTrigger.RECONCILIATION,
                summary=summary,
                payload_fingerprint=fingerprint,
                created_at=now,
            )
            synthesis.add_event(event)
            return ReconciliationReport(
                project_id=project_id,
                replayed=False,
                event=event,
                graph=graph,
                edges_written=edges_written,
                roles_written=roles_written,
                affected=graph.affected,
                resolved_item_ids=graph.resolved_item_ids,
            )

        return run_transaction(self._session_factory, operation)

    def neighborhood(
        self,
        project_id: ProjectId,
        item_id: KnowledgeItemId,
        *,
        limit: int = NEIGHBORHOOD_LIMIT,
    ) -> Neighborhood:
        """Same-kind neighbours, by vectors where they exist, and say which.

        **Semantic first, lexical as the honest fallback.** The corpus stores a
        1024-dimension vector per chunk, so the nearest same-kind statements are
        a query away — no model call, because the numbers are already here. A
        deployment that never embedded gets stem coverage instead and is told so
        (`NeighborhoodMeasure`), because *nothing is near this* and *nothing
        here can compare it* are different facts with different remedies.

        `PHASE-2-RECONCILIATION.md` is the reason this exists: stem coverage
        cannot see `plan` against `plann`, and that was recorded as Phase 3
        work rather than a threshold to lower.
        """

        def operation(session: DbSession) -> Neighborhood:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            focus_item = knowledge.get(item_id)
            if focus_item is None or focus_item.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown knowledge item: {item_id}")
            retrievable = tuple(
                item
                for item in knowledge.list_for_project(project_id, None)
                if item.lifecycle in RETRIEVABLE
            )
            snapshots = tuple(snapshot_from_item(item) for item in retrievable)
            focus = snapshot_from_item(focus_item)
            related = _graph_neighbors(session, project_id, item_id)

            # **Which measure ran is decided before the result, not after it.**
            # Choosing by "did it return anything" collapses the two states this
            # field exists to separate: an indexed item with nothing near it
            # would report itself unindexed, and a caller would go looking for a
            # missing embedding that is present.
            if _is_indexed(session, item_id):
                found = semantic_neighborhood(
                    ChunkRepository(session).semantic_neighbors(
                        project_id, item_id, kind=focus.kind, limit=limit
                    ),
                    limit=limit,
                )
                measure = NeighborhoodMeasure.SEMANTIC
            else:
                found = lexical_neighborhood(focus, snapshots, limit=limit)
                # Nothing found *and* no vector to try is the state a caller
                # must not read as "unrelated".
                measure = NeighborhoodMeasure.LEXICAL if found else NeighborhoodMeasure.NONE
            return Neighborhood(measure=measure, neighbors=_merge_neighbors(found, related, limit))

        return run_transaction(self._session_factory, operation)


def _resolve_focus(
    item_ids: Sequence[KnowledgeItemId] | None, snapshots: Sequence[EvidenceSnapshot]
) -> frozenset[KnowledgeItemId] | None:
    if item_ids is None:
        return None
    wanted = tuple(item_ids)
    if not wanted:
        return None
    known = {item.id for item in snapshots}
    missing = [item_id for item_id in wanted if item_id not in known]
    if missing:
        raise KnowledgeNotFoundError(f"unknown knowledge item: {missing[0]}")
    return frozenset(wanted)


def _persist_edges(
    relationships: RelationshipRepository,
    project_id: ProjectId,
    graph: IntendedGraph,
    moment: datetime,
) -> int:
    written = 0
    for edge in graph.edges:
        if relationships.get_between(edge.source_id, edge.target_id, edge.type) is not None:
            continue
        relationships.add(
            Relationship(
                id=RelationshipId(_new_id()),
                project_id=project_id,
                source_id=edge.source_id,
                target_id=edge.target_id,
                type=edge.type,
            ),
            moment,
        )
        written += 1
    return written


def _persist_roles(
    synthesis: SynthesisRepository,
    project_id: ProjectId,
    graph: IntendedGraph,
    moment: datetime,
) -> int:
    current = {record.knowledge_item_id: record.role for record in synthesis.list_roles(project_id)}
    written = 0
    for item_id, role in graph.roles:
        if current.get(item_id) is role:
            continue
        if current.get(item_id) is EvidenceRole.NOISE:
            continue
        synthesis.save_role(
            EvidenceRoleRecord(
                knowledge_item_id=item_id,
                project_id=project_id,
                role=role,
                updated_at=moment,
            )
        )
        written += 1
    return written


def _is_indexed(session: DbSession, item_id: KnowledgeItemId) -> bool:
    """Whether this item has a vector at all.

    Separates *nothing is near it* from *nothing here can compare it*. The two
    look identical in an empty result and mean opposite things: one is a fact
    about the project, the other about the deployment.
    """

    chunks = ChunkRepository(session).list_for_knowledge(item_id)
    return any(chunk.state is EmbeddingState.EMBEDDED for chunk in chunks)


def _graph_neighbors(
    session: DbSession, project_id: ProjectId, item_id: KnowledgeItemId
) -> dict[KnowledgeItemId, str]:
    related: dict[KnowledgeItemId, str] = {}
    for relationship in RelationshipRepository(session).list_for_project(project_id):
        if relationship.source_id == item_id:
            related[relationship.target_id] = relationship.type.value
        elif relationship.target_id == item_id:
            related[relationship.source_id] = relationship.type.value
    return related


def _merge_neighbors(
    lexical: Sequence[Neighbor], related: dict[KnowledgeItemId, str], limit: int
) -> tuple[Neighbor, ...]:
    merged: dict[KnowledgeItemId, Neighbor] = {
        neighbor.item_id: Neighbor(
            item_id=neighbor.item_id,
            score=neighbor.score,
            relation=related.get(neighbor.item_id),
        )
        for neighbor in lexical
    }
    for item_id, relation in related.items():
        if item_id not in merged:
            merged[item_id] = Neighbor(item_id=item_id, score=0.0, relation=relation)
    ordered = sorted(merged.values(), key=lambda neighbor: (-neighbor.score, str(neighbor.item_id)))
    return tuple(ordered[:limit])
