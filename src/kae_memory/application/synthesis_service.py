"""The synthesized project model and the human-attention queue (ADR-0007).

Extracted ``KnowledgeItem`` rows stay where they are. This service writes the
other two layers: synthesized objects (the current model) and attention items
(what a person may need to care about). It also records idempotent change
events so a later reconcilation pass can retry without minting twins.

## What this is not

**Not a synthesizer.** Nothing here clusters goals or closes stale unknowns.
Phase 2's ``ReconciliationService`` writes evidence-graph edges and roles, then
Phase 3 will call these methods to mint a compact model. Phase 1 exists so
those calls have a place to land that is not ``confirm_knowledge``.

**Not a replacement for extracted knowledge.** Binding evidence maps a model
object onto existing rows. It never deletes them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.errors import (
    AuthoritativeOverrideError,
    DomainInvariantError,
    IdempotencyConflictError,
    KnowledgeNotFoundError,
)
from kae_memory.domain.identifiers import (
    AttentionItemId,
    EvidenceBindingId,
    KnowledgeItemId,
    ProjectId,
    ReconciliationEventId,
    ResponsibilityAssignmentId,
    SynthesizedObjectId,
)
from kae_memory.domain.synthesis import (
    OPEN_ATTENTION,
    AttentionItem,
    AttentionKind,
    AttentionStatus,
    Authority,
    ChangeTrigger,
    EvidenceBinding,
    EvidenceBindingKind,
    EvidenceRole,
    EvidenceRoleRecord,
    ReconciliationEvent,
    ResponsibilityAssignmentRecord,
    SynthesizedLifecycle,
    SynthesizedObject,
)
from kae_memory.persistence.readiness_repositories import bump_knowledge_revision
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.synthesis_repository import SynthesisRepository
from kae_memory.persistence.transactions import run_transaction


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def payload_fingerprint(trigger: ChangeTrigger, summary: str) -> str:
    """Stable digest of a change-event payload.

    The idempotency key says *which* act; this says *what* the act claimed.
    Same key and same fingerprint is a replay. Same key and a different
    fingerprint is a conflict.
    """

    material = f"{trigger.value}\n{summary.strip()}"
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SynthesizedObjectView:
    """A synthesized object plus the evidence it is mapped to."""

    object: SynthesizedObject
    evidence: tuple[EvidenceBinding, ...]


class SynthesisService:
    """Persist and retrieve the synthesized model and attention queue."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    def put_object(
        self,
        project_id: ProjectId,
        domain: str,
        identity_key: str,
        title: str,
        statement: str,
    ) -> SynthesizedObject:
        """Create or update a working-model object, idempotent by identity.

        A replay with the same title and statement returns the existing object
        without bumping revision. A changed working object is updated. A
        human-authoritative object is refused — new evidence must raise
        attention, not overwrite what a person settled.
        """

        title = title.strip()
        statement = statement.strip()
        identity_key = identity_key.strip()

        def operation(session: DbSession) -> SynthesizedObject:
            repo = SynthesisRepository(session)
            existing = repo.get_object_by_identity(project_id, domain, identity_key)
            now = _now()
            if existing is None:
                created = SynthesizedObject(
                    id=SynthesizedObjectId(_new_id()),
                    project_id=project_id,
                    domain=domain,
                    identity_key=identity_key,
                    title=title,
                    statement=statement,
                    lifecycle=SynthesizedLifecycle.WORKING,
                    authority=Authority.WORKING_MODEL,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
                repo.save_object(created)
                bump_knowledge_revision(session, project_id)
                return created
            if existing.title == title and existing.statement == statement:
                return existing
            if existing.authority is Authority.HUMAN:
                raise AuthoritativeOverrideError(
                    f"synthesized object {existing.id} is human-authoritative; "
                    "working-model synthesis cannot overwrite it"
                )
            updated = replace(existing.with_working_update(title, statement), updated_at=now)
            repo.save_object(updated)
            bump_knowledge_revision(session, project_id)
            return updated

        return run_transaction(self._session_factory, operation)

    def correct_object(
        self, project_id: ProjectId, object_id: SynthesizedObjectId, title: str, statement: str
    ) -> SynthesizedObject:
        """Record a person's wording as the authoritative synthesized object.

        Evidence bindings are left in place. The extracted rows that supported
        the previous wording remain retrievable.
        """

        title = title.strip()
        statement = statement.strip()

        def operation(session: DbSession) -> SynthesizedObject:
            repo = SynthesisRepository(session)
            existing = repo.get_object(object_id)
            if existing is None or existing.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown synthesized object: {object_id}")
            now = _now()
            if (
                existing.title == title
                and existing.statement == statement
                and existing.authority is Authority.HUMAN
            ):
                return existing
            corrected = replace(existing.with_human_correction(title, statement), updated_at=now)
            repo.save_object(corrected)
            bump_knowledge_revision(session, project_id)
            return corrected

        return run_transaction(self._session_factory, operation)

    def get_object(
        self, project_id: ProjectId, object_id: SynthesizedObjectId
    ) -> SynthesizedObjectView | None:
        """Return one synthesized object with its evidence bindings."""

        def operation(session: DbSession) -> SynthesizedObjectView | None:
            repo = SynthesisRepository(session)
            obj = repo.get_object(object_id)
            if obj is None or obj.project_id != project_id:
                return None
            return SynthesizedObjectView(obj, repo.list_bindings(object_id))

        return run_transaction(self._session_factory, operation)

    def list_objects(
        self, project_id: ProjectId, domain: str | None = None
    ) -> tuple[SynthesizedObject, ...]:
        """Return the synthesized model, which may be empty."""

        def operation(session: DbSession) -> tuple[SynthesizedObject, ...]:
            return SynthesisRepository(session).list_objects(project_id, domain)

        return run_transaction(self._session_factory, operation)

    def list_bindings(
        self, project_id: ProjectId, object_id: SynthesizedObjectId
    ) -> tuple[EvidenceBinding, ...]:
        """The evidence behind one synthesized object.

        The other half of `ADR-0007`'s storage separation, and the reason the
        separation is worth having: a model a reader cannot trace back to what
        produced it is a summary, and this estate has been careful not to ship
        one. Writing bindings without a way to read them would have left the
        provenance unprovable.
        """

        def operation(session: DbSession) -> tuple[EvidenceBinding, ...]:
            repo = SynthesisRepository(session)
            obj = repo.get_object(object_id)
            if obj is None or obj.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown synthesized object: {object_id}")
            return repo.list_bindings(object_id)

        return run_transaction(self._session_factory, operation)

    def bind_evidence(
        self,
        project_id: ProjectId,
        object_id: SynthesizedObjectId,
        knowledge_item_id: KnowledgeItemId,
        kind: EvidenceBindingKind,
    ) -> EvidenceBinding:
        """Map a synthesized object onto an extracted row. The row is not deleted.

        Rebinding the same pair returns the existing link. A different kind on
        the same pair is a conflict: the two cannot both be the relation.
        """

        def operation(session: DbSession) -> EvidenceBinding:
            repo = SynthesisRepository(session)
            obj = repo.get_object(object_id)
            if obj is None or obj.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown synthesized object: {object_id}")
            item = SqlAlchemyKnowledgeRepository(session).get(knowledge_item_id)
            if item is None or item.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown knowledge item: {knowledge_item_id}")
            existing = repo.get_binding(object_id, knowledge_item_id)
            if existing is not None:
                if existing.kind is kind:
                    return existing
                raise IdempotencyConflictError(
                    f"evidence {knowledge_item_id} is already bound to {object_id} "
                    f"as {existing.kind.value}"
                )
            binding = EvidenceBinding(
                id=EvidenceBindingId(_new_id()),
                project_id=project_id,
                synthesized_object_id=object_id,
                knowledge_item_id=knowledge_item_id,
                kind=kind,
                created_at=_now(),
            )
            repo.add_binding(binding)
            bump_knowledge_revision(session, project_id)
            return binding

        return run_transaction(self._session_factory, operation)

    def set_evidence_role(
        self, project_id: ProjectId, knowledge_item_id: KnowledgeItemId, role: EvidenceRole
    ) -> EvidenceRoleRecord:
        """Set how an extracted row participates in reasoning.

        Does not change ``LifecycleState`` and does not delete the item.
        Absence of a role remains ``active``.
        """

        def operation(session: DbSession) -> EvidenceRoleRecord:
            item = SqlAlchemyKnowledgeRepository(session).get(knowledge_item_id)
            if item is None or item.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown knowledge item: {knowledge_item_id}")
            record = EvidenceRoleRecord(
                knowledge_item_id=knowledge_item_id,
                project_id=project_id,
                role=role,
                updated_at=_now(),
            )
            SynthesisRepository(session).save_role(record)
            bump_knowledge_revision(session, project_id)
            return record

        return run_transaction(self._session_factory, operation)

    def evidence_role(self, knowledge_item_id: KnowledgeItemId) -> EvidenceRole:
        """Return the explicit role, or ``active`` when none has been written."""

        def operation(session: DbSession) -> EvidenceRole:
            record = SynthesisRepository(session).get_role(knowledge_item_id)
            return EvidenceRole.ACTIVE if record is None else record.role

        return run_transaction(self._session_factory, operation)

    def assign_responsibility(
        self,
        project_id: ProjectId,
        role_object_id: SynthesizedObjectId,
        subject_key: str,
        letter: str,
        basis: str,
    ) -> ResponsibilityAssignmentRecord:
        """Record that a role holds a responsibility over a subject.

        Idempotent by ``(role, subject)``: a rerun over unchanged evidence reads
        the same letter and returns the stored cell. A changed letter updates it,
        because a role holds one responsibility over one subject — two would be
        the matrix contradicting itself rather than saying more.
        """

        subject_key = subject_key.strip()
        basis = basis.strip()

        def operation(session: DbSession) -> ResponsibilityAssignmentRecord:
            repo = SynthesisRepository(session)
            role = repo.get_object(role_object_id)
            if role is None or role.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown synthesized object: {role_object_id}")
            now = _now()
            existing = repo.get_assignment(role_object_id, subject_key)
            if existing is not None:
                if existing.letter == letter and existing.basis == basis:
                    return existing
                updated = replace(existing, letter=letter, basis=basis, updated_at=now)
                repo.save_assignment(updated)
                bump_knowledge_revision(session, project_id)
                return updated
            record = ResponsibilityAssignmentRecord(
                id=ResponsibilityAssignmentId(_new_id()),
                project_id=project_id,
                role_object_id=role_object_id,
                subject_key=subject_key,
                letter=letter,
                basis=basis,
                created_at=now,
                updated_at=now,
            )
            repo.save_assignment(record)
            bump_knowledge_revision(session, project_id)
            return record

        return run_transaction(self._session_factory, operation)

    def list_assignments(
        self, project_id: ProjectId, subject_key: str | None = None
    ) -> tuple[ResponsibilityAssignmentRecord, ...]:
        """The project's responsibility matrix, which may legitimately be empty.

        Empty means no evidence named both a role and a subject, which doc 03
        calls a legitimate finding rather than a gap to fill with guesses.
        """

        def operation(session: DbSession) -> tuple[ResponsibilityAssignmentRecord, ...]:
            return SynthesisRepository(session).list_assignments(project_id, subject_key)

        return run_transaction(self._session_factory, operation)

    def put_attention(
        self,
        project_id: ProjectId,
        kind: AttentionKind,
        title: str,
        explanation: str,
        *,
        identity_key: str | None = None,
        recommendation: str | None = None,
        synthesized_object_id: SynthesizedObjectId | None = None,
        priority: int = 0,
        actions: tuple[str, ...] = (),
    ) -> AttentionItem:
        """Create an attention item, or return the one already occupying this identity.

        Extraction does not call this. A later attention engine does. Identical
        identity is a replay; a different title/explanation on the same key
        updates the open item rather than minting a second interrupt.
        """

        title = title.strip()
        explanation = explanation.strip()
        key = None if identity_key is None else identity_key.strip()

        def operation(session: DbSession) -> AttentionItem:
            repo = SynthesisRepository(session)
            if synthesized_object_id is not None:
                obj = repo.get_object(synthesized_object_id)
                if obj is None or obj.project_id != project_id:
                    raise KnowledgeNotFoundError(
                        f"unknown synthesized object: {synthesized_object_id}"
                    )
            now = _now()
            if key:
                existing = repo.get_attention_by_identity(project_id, key)
                if existing is not None:
                    if (
                        existing.title == title
                        and existing.explanation == explanation
                        and existing.kind is kind
                    ):
                        return existing
                    updated = replace(
                        existing,
                        title=title,
                        explanation=explanation,
                        kind=kind,
                        recommendation=recommendation,
                        priority=priority,
                        actions=actions,
                        updated_at=now,
                    )
                    repo.save_attention(updated)
                    bump_knowledge_revision(session, project_id)
                    return updated
            item = AttentionItem(
                id=AttentionItemId(_new_id()),
                project_id=project_id,
                kind=kind,
                title=title,
                explanation=explanation,
                status=AttentionStatus.OPEN,
                identity_key=key,
                recommendation=recommendation,
                synthesized_object_id=synthesized_object_id,
                priority=priority,
                actions=actions,
                created_at=now,
                updated_at=now,
            )
            repo.save_attention(item)
            bump_knowledge_revision(session, project_id)
            return item

        return run_transaction(self._session_factory, operation)

    def list_attention(
        self, project_id: ProjectId, *, open_only: bool = True
    ) -> tuple[AttentionItem, ...]:
        """Return attention items. Default is the live queue, not history."""

        def operation(session: DbSession) -> tuple[AttentionItem, ...]:
            statuses = tuple(OPEN_ATTENTION) if open_only else None
            return SynthesisRepository(session).list_attention(project_id, statuses)

        return run_transaction(self._session_factory, operation)

    def resolve_attention(
        self,
        project_id: ProjectId,
        item_id: AttentionItemId,
        status: AttentionStatus = AttentionStatus.RESOLVED,
    ) -> AttentionItem:
        """Move an attention item off the live queue, with provenance via status."""

        if status not in {AttentionStatus.RESOLVED, AttentionStatus.DISMISSED}:
            raise DomainInvariantError(
                "resolve_attention closes the queue; use put_attention to defer"
            )

        def operation(session: DbSession) -> AttentionItem:
            repo = SynthesisRepository(session)
            existing = repo.get_attention(item_id)
            if existing is None or existing.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown attention item: {item_id}")
            if existing.status is status:
                return existing
            resolved = replace(existing.transition_to(status), updated_at=_now())
            repo.save_attention(resolved)
            bump_knowledge_revision(session, project_id)
            return resolved

        return run_transaction(self._session_factory, operation)

    def record_change(
        self,
        project_id: ProjectId,
        idempotency_key: str,
        trigger: ChangeTrigger,
        summary: str,
    ) -> ReconciliationEvent:
        """Record a change event, or return the one already stored under this key.

        Rerunning unchanged evidence with the same key must not create a second
        event, a second model object, or a second attention item. This method
        is the event half of that guarantee.
        """

        key = idempotency_key.strip()
        summary = summary.strip()
        fingerprint = payload_fingerprint(trigger, summary)

        def operation(session: DbSession) -> ReconciliationEvent:
            repo = SynthesisRepository(session)
            existing = repo.get_event_by_key(project_id, key)
            if existing is not None:
                if existing.payload_fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        f"reconciliation key {key!r} was recorded as "
                        f"{existing.trigger.value}: {existing.summary!r}"
                    )
                return existing
            event = ReconciliationEvent(
                id=ReconciliationEventId(_new_id()),
                project_id=project_id,
                idempotency_key=key,
                trigger=trigger,
                summary=summary,
                payload_fingerprint=fingerprint,
                created_at=_now(),
            )
            repo.add_event(event)
            return event

        return run_transaction(self._session_factory, operation)

    def list_changes(self, project_id: ProjectId) -> tuple[ReconciliationEvent, ...]:
        """Return recorded change events, oldest first."""

        def operation(session: DbSession) -> tuple[ReconciliationEvent, ...]:
            return SynthesisRepository(session).list_events(project_id)

        return run_transaction(self._session_factory, operation)
