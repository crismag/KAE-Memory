"""Persistence for the append-only knowledge review log.

There is no update and no delete. A decision that can be rewritten is not a
record of a decision, and the audit trail exists precisely for the case where
someone disputes what was agreed.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId, ReviewEventId
from kae_memory.domain.knowledge_review import (
    KnowledgeReviewEvent,
    RejectionReason,
    ReviewAction,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.workspace import ActorType

from .tables import KnowledgeReviewEventRow
from .timestamps import as_aware


class ReviewEventRepository:
    """Append and read knowledge review events."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: KnowledgeReviewEvent) -> None:
        """Append one decision.

        A duplicate ``idempotency_key`` raises through the unique index rather
        than being silently swallowed here. The caller decides whether that is a
        replay to report or a conflict to surface; this layer does not guess.
        """

        self._session.add(
            KnowledgeReviewEventRow(
                review_event_id=str(event.id),
                project_id=str(event.project_id),
                knowledge_item_id=str(event.knowledge_item_id),
                version_number=event.version_number,
                from_version_number=event.from_version_number,
                action=event.action.value,
                from_lifecycle=event.from_lifecycle.value,
                to_lifecycle=event.to_lifecycle.value,
                actor_type=event.actor_type.value,
                actor_id=event.actor_id,
                reason_code=event.reason_code.value if event.reason_code else None,
                note=event.note,
                idempotency_key=event.idempotency_key,
                created_at=event.created_at,
            )
        )

    def find_by_idempotency_key(
        self, item_id: KnowledgeItemId, key: str
    ) -> KnowledgeReviewEvent | None:
        """Return the decision a replay of ``key`` already recorded, if any."""

        row = self._session.scalars(
            select(KnowledgeReviewEventRow).where(
                KnowledgeReviewEventRow.knowledge_item_id == str(item_id),
                KnowledgeReviewEventRow.idempotency_key == key,
            )
        ).first()
        return _to_domain(row) if row is not None else None

    def history_for(self, item_id: KnowledgeItemId) -> tuple[KnowledgeReviewEvent, ...]:
        """Return one item's decisions, oldest first.

        Ordered by ``(created_at, review_event_id)`` so two events written in the
        same transaction — and therefore carrying the same timestamp — still come
        back in a stable order rather than whatever the scan happens to produce.
        """

        rows = self._session.scalars(
            select(KnowledgeReviewEventRow)
            .where(KnowledgeReviewEventRow.knowledge_item_id == str(item_id))
            .order_by(
                KnowledgeReviewEventRow.created_at,
                KnowledgeReviewEventRow.review_event_id,
            )
        ).all()
        return tuple(_to_domain(row) for row in rows)

    def history_for_project(self, project_id: ProjectId) -> tuple[KnowledgeReviewEvent, ...]:
        """Return a project's decisions, oldest first."""

        rows = self._session.scalars(
            select(KnowledgeReviewEventRow)
            .where(KnowledgeReviewEventRow.project_id == str(project_id))
            .order_by(
                KnowledgeReviewEventRow.created_at,
                KnowledgeReviewEventRow.review_event_id,
            )
        ).all()
        return tuple(_to_domain(row) for row in rows)


def _to_domain(row: KnowledgeReviewEventRow) -> KnowledgeReviewEvent:
    return KnowledgeReviewEvent(
        id=ReviewEventId(row.review_event_id),
        project_id=ProjectId(row.project_id),
        knowledge_item_id=KnowledgeItemId(row.knowledge_item_id),
        version_number=row.version_number,
        from_version_number=row.from_version_number,
        action=ReviewAction(row.action),
        from_lifecycle=LifecycleState(row.from_lifecycle),
        to_lifecycle=LifecycleState(row.to_lifecycle),
        actor_type=ActorType(row.actor_type),
        created_at=as_aware(row.created_at),
        actor_id=row.actor_id,
        reason_code=RejectionReason(row.reason_code) if row.reason_code else None,
        note=row.note,
        idempotency_key=row.idempotency_key,
    )


__all__ = ["ReviewEventRepository"]
