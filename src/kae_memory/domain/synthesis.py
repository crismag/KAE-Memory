"""Evidence, synthesized model, and human attention — three layers, not one.

Extracted ``KnowledgeItem`` rows are evidence. They stay. They are not the
project model and they are not a review queue. This module is the vocabulary
for the other two layers and for the epistemic role an evidence row plays in
reasoning.

``LifecycleState`` on a knowledge item remains the *statement confirmation*
axis (proposed / validated / rejected / superseded). That axis is transitional:
Studio Reviews still Confirm/Reject extracted rows. It is not attention, and
it is not synthesized-object approval. Do not reuse it as either.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError, InvalidLifecycleTransitionError
from .identifiers import (
    AttentionItemId,
    ConstraintEffectId,
    EvidenceBindingId,
    KnowledgeItemId,
    ProjectId,
    ReconciliationEventId,
    ResponsibilityAssignmentId,
    SynthesizedObjectId,
)
from .models import KnowledgeKind


class EvidenceRole(StrEnum):
    """How an extracted row participates in reasoning.

    Item-level, and independent of ``LifecycleState``. A proposed sentence can
    be noise; a validated sentence can be historical. Missing role means
    ``active``.
    """

    ACTIVE = "active"
    SUPPORTING = "supporting"
    SUPERSEDED = "superseded"
    RESOLVED = "resolved"
    CONFLICTING = "conflicting"
    NOISE = "noise"
    HISTORICAL = "historical"
    ARCHIVED = "archived"


class EvidenceBindingKind(StrEnum):
    """How one synthesized object relates to one extracted evidence row."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    SUPERSEDED_BY = "superseded_by"
    RESOLVED_BY = "resolved_by"


class SynthesizedLifecycle(StrEnum):
    """Lifecycle of a synthesized object — not evidence confirmation.

    ``working`` is AI-maintained current understanding. ``authoritative`` is
    what a person settled. Do not treat ``KnowledgeItem.lifecycle == validated``
    as this.
    """

    WORKING = "working"
    PROPOSED_CHANGE = "proposed_change"
    AUTHORITATIVE = "authoritative"
    SUPERSEDED = "superseded"
    RESOLVED = "resolved"


class Authority(StrEnum):
    """Who may change this synthesized object without raising attention."""

    WORKING_MODEL = "working_model"
    HUMAN = "human"


class AttentionKind(StrEnum):
    """Why a human might need to care now."""

    DECISION = "decision"
    CONFLICT = "conflict"
    CORRECTION = "correction"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"
    MATERIAL_CHANGE = "material_change"


class AttentionStatus(StrEnum):
    """Whether an attention item still belongs in the queue."""

    OPEN = "open"
    DEFERRED = "deferred"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ChangeTrigger(StrEnum):
    """What caused a reconciliation/change event to be recorded."""

    EVIDENCE_WRITTEN = "evidence_written"
    HUMAN_CORRECTION = "human_correction"
    HUMAN_DECISION = "human_decision"
    RECONCILIATION = "reconciliation"
    ATTENTION_RESOLVED = "attention_resolved"


_SYNTHESIZED_TRANSITIONS: dict[SynthesizedLifecycle, frozenset[SynthesizedLifecycle]] = {
    SynthesizedLifecycle.WORKING: frozenset(
        {
            SynthesizedLifecycle.PROPOSED_CHANGE,
            SynthesizedLifecycle.AUTHORITATIVE,
            SynthesizedLifecycle.SUPERSEDED,
            SynthesizedLifecycle.RESOLVED,
        }
    ),
    SynthesizedLifecycle.PROPOSED_CHANGE: frozenset(
        {
            SynthesizedLifecycle.WORKING,
            SynthesizedLifecycle.AUTHORITATIVE,
            SynthesizedLifecycle.SUPERSEDED,
            SynthesizedLifecycle.RESOLVED,
        }
    ),
    SynthesizedLifecycle.AUTHORITATIVE: frozenset(
        {SynthesizedLifecycle.SUPERSEDED, SynthesizedLifecycle.RESOLVED}
    ),
    SynthesizedLifecycle.SUPERSEDED: frozenset(),
    SynthesizedLifecycle.RESOLVED: frozenset(),
}


