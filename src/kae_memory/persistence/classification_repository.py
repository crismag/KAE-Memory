"""Persistence for observation classifications and operational updates (T24).

Classifications are append-only. A classifier upgrade writes a new result set
and marks the previous one superseded; it never edits a prior row, because a
reviewer's decision was made against what they saw.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from kae_memory.domain.identifiers import MessageId, ProjectId
from kae_memory.domain.observation import ClassifiedSpan, RetentionTier

from .tables import ObservationClassificationRow, OperationalUpdateRow


class ClassificationRepository:
    """Read and append classification records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_span(
        self,
        project_id: ProjectId,
        message_id: MessageId,
        span: ClassifiedSpan,
        classifier_name: str,
        classifier_version: str,
        semantic: bool,
    ) -> ObservationClassificationRow:
        """Append one classified span.

        A duplicate raises through the unique index rather than being swallowed
        here. Whether that is a replay to report or a conflict to surface is
        the caller's decision; this layer does not guess.
        """

        row = ObservationClassificationRow(
            classification_id=str(uuid4()),
            project_id=str(project_id),
            message_id=str(message_id),
            classifier_name=classifier_name,
            classifier_version=classifier_version,
            semantic=semantic,
            classification=span.classification.value,
            retention_tier=span.tier.value,
            route=span.route.value,
            confidence=span.confidence,
            review_required=span.review_required,
            span_start=span.span.start,
            span_end=span.span.end,
            normalized_text=span.normalized_text,
            extracted_fields=dict(span.fields),
            rationale=span.rationale or None,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        return row

    def for_message(
        self, message_id: MessageId, classifier_version: str | None = None
    ) -> tuple[ObservationClassificationRow, ...]:
        """Return the classifications of one observation, in span order."""

        statement = select(ObservationClassificationRow).where(
            ObservationClassificationRow.message_id == str(message_id)
        )
        if classifier_version is not None:
            statement = statement.where(
                ObservationClassificationRow.classifier_version == classifier_version
            )
        rows = self._session.scalars(
            statement.order_by(ObservationClassificationRow.span_start)
        ).all()
        return tuple(rows)

    def for_project(
        self, project_id: ProjectId, tiers: Sequence[RetentionTier] | None = None
    ) -> tuple[ObservationClassificationRow, ...]:
        """Return a project's classifications, optionally filtered by tier."""

        statement = select(ObservationClassificationRow).where(
            ObservationClassificationRow.project_id == str(project_id),
            ObservationClassificationRow.superseded_by.is_(None),
        )
        if tiers:
            statement = statement.where(
                ObservationClassificationRow.retention_tier.in_([tier.value for tier in tiers])
            )
        rows = self._session.scalars(
            statement.order_by(ObservationClassificationRow.created_at.desc())
        ).all()
        return tuple(rows)

    def supersede_older_versions(
        self, message_id: MessageId, classifier_name: str, current_version: str, replacement: str
    ) -> int:
        """Mark earlier versions of one observation's classifications superseded.

        The rows survive. A version upgrade must preserve what a reviewer saw,
        so the previous result set is marked rather than deleted, and a history
        view can still show which classifier produced which decision.
        """

        result: Any = self._session.execute(
            update(ObservationClassificationRow)
            .where(
                ObservationClassificationRow.message_id == str(message_id),
                ObservationClassificationRow.classifier_name == classifier_name,
                ObservationClassificationRow.classifier_version != current_version,
                ObservationClassificationRow.superseded_by.is_(None),
            )
            .values(superseded_by=replacement)
        )
        return int(result.rowcount or 0)


class OperationalUpdateRepository:
    """Read and append operational records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        project_id: ProjectId,
        message_id: MessageId,
        kind: str,
        authority: str,
        state: str,
        idempotency_key: str,
        classification_id: str | None = None,
        subject: str | None = None,
        reported_status: str | None = None,
        current_status: str | None = None,
        transition_type: str | None = None,
        verification: str | None = None,
        effective_date: str | None = None,
        date_role: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> OperationalUpdateRow:
        """Append one operational record."""

        row = OperationalUpdateRow(
            operational_update_id=str(uuid4()),
            project_id=str(project_id),
            message_id=str(message_id),
            classification_id=classification_id,
            kind=kind,
            subject=subject,
            reported_status=reported_status,
            current_status=current_status,
            transition_type=transition_type,
            authority=authority,
            state=state,
            verification=verification,
            effective_date=effective_date,
            date_role=date_role,
            detail=dict(detail or {}),
            idempotency_key=idempotency_key,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        return row

    def active(
        self, project_id: ProjectId, states: Sequence[str]
    ) -> tuple[OperationalUpdateRow, ...]:
        """Return the records a briefing may show as current."""

        rows = self._session.scalars(
            select(OperationalUpdateRow)
            .where(
                OperationalUpdateRow.project_id == str(project_id),
                OperationalUpdateRow.state.in_(list(states)),
            )
            .order_by(OperationalUpdateRow.created_at.desc())
        ).all()
        return tuple(rows)

    def find_by_idempotency_key(
        self, project_id: ProjectId, idempotency_key: str
    ) -> OperationalUpdateRow | None:
        return self._session.scalars(
            select(OperationalUpdateRow).where(
                OperationalUpdateRow.project_id == str(project_id),
                OperationalUpdateRow.idempotency_key == idempotency_key,
            )
        ).first()

    def latest_status(self, project_id: ProjectId, subject: str) -> str | None:
        """Return the last recorded status for a subject, if any.

        What "current" means for a reported transition: the status this project
        last recorded, not the one the sentence claims.
        """

        row = self._session.scalars(
            select(OperationalUpdateRow)
            .where(
                OperationalUpdateRow.project_id == str(project_id),
                OperationalUpdateRow.subject == subject,
                OperationalUpdateRow.reported_status.is_not(None),
            )
            .order_by(OperationalUpdateRow.created_at.desc())
        ).first()
        return row.reported_status if row else None
