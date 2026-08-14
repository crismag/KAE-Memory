"""Repositories for relationships, area links, blockers, and readiness snapshots.

Everything readiness gates on is queryable relationally. Per-area detail is
``JSONB`` because its shape is open-ended, but no gating decision reads it
(ADR-0012).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import (
    AgentRunId,
    AreaLinkId,
    BlockerId,
    KnowledgeItemId,
    ProjectId,
    RelationshipId,
    SnapshotId,
)
from kae_memory.domain.models import KnowledgeKind, Relationship, RelationshipType
from kae_memory.domain.readiness import (
    AreaDefinition,
    AreaResult,
    AreaState,
    Blocker,
    BlockerSeverity,
    BlockerStatus,
    Claim,
    KnowledgeAreaLink,
    ReadinessSnapshot,
    ReadinessStatus,
    ReadinessTemplate,
)

from .tables import (
    DiscoveryBlockerRow,
    KnowledgeAreaLinkRow,
    KnowledgeRelationshipRow,
    ProjectRow,
    ReadinessSnapshotRow,
    ReadinessTemplateRow,
)
from .timestamps import as_aware


class RelationshipRepository:
    """Persistence boundary for typed edges between knowledge items.

    M5 created the table and deferred the domain wiring to M9. Without this,
    ``blocked`` is unreachable and the contradiction gate is decorative.
    """

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(
        self,
        relationship: Relationship,
        moment: datetime,
        created_by_agent_run_id: AgentRunId | None = None,
    ) -> None:
        """Record a relationship between two knowledge items."""

        self._session.add(
            KnowledgeRelationshipRow(
                relationship_id=str(relationship.id),
                project_id=str(relationship.project_id),
                source_knowledge_item_id=str(relationship.source_id),
                target_knowledge_item_id=str(relationship.target_id),
                relationship_type=relationship.type.value,
                created_by_agent_run_id=(
                    None if created_by_agent_run_id is None else str(created_by_agent_run_id)
                ),
                relationship_metadata={},
                created_at=moment,
            )
        )

    def get(self, relationship_id: RelationshipId) -> Relationship | None:
        """Return a relationship by identifier."""

        row = self._session.get(KnowledgeRelationshipRow, str(relationship_id))
        return None if row is None else _relationship_to_domain(row)

    def resolve(
        self, relationship_id: RelationshipId, moment: datetime, note: str | None = None
    ) -> bool:
        """Mark a relationship resolved. Returns whether it was still open.

        Resolution does not delete the edge: a contradiction that was raised and
        settled is part of the audit trail, and losing it would make the
        readiness history unexplainable.
        """

        statement = (
            update(KnowledgeRelationshipRow)
            .where(
                KnowledgeRelationshipRow.relationship_id == str(relationship_id),
                KnowledgeRelationshipRow.resolved_at.is_(None),
            )
            .values(resolved_at=moment, resolution_note=note)
        )
        return bool(cast("Any", self._session.execute(statement)).rowcount)

    def list_for_project(
        self,
        project_id: ProjectId,
        relationship_type: RelationshipType | None = None,
        unresolved_only: bool = False,
    ) -> tuple[Relationship, ...]:
        """Return a project's relationships."""

        statement = select(KnowledgeRelationshipRow).where(
            KnowledgeRelationshipRow.project_id == str(project_id)
        )
        if relationship_type is not None:
            statement = statement.where(
                KnowledgeRelationshipRow.relationship_type == relationship_type.value
            )
        if unresolved_only:
            statement = statement.where(KnowledgeRelationshipRow.resolved_at.is_(None))
        rows = self._session.scalars(statement.order_by(KnowledgeRelationshipRow.created_at)).all()
        return tuple(_relationship_to_domain(row) for row in rows)

    def get_between(
        self,
        source_id: KnowledgeItemId,
        target_id: KnowledgeItemId,
        relationship_type: RelationshipType,
    ) -> Relationship | None:
        """Return the typed edge between two items, if it already exists."""

        row = self._session.scalars(
            select(KnowledgeRelationshipRow).where(
                KnowledgeRelationshipRow.source_knowledge_item_id == str(source_id),
                KnowledgeRelationshipRow.target_knowledge_item_id == str(target_id),
                KnowledgeRelationshipRow.relationship_type == relationship_type.value,
            )
        ).first()
        return None if row is None else _relationship_to_domain(row)

    def unresolved_contradiction_items(self, project_id: ProjectId) -> frozenset[str]:
        """Return the knowledge items on either end of an open contradiction."""

        rows = self.list_for_project(project_id, RelationshipType.CONTRADICTS, unresolved_only=True)
        return frozenset(
            str(endpoint)
            for relationship in rows
            for endpoint in (relationship.source_id, relationship.target_id)
        )