_ATTENTION_TRANSITIONS: dict[AttentionStatus, frozenset[AttentionStatus]] = {
    AttentionStatus.OPEN: frozenset(
        {AttentionStatus.DEFERRED, AttentionStatus.RESOLVED, AttentionStatus.DISMISSED}
    ),
    AttentionStatus.DEFERRED: frozenset(
        {AttentionStatus.OPEN, AttentionStatus.RESOLVED, AttentionStatus.DISMISSED}
    ),
    AttentionStatus.RESOLVED: frozenset(),
    AttentionStatus.DISMISSED: frozenset(),
}


def ensure_synthesized_transition(
    current: SynthesizedLifecycle, target: SynthesizedLifecycle
) -> None:
    """Refuse an illegal synthesized-object lifecycle move."""

    if current is target:
        return
    if target not in _SYNTHESIZED_TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(
            f"cannot transition synthesized object from {current.value} to {target.value}"
        )


def ensure_attention_transition(current: AttentionStatus, target: AttentionStatus) -> None:
    """Refuse an illegal attention-item status move."""

    if current is target:
        return
    if target not in _ATTENTION_TRANSITIONS[current]:
        raise InvalidLifecycleTransitionError(
            f"cannot transition attention item from {current.value} to {target.value}"
        )


def _require_kind(domain: str) -> str:
    if domain not in set(KnowledgeKind):
        raise DomainInvariantError(
            f"unknown synthesized domain: {domain!r}. "
            f"Valid domains: {', '.join(sorted(KnowledgeKind))}"
        )
    return domain


@dataclass(frozen=True, slots=True)
class SynthesizedObject:
    """One object in the current project model, mapped to evidence rather than replacing it."""

    id: SynthesizedObjectId
    project_id: ProjectId
    domain: str
    identity_key: str
    title: str
    statement: str
    lifecycle: SynthesizedLifecycle = SynthesizedLifecycle.WORKING
    authority: Authority = Authority.WORKING_MODEL
    revision: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_kind(self.domain)
        if not self.identity_key.strip():
            raise DomainInvariantError("synthesized object identity_key must not be empty")
        if not self.title.strip():
            raise DomainInvariantError("synthesized object title must not be empty")
        if not self.statement.strip():
            raise DomainInvariantError("synthesized object statement must not be empty")
        if self.revision < 1:
            raise DomainInvariantError("synthesized object revision must be positive")
        if self.authority is Authority.HUMAN and self.lifecycle not in {
            SynthesizedLifecycle.AUTHORITATIVE,
            SynthesizedLifecycle.SUPERSEDED,
            SynthesizedLifecycle.RESOLVED,
        }:
            raise DomainInvariantError(
                "human authority requires an authoritative, superseded, or resolved lifecycle"
            )
        if (
            self.lifecycle is SynthesizedLifecycle.AUTHORITATIVE
            and self.authority is not Authority.HUMAN
        ):
            raise DomainInvariantError("an authoritative object must carry human authority")

    def with_working_update(self, title: str, statement: str) -> SynthesizedObject:
        """Return a new working revision, or refuse if a person already settled this."""

        if self.authority is Authority.HUMAN:
            raise DomainInvariantError(
                "working-model update cannot silently rewrite a human-authoritative object"
            )
        ensure_synthesized_transition(self.lifecycle, SynthesizedLifecycle.WORKING)
        return replace(
            self,
            title=title,
            statement=statement,
            lifecycle=SynthesizedLifecycle.WORKING,
            authority=Authority.WORKING_MODEL,
            revision=self.revision + 1,
        )

    def with_human_correction(self, title: str, statement: str) -> SynthesizedObject:
        """Record a person's wording as the authoritative object."""

        ensure_synthesized_transition(self.lifecycle, SynthesizedLifecycle.AUTHORITATIVE)
        return replace(
            self,
            title=title,
            statement=statement,
            lifecycle=SynthesizedLifecycle.AUTHORITATIVE,
            authority=Authority.HUMAN,
            revision=self.revision + 1,
        )


