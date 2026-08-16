"""Persistence for synthesized objects, attention items, and change events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import (
    AttentionItemId,
    ConstraintEffectId,
    EvidenceBindingId,
    KnowledgeItemId,
    ProjectId,
    ReconciliationEventId,
    ResponsibilityAssignmentId,
    SynthesizedObjectId,
)
from kae_memory.domain.synthesis import (
    AttentionItem,
    AttentionKind,
    AttentionStatus,
    Authority,
    ChangeTrigger,
    ConstraintEffectRecord,
    EvidenceBinding,
    EvidenceBindingKind,
    EvidenceRole,
    EvidenceRoleRecord,
    ReconciliationEvent,
    ResponsibilityAssignmentRecord,
    SynthesizedLifecycle,
    SynthesizedObject,
)
from kae_memory.persistence.tables import (
    AttentionItemRow,
    ConstraintEffectRow,
    KnowledgeEvidenceRoleRow,
    ReconciliationEventRow,
    ResponsibilityAssignmentRow,
    SynthesizedEvidenceLinkRow,
    SynthesizedObjectRow,
)
from kae_memory.persistence.timestamps import as_aware


def _stamp(value: datetime | None) -> datetime:
    """Persistence requires a timestamp the domain type still allows to be unset."""

    if value is None:
        raise DomainInvariantError("a persisted synthesis record needs a timestamp")
    return value


class SynthesisRepository:
    """SQLAlchemy mapping for the three knowledge layers beyond extracted rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_object(self, object_id: SynthesizedObjectId) -> SynthesizedObject | None:
        """Return one synthesized object, or ``None``."""

        row = self._session.get(SynthesizedObjectRow, str(object_id))
        return None if row is None else _object_from_row(row)

    def get_object_by_identity(
        self, project_id: ProjectId, domain: str, identity_key: str
    ) -> SynthesizedObject | None:
        """Return the object occupying this identity, if any."""

        row = self._session.scalars(
            select(SynthesizedObjectRow).where(
                SynthesizedObjectRow.project_id == str(project_id),
                SynthesizedObjectRow.domain == domain,
                SynthesizedObjectRow.identity_key == identity_key,
            )
        ).first()
        return None if row is None else _object_from_row(row)

    def list_objects(
        self, project_id: ProjectId, domain: str | None = None
    ) -> tuple[SynthesizedObject, ...]:
        """Return synthesized objects for a project, optionally one domain."""

        stmt = select(SynthesizedObjectRow).where(
            SynthesizedObjectRow.project_id == str(project_id)
        )
        if domain is not None:
            stmt = stmt.where(SynthesizedObjectRow.domain == domain)
        stmt = stmt.order_by(SynthesizedObjectRow.domain, SynthesizedObjectRow.title)
        return tuple(_object_from_row(row) for row in self._session.scalars(stmt))

    def save_object(self, obj: SynthesizedObject) -> None:
        """Insert or update a synthesized object row."""

        row = self._session.get(SynthesizedObjectRow, str(obj.id))
        if row is None:
            self._session.add(
                SynthesizedObjectRow(
                    object_id=str(obj.id),
                    project_id=str(obj.project_id),
                    domain=obj.domain,
                    identity_key=obj.identity_key,
                    title=obj.title,
                    statement=obj.statement,
                    lifecycle=obj.lifecycle.value,
                    authority=obj.authority.value,
                    revision=obj.revision,
                    created_at=_stamp(obj.created_at),
                    updated_at=_stamp(obj.updated_at),
                )
            )
            return
        row.title = obj.title
        row.statement = obj.statement
        row.lifecycle = obj.lifecycle.value
        row.authority = obj.authority.value
        row.revision = obj.revision
        row.updated_at = _stamp(obj.updated_at)

    def get_binding(
        self, synthesized_object_id: SynthesizedObjectId, knowledge_item_id: KnowledgeItemId
    ) -> EvidenceBinding | None:
        """Return the link between this object and this evidence row, if any."""

        row = self._session.scalars(
            select(SynthesizedEvidenceLinkRow).where(
                SynthesizedEvidenceLinkRow.synthesized_object_id == str(synthesized_object_id),
                SynthesizedEvidenceLinkRow.knowledge_item_id == str(knowledge_item_id),
            )
        ).first()
        return None if row is None else _binding_from_row(row)

    def add_binding(self, binding: EvidenceBinding) -> None:
        """Persist a new evidence binding."""

        self._session.add(
            SynthesizedEvidenceLinkRow(
                link_id=str(binding.id),
                project_id=str(binding.project_id),
                synthesized_object_id=str(binding.synthesized_object_id),
                knowledge_item_id=str(binding.knowledge_item_id),
                kind=binding.kind.value,
                created_at=_stamp(binding.created_at),
            )
        )

    def list_bindings(
        self, synthesized_object_id: SynthesizedObjectId
    ) -> tuple[EvidenceBinding, ...]:
        """Return every evidence link for one synthesized object."""

        rows = self._session.scalars(
            select(SynthesizedEvidenceLinkRow)
            .where(SynthesizedEvidenceLinkRow.synthesized_object_id == str(synthesized_object_id))
            .order_by(SynthesizedEvidenceLinkRow.created_at)
        )
        return tuple(_binding_from_row(row) for row in rows)

    def get_role(self, knowledge_item_id: KnowledgeItemId) -> EvidenceRoleRecord | None:
        """Return an explicit evidence role, or ``None`` for implicit active."""

        row = self._session.get(KnowledgeEvidenceRoleRow, str(knowledge_item_id))
        return None if row is None else _role_from_row(row)

    def list_roles(self, project_id: ProjectId) -> tuple[EvidenceRoleRecord, ...]:
        """Return explicit evidence roles for a project."""

        rows = self._session.scalars(
            select(KnowledgeEvidenceRoleRow).where(
                KnowledgeEvidenceRoleRow.project_id == str(project_id)
            )
        ).all()
        return tuple(_role_from_row(row) for row in rows)

    def save_role(self, record: EvidenceRoleRecord) -> None:
        """Insert or update an evidence role without touching the knowledge item."""

        row = self._session.get(KnowledgeEvidenceRoleRow, str(record.knowledge_item_id))
        if row is None:
            self._session.add(
                KnowledgeEvidenceRoleRow(
                    knowledge_item_id=str(record.knowledge_item_id),
                    project_id=str(record.project_id),
                    role=record.role.value,
                    updated_at=_stamp(record.updated_at),
                )
            )
            return
        row.role = record.role.value
        row.updated_at = _stamp(record.updated_at)

    def get_assignment(
        self, role_object_id: SynthesizedObjectId, subject_key: str
    ) -> ResponsibilityAssignmentRecord | None:
        """Return the cell this role occupies over this subject, if any."""

        row = self._session.scalars(
            select(ResponsibilityAssignmentRow).where(
                ResponsibilityAssignmentRow.role_object_id == str(role_object_id),
                ResponsibilityAssignmentRow.subject_key == subject_key,
            )
        ).first()
        return None if row is None else _assignment_from_row(row)

    def list_assignments(
        self, project_id: ProjectId, subject_key: str | None = None
    ) -> tuple[ResponsibilityAssignmentRecord, ...]:
        """Return the project's responsibility matrix, optionally one column of it."""

        stmt = select(ResponsibilityAssignmentRow).where(
            ResponsibilityAssignmentRow.project_id == str(project_id)
        )
        if subject_key is not None:
            stmt = stmt.where(ResponsibilityAssignmentRow.subject_key == subject_key)
        stmt = stmt.order_by(
            ResponsibilityAssignmentRow.subject_key, ResponsibilityAssignmentRow.letter
        )
        return tuple(_assignment_from_row(row) for row in self._session.scalars(stmt))

    def save_assignment(self, record: ResponsibilityAssignmentRecord) -> None:
        """Insert or update one cell of the responsibility matrix."""

        row = self._session.get(ResponsibilityAssignmentRow, str(record.id))
        if row is None:
            self._session.add(
                ResponsibilityAssignmentRow(
                    assignment_id=str(record.id),
                    project_id=str(record.project_id),
                    role_object_id=str(record.role_object_id),
                    subject_key=record.subject_key,
                    letter=record.letter,
                    basis=record.basis,
                    created_at=_stamp(record.created_at),
                    updated_at=_stamp(record.updated_at),
                )
            )
            return
        row.letter = record.letter
        row.basis = record.basis
        row.updated_at = _stamp(record.updated_at)

    def get_effect(
        self, constraint_object_id: SynthesizedObjectId, knowledge_item_id: KnowledgeItemId
    ) -> ConstraintEffectRecord | None:
        """Return how this constraint already bears on this item, if at all."""

        row = self._session.scalars(
            select(ConstraintEffectRow).where(
                ConstraintEffectRow.constraint_object_id == str(constraint_object_id),
                ConstraintEffectRow.knowledge_item_id == str(knowledge_item_id),
            )
        ).first()
        return None if row is None else _effect_from_row(row)

    def list_effects(
        self, project_id: ProjectId, knowledge_item_id: KnowledgeItemId | None = None
    ) -> tuple[ConstraintEffectRecord, ...]:
        """Return the project's applied effects, optionally those on one item."""

        stmt = select(ConstraintEffectRow).where(ConstraintEffectRow.project_id == str(project_id))
        if knowledge_item_id is not None:
            stmt = stmt.where(ConstraintEffectRow.knowledge_item_id == str(knowledge_item_id))
        stmt = stmt.order_by(ConstraintEffectRow.knowledge_item_id, ConstraintEffectRow.kind)
        return tuple(_effect_from_row(row) for row in self._session.scalars(stmt))

    def save_effect(self, record: ConstraintEffectRecord) -> None:
        """Insert or update one constraint-to-item effect."""

        row = self._session.get(ConstraintEffectRow, str(record.id))
        if row is None:
            self._session.add(
                ConstraintEffectRow(
                    effect_id=str(record.id),
                    project_id=str(record.project_id),
                    constraint_object_id=str(record.constraint_object_id),
                    knowledge_item_id=str(record.knowledge_item_id),
                    kind=record.kind,
                    basis=record.basis,
                    created_at=_stamp(record.created_at),
                    updated_at=_stamp(record.updated_at),
                )
            )
            return
        row.kind = record.kind
        row.basis = record.basis
        row.updated_at = _stamp(record.updated_at)

    def get_attention(self, item_id: AttentionItemId) -> AttentionItem | None:
        """Return one attention item, or ``None``."""

        row = self._session.get(AttentionItemRow, str(item_id))
        return None if row is None else _attention_from_row(row)

    def get_attention_by_identity(
        self, project_id: ProjectId, identity_key: str
    ) -> AttentionItem | None:
        """Return the attention item occupying this identity, if any."""

        row = self._session.scalars(
            select(AttentionItemRow).where(
                AttentionItemRow.project_id == str(project_id),
                AttentionItemRow.identity_key == identity_key,
            )
        ).first()
        return None if row is None else _attention_from_row(row)

    def list_attention(
        self, project_id: ProjectId, statuses: tuple[AttentionStatus, ...] | None = None
    ) -> tuple[AttentionItem, ...]:
        """Return attention items for a project, newest-material first."""

        stmt = select(AttentionItemRow).where(AttentionItemRow.project_id == str(project_id))
        if statuses is not None:
            stmt = stmt.where(AttentionItemRow.status.in_([status.value for status in statuses]))
        stmt = stmt.order_by(AttentionItemRow.priority.desc(), AttentionItemRow.created_at)
        return tuple(_attention_from_row(row) for row in self._session.scalars(stmt))

    def save_attention(self, item: AttentionItem) -> None:
        """Insert or update an attention item."""

        row = self._session.get(AttentionItemRow, str(item.id))
        if row is None:
            self._session.add(
                AttentionItemRow(
                    item_id=str(item.id),
                    project_id=str(item.project_id),
                    kind=item.kind.value,
                    title=item.title,
                    explanation=item.explanation,
                    status=item.status.value,
                    identity_key=item.identity_key,
                    recommendation=item.recommendation,
                    synthesized_object_id=(
                        None
                        if item.synthesized_object_id is None
                        else str(item.synthesized_object_id)
                    ),
                    priority=item.priority,
                    actions=list(item.actions),
                    created_at=_stamp(item.created_at),
                    updated_at=_stamp(item.updated_at),
                )
            )
            return
        row.title = item.title
        row.explanation = item.explanation
        row.status = item.status.value
        row.recommendation = item.recommendation
        row.priority = item.priority
        row.actions = list(item.actions)
        row.updated_at = _stamp(item.updated_at)

    def get_event_by_key(
        self, project_id: ProjectId, idempotency_key: str
    ) -> ReconciliationEvent | None:
        """Return the event already recorded under this key, if any."""

        row = self._session.scalars(
            select(ReconciliationEventRow).where(
                ReconciliationEventRow.project_id == str(project_id),
                ReconciliationEventRow.idempotency_key == idempotency_key,
            )
        ).first()
        return None if row is None else _event_from_row(row)

    def add_event(self, event: ReconciliationEvent) -> None:
        """Persist a new reconciliation event."""

        self._session.add(
            ReconciliationEventRow(
                event_id=str(event.id),
                project_id=str(event.project_id),
                idempotency_key=event.idempotency_key,
                trigger=event.trigger.value,
                summary=event.summary,
                payload_fingerprint=event.payload_fingerprint,
                created_at=_stamp(event.created_at),
            )
        )

    def list_events(self, project_id: ProjectId) -> tuple[ReconciliationEvent, ...]:
        """Return change events for a project, oldest first."""

        rows = self._session.scalars(
            select(ReconciliationEventRow)
            .where(ReconciliationEventRow.project_id == str(project_id))
            .order_by(ReconciliationEventRow.created_at)
        )
        return tuple(_event_from_row(row) for row in rows)