class KnowledgeAreaLinkRepository:
    """Persistence boundary for knowledge-to-area assignments."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, link: KnowledgeAreaLink) -> None:
        """Assign a knowledge item to a readiness area."""

        self._session.add(
            KnowledgeAreaLinkRow(
                area_link_id=str(link.id),
                project_id=str(link.project_id),
                knowledge_item_id=str(link.knowledge_item_id),
                area_key=link.area_key,
                claim_key=link.claim_key,
                assigned_by_agent_run_id=(
                    None
                    if link.assigned_by_agent_run_id is None
                    else str(link.assigned_by_agent_run_id)
                ),
                created_at=link.created_at,
            )
        )

    def list_for_project(self, project_id: ProjectId) -> tuple[KnowledgeAreaLink, ...]:
        """Return every area assignment in a project."""

        rows = self._session.scalars(
            select(KnowledgeAreaLinkRow)
            .where(KnowledgeAreaLinkRow.project_id == str(project_id))
            .order_by(KnowledgeAreaLinkRow.created_at)
        ).all()
        return tuple(
            KnowledgeAreaLink(
                id=AreaLinkId(row.area_link_id),
                project_id=ProjectId(row.project_id),
                knowledge_item_id=KnowledgeItemId(row.knowledge_item_id),
                area_key=row.area_key,
                claim_key=row.claim_key,
                created_at=as_aware(row.created_at),
                assigned_by_agent_run_id=(
                    None
                    if row.assigned_by_agent_run_id is None
                    else AgentRunId(row.assigned_by_agent_run_id)
                ),
            )
            for row in rows
        )


class BlockerRepository:
    """Persistence boundary for discovery blockers."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, blocker: Blocker) -> None:
        """Record a blocker."""

        self._session.add(
            DiscoveryBlockerRow(
                blocker_id=str(blocker.id),
                project_id=str(blocker.project_id),
                area_key=blocker.area_key,
                summary=blocker.summary,
                severity=blocker.severity.value,
                status=blocker.status.value,
                owner=blocker.owner,
                resolution_note=blocker.resolution_note,
                created_at=blocker.created_at,
                resolved_at=blocker.resolved_at,
            )
        )

    def get(self, blocker_id: BlockerId) -> Blocker | None:
        """Return a blocker by identifier."""

        row = self._session.get(DiscoveryBlockerRow, str(blocker_id))
        return None if row is None else _blocker_to_domain(row)

    def save(self, blocker: Blocker) -> None:
        """Persist a blocker's resolution."""

        row = self._session.get(DiscoveryBlockerRow, str(blocker.id))
        if row is None:
            raise LookupError(f"unknown blocker: {blocker.id}")
        row.status = blocker.status.value
        row.resolved_at = blocker.resolved_at
        row.resolution_note = blocker.resolution_note

    def list_for_project(
        self, project_id: ProjectId, status: BlockerStatus | None = None
    ) -> tuple[Blocker, ...]:
        """Return a project's blockers, optionally filtered by status."""

        statement = select(DiscoveryBlockerRow).where(
            DiscoveryBlockerRow.project_id == str(project_id)
        )
        if status is not None:
            statement = statement.where(DiscoveryBlockerRow.status == status.value)
        rows = self._session.scalars(statement.order_by(DiscoveryBlockerRow.created_at)).all()
        return tuple(_blocker_to_domain(row) for row in rows)