@dataclass(frozen=True, slots=True)
class EvidenceBinding:
    """Provenance from a synthesized object to an extracted knowledge item."""

    id: EvidenceBindingId
    project_id: ProjectId
    synthesized_object_id: SynthesizedObjectId
    knowledge_item_id: KnowledgeItemId
    kind: EvidenceBindingKind
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ResponsibilityAssignmentRecord:
    """One cell of doc 03's ``Role × Subject → Responsibility`` matrix, stored.

    The role is a synthesized object; the subject is a readiness area key. What
    is deliberately *not* here is the role's kind: a persona is a role holding
    no assignment anywhere, so storing the kind beside the assignments would
    store an answer this table already contains and let the two disagree.
    """

    id: ResponsibilityAssignmentId
    project_id: ProjectId
    role_object_id: SynthesizedObjectId
    subject_key: str
    letter: str
    basis: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.subject_key.strip():
            raise DomainInvariantError("responsibility assignment subject_key must not be empty")
        if not self.basis.strip():
            raise DomainInvariantError("responsibility assignment basis must not be empty")


@dataclass(frozen=True, slots=True)
class ConstraintEffectRecord:
    """One accepted constraint bearing on one open item (doc 07, `SYN-5e`).

    The constraint is a synthesized object; the item is the extracted unknown or
    assumption it narrows or answers. Only *accepted* boundaries are written
    here, so a row's existence is the acceptance — `D-126`. There is no status
    column, because doc 07 offers *Add exception* and *Change scope* beside
    *Accept*: an effect is an argument about an item, never a verdict on it.
    """

    id: ConstraintEffectId
    project_id: ProjectId
    constraint_object_id: SynthesizedObjectId
    knowledge_item_id: KnowledgeItemId
    kind: str
    basis: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise DomainInvariantError("constraint effect kind must not be empty")
        if not self.basis.strip():
            raise DomainInvariantError("constraint effect basis must not be empty")


@dataclass(frozen=True, slots=True)
class EvidenceRoleRecord:
    """Explicit epistemic role for one extracted knowledge item.

    Absence of a record means ``EvidenceRole.ACTIVE``. Writing a role never
    deletes the knowledge item.
    """

    knowledge_item_id: KnowledgeItemId
    project_id: ProjectId
    role: EvidenceRole
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """Something a human may need to care about now — not an unconfirmed row."""

    id: AttentionItemId
    project_id: ProjectId
    kind: AttentionKind
    title: str
    explanation: str
    status: AttentionStatus = AttentionStatus.OPEN
    identity_key: str | None = None
    recommendation: str | None = None
    synthesized_object_id: SynthesizedObjectId | None = None
    priority: int = 0
    actions: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise DomainInvariantError("attention item title must not be empty")
        if not self.explanation.strip():
            raise DomainInvariantError("attention item explanation must not be empty")
        if self.identity_key is not None and not self.identity_key.strip():
            raise DomainInvariantError("attention identity_key must not be blank when provided")

    def transition_to(self, target: AttentionStatus) -> AttentionItem:
        """Return a copy in a valid attention status."""

        ensure_attention_transition(self.status, target)
        return replace(self, status=target)


@dataclass(frozen=True, slots=True)
class ReconciliationEvent:
    """An idempotent record that reconciliation or a human act happened.

    Rerunning unchanged evidence with the same idempotency key returns this
    event; it does not mint a new model object or attention item.
    """

    id: ReconciliationEventId
    project_id: ProjectId
    idempotency_key: str
    trigger: ChangeTrigger
    summary: str
    payload_fingerprint: str
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise DomainInvariantError("reconciliation event idempotency_key must not be empty")
        if not self.summary.strip():
            raise DomainInvariantError("reconciliation event summary must not be empty")
        if not self.payload_fingerprint.strip():
            raise DomainInvariantError("reconciliation event payload_fingerprint must not be empty")


OPEN_ATTENTION: frozenset[AttentionStatus] = frozenset(
    {AttentionStatus.OPEN, AttentionStatus.DEFERRED}
)
"""Statuses that still occupy the human queue.

Deferred items remain on the queue so they can be resumed; they must not
re-interrupt as if they were new. Resolved and dismissed items leave it.
"""

HOT_EVIDENCE: frozenset[EvidenceRole] = frozenset(
    {
        EvidenceRole.ACTIVE,
        EvidenceRole.SUPPORTING,
        EvidenceRole.CONFLICTING,
    }
)
"""Roles a synthesizer should retrieve by default.

Noise, historical, superseded, resolved, and archived evidence stay
retrievable; they are not the hot set.
"""