def _object_from_row(row: SynthesizedObjectRow) -> SynthesizedObject:
    return SynthesizedObject(
        id=SynthesizedObjectId(row.object_id),
        project_id=ProjectId(row.project_id),
        domain=row.domain,
        identity_key=row.identity_key,
        title=row.title,
        statement=row.statement,
        lifecycle=SynthesizedLifecycle(row.lifecycle),
        authority=Authority(row.authority),
        revision=int(row.revision),
        created_at=as_aware(row.created_at),
        updated_at=as_aware(row.updated_at),
    )


def _binding_from_row(row: SynthesizedEvidenceLinkRow) -> EvidenceBinding:
    return EvidenceBinding(
        id=EvidenceBindingId(row.link_id),
        project_id=ProjectId(row.project_id),
        synthesized_object_id=SynthesizedObjectId(row.synthesized_object_id),
        knowledge_item_id=KnowledgeItemId(row.knowledge_item_id),
        kind=EvidenceBindingKind(row.kind),
        created_at=as_aware(row.created_at),
    )


def _role_from_row(row: KnowledgeEvidenceRoleRow) -> EvidenceRoleRecord:
    return EvidenceRoleRecord(
        knowledge_item_id=KnowledgeItemId(row.knowledge_item_id),
        project_id=ProjectId(row.project_id),
        role=EvidenceRole(row.role),
        updated_at=as_aware(row.updated_at),
    )