class ReadinessTemplateRepository:
    """Persistence boundary for versioned readiness templates."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def upsert(self, template: ReadinessTemplate, moment: datetime) -> None:
        """Store a template version. **A stored version is immutable.**

        This exists so the shipped template can be installed idempotently at
        startup, not so definitions can be edited in place. Changing a template
        means publishing a new version.

        **That was the intent and nothing enforced it.** The method rewrote
        `definition` for an existing `(key, version)`, so editing
        `SOFTWARE_TEMPLATE` without bumping the version silently rewrote the
        stored v1 — and every snapshot labelled `template_version: 1` became a
        claim about semantics that no longer existed. Readiness history is only
        interpretable if a version means one thing forever.

        Re-installing the same definition is still a no-op, which is what makes
        startup idempotent. Re-installing a *different* one under the same
        version raises, because there is no correct silent answer: overwriting
        falsifies history and ignoring it leaves the deployment running
        semantics it did not install.
        """

        row = self._session.get(ReadinessTemplateRow, (template.key, template.version))
        definition = _template_to_json(template)
        if row is None:
            self._session.add(
                ReadinessTemplateRow(
                    template_key=template.key,
                    version=template.version,
                    definition=definition,
                    is_active=True,
                    created_at=moment,
                )
            )
        elif row.definition != definition:
            raise DomainInvariantError(
                f"template {template.key!r} version {template.version} is already "
                f"stored with a different definition. A stored version is immutable — "
                f"publish a new version rather than editing this one, or every "
                f"snapshot recorded against it becomes a claim about semantics that "
                f"no longer exist."
            )

    def get(self, key: str, version: int) -> ReadinessTemplate | None:
        """Return one template version."""

        row = self._session.get(ReadinessTemplateRow, (key, version))
        return None if row is None else _template_from_json(row.definition)

    def latest_active(self, key: str) -> ReadinessTemplate | None:
        """Return the highest active version of a template."""

        row = self._session.scalars(
            select(ReadinessTemplateRow)
            .where(
                ReadinessTemplateRow.template_key == key,
                ReadinessTemplateRow.is_active.is_(True),
            )
            .order_by(ReadinessTemplateRow.version.desc())
            .limit(1)
        ).one_or_none()
        return None if row is None else _template_from_json(row.definition)


class ReadinessSnapshotRepository:
    """Append-only persistence boundary for readiness calculations."""

    def __init__(self, session: DbSession) -> None:
        self._session = session

    def add(self, snapshot: ReadinessSnapshot) -> None:
        """Append a snapshot."""

        mandatory = [area for area in snapshot.areas if area.mandatory]
        self._session.add(
            ReadinessSnapshotRow(
                snapshot_id=str(snapshot.id),
                project_id=str(snapshot.project_id),
                template_key=snapshot.template_key,
                template_version=snapshot.template_version,
                calculation_version=snapshot.calculation_version,
                knowledge_revision=snapshot.knowledge_revision,
                score=snapshot.score,
                status=snapshot.status.value,
                draft_eligible=snapshot.draft_eligible,
                implementation_eligible=snapshot.implementation_eligible,
                mandatory_area_count=len(mandatory),
                mandatory_area_sufficient_count=sum(
                    1 for area in mandatory if area.state is AreaState.SUFFICIENT
                ),
                open_blocker_count=snapshot.open_blocker_count,
                critical_blocker_count=snapshot.critical_blocker_count,
                unresolved_contradiction_count=snapshot.unresolved_contradiction_count,
                area_results={"areas": [_area_to_json(area) for area in snapshot.areas]},
                calculated_at=snapshot.calculated_at,
            )
        )

    def latest(self, project_id: ProjectId) -> ReadinessSnapshot | None:
        """Return a project's most recent snapshot."""

        row = self._session.scalars(
            select(ReadinessSnapshotRow)
            .where(ReadinessSnapshotRow.project_id == str(project_id))
            .order_by(ReadinessSnapshotRow.calculated_at.desc())
            .limit(1)
        ).first()
        return None if row is None else _snapshot_to_domain(row)

    def history(self, project_id: ProjectId, limit: int = 50) -> tuple[ReadinessSnapshot, ...]:
        """Return a project's snapshots, oldest first.

        History is how readiness is shown *moving* as knowledge is confirmed.
        """

        rows = self._session.scalars(
            select(ReadinessSnapshotRow)
            .where(ReadinessSnapshotRow.project_id == str(project_id))
            .order_by(ReadinessSnapshotRow.calculated_at)
            .limit(limit)
        ).all()
        return tuple(_snapshot_to_domain(row) for row in rows)


def bump_knowledge_revision(session: DbSession, project_id: ProjectId) -> int:
    """Increment a project's authoritative knowledge revision and return it.

    Incremented in the same transaction as the change that caused it, so a
    snapshot can never claim to reflect a revision that was never committed.
    """

    revision = session.execute(
        update(ProjectRow)
        .where(ProjectRow.project_id == str(project_id))
        .values(knowledge_revision=ProjectRow.knowledge_revision + 1)
        .returning(ProjectRow.knowledge_revision)
    ).scalar_one()
    return int(revision)


def current_knowledge_revision(session: DbSession, project_id: ProjectId) -> int:
    """Return a project's current authoritative knowledge revision."""

    revision = session.execute(
        select(ProjectRow.knowledge_revision).where(ProjectRow.project_id == str(project_id))
    ).scalar_one_or_none()
    return 0 if revision is None else int(revision)


def count_open_blockers(session: DbSession, project_id: ProjectId) -> tuple[int, int]:
    """Return ``(open, critical_open)`` blocker counts for a project."""

    rows = session.execute(
        select(DiscoveryBlockerRow.severity, func.count())
        .where(
            DiscoveryBlockerRow.project_id == str(project_id),
            DiscoveryBlockerRow.status == BlockerStatus.OPEN.value,
        )
        .group_by(DiscoveryBlockerRow.severity)
    ).all()
    total = sum(int(count) for _, count in rows)
    critical = sum(
        int(count) for severity, count in rows if severity == BlockerSeverity.CRITICAL.value
    )
    return total, critical


def _relationship_to_domain(row: KnowledgeRelationshipRow) -> Relationship:
    return Relationship(
        id=RelationshipId(row.relationship_id),
        project_id=ProjectId(row.project_id),
        source_id=KnowledgeItemId(row.source_knowledge_item_id),
        target_id=KnowledgeItemId(row.target_knowledge_item_id),
        type=RelationshipType(row.relationship_type),
    )


def _blocker_to_domain(row: DiscoveryBlockerRow) -> Blocker:
    return Blocker(
        id=BlockerId(row.blocker_id),
        project_id=ProjectId(row.project_id),
        summary=row.summary,
        severity=BlockerSeverity(row.severity),
        created_at=as_aware(row.created_at),
        area_key=row.area_key,
        owner=row.owner,
        status=BlockerStatus(row.status),
        resolved_at=as_aware(row.resolved_at) if row.resolved_at else None,
        resolution_note=row.resolution_note,
    )


def _area_to_json(area: AreaResult) -> dict[str, Any]:
    return {
        "key": area.key,
        "name": area.name,
        "weight": area.weight,
        "mandatory": area.mandatory,
        "state": area.state.value,
        "confirmed_count": area.confirmed_count,
        "proposed_count": area.proposed_count,
        "minimum_confirmed": area.minimum_confirmed,
        "contradicted": area.contradicted,
    }


def _area_from_json(payload: dict[str, Any]) -> AreaResult:
    return AreaResult(
        key=payload["key"],
        name=payload["name"],
        weight=float(payload["weight"]),
        mandatory=bool(payload["mandatory"]),
        state=AreaState(payload["state"]),
        confirmed_count=int(payload["confirmed_count"]),
        proposed_count=int(payload["proposed_count"]),
        minimum_confirmed=int(payload["minimum_confirmed"]),
        contradicted=bool(payload["contradicted"]),
    )


def _snapshot_to_domain(row: ReadinessSnapshotRow) -> ReadinessSnapshot:
    areas: Sequence[dict[str, Any]] = row.area_results.get("areas", [])
    return ReadinessSnapshot(
        id=SnapshotId(row.snapshot_id),
        project_id=ProjectId(row.project_id),
        template_key=row.template_key,
        template_version=row.template_version,
        calculation_version=row.calculation_version,
        knowledge_revision=row.knowledge_revision,
        score=float(row.score),
        status=ReadinessStatus(row.status),
        draft_eligible=row.draft_eligible,
        implementation_eligible=row.implementation_eligible,
        areas=tuple(_area_from_json(area) for area in areas),
        open_blocker_count=row.open_blocker_count,
        critical_blocker_count=row.critical_blocker_count,
        unresolved_contradiction_count=row.unresolved_contradiction_count,
        calculated_at=as_aware(row.calculated_at),
    )


def _template_to_json(template: ReadinessTemplate) -> dict[str, Any]:
    return {
        "key": template.key,
        "version": template.version,
        "areas": [
            {
                "key": area.key,
                "name": area.name,
                "weight": area.weight,
                "kinds": [kind.value for kind in area.kinds],
                "minimum_confirmed": area.minimum_confirmed,
                "mandatory": area.mandatory,
                # Omitted entirely when empty, so a stored v1 stays byte-identical
                # to what it was — a version whose serialisation changes is a
                # version, and the whole point of pinning is that it does not.
                **(
                    {
                        "claims": [
                            {
                                "key": claim.key,
                                "name": claim.name,
                                "minimum_confirmed": claim.minimum_confirmed,
                            }
                            for claim in area.claims
                        ]
                    }
                    if area.claims
                    else {}
                ),
            }
            for area in template.areas
        ],
    }


def _template_from_json(payload: dict[str, Any]) -> ReadinessTemplate:
    return ReadinessTemplate(
        key=payload["key"],
        version=int(payload["version"]),
        areas=tuple(
            AreaDefinition(
                key=area["key"],
                name=area["name"],
                weight=float(area["weight"]),
                kinds=tuple(KnowledgeKind(kind) for kind in area["kinds"]),
                minimum_confirmed=int(area["minimum_confirmed"]),
                mandatory=bool(area["mandatory"]),
                claims=tuple(
                    Claim(
                        key=claim["key"],
                        name=claim["name"],
                        minimum_confirmed=int(claim.get("minimum_confirmed", 1)),
                    )
                    for claim in area.get("claims", ())
                ),
            )
            for area in payload["areas"]
        ),
    )