def _assignment_from_row(row: ResponsibilityAssignmentRow) -> ResponsibilityAssignmentRecord:
    return ResponsibilityAssignmentRecord(
        id=ResponsibilityAssignmentId(row.assignment_id),
        project_id=ProjectId(row.project_id),
        role_object_id=SynthesizedObjectId(row.role_object_id),
        subject_key=row.subject_key,
        letter=row.letter,
        basis=row.basis,
        created_at=as_aware(row.created_at),
        updated_at=as_aware(row.updated_at),
    )


def _effect_from_row(row: ConstraintEffectRow) -> ConstraintEffectRecord:
    return ConstraintEffectRecord(
        id=ConstraintEffectId(row.effect_id),
        project_id=ProjectId(row.project_id),
        constraint_object_id=SynthesizedObjectId(row.constraint_object_id),
        knowledge_item_id=KnowledgeItemId(row.knowledge_item_id),
        kind=row.kind,
        basis=row.basis,
        created_at=as_aware(row.created_at),
        updated_at=as_aware(row.updated_at),
    )


def _attention_from_row(row: AttentionItemRow) -> AttentionItem:
    object_id = row.synthesized_object_id
    return AttentionItem(
        id=AttentionItemId(row.item_id),
        project_id=ProjectId(row.project_id),
        kind=AttentionKind(row.kind),
        title=row.title,
        explanation=row.explanation,
        status=AttentionStatus(row.status),
        identity_key=row.identity_key,
        recommendation=row.recommendation,
        synthesized_object_id=None if object_id is None else SynthesizedObjectId(object_id),
        priority=int(row.priority),
        actions=tuple(row.actions or ()),
        created_at=as_aware(row.created_at),
        updated_at=as_aware(row.updated_at),
    )


def _event_from_row(row: ReconciliationEventRow) -> ReconciliationEvent:
    return ReconciliationEvent(
        id=ReconciliationEventId(row.event_id),
        project_id=ProjectId(row.project_id),
        idempotency_key=row.idempotency_key,
        trigger=ChangeTrigger(row.trigger),
        summary=row.summary,
        payload_fingerprint=row.payload_fingerprint,
        created_at=as_aware(row.created_at),
    )
