"""Recording, accepting, and retiring assumptions (N35).

The boundary: this service writes to `assumptions` and to nothing else. It has
no reference to `MemoryService`, no path to `knowledge_items`, and no way to
confirm anything — which is how "a material assumption is never silently
promoted to a confirmed requirement" is enforced rather than merely intended.

Accepting an assumption records that a person is willing to proceed on it.
Confirming knowledge records that a person believes it is true. Those are
different acts with different consequences, and a service that could do both
would eventually be asked to.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.assumptions import (
    Assumption,
    AssumptionId,
    AssumptionOrigin,
    AssumptionState,
    Consequence,
    RevisitTrigger,
    ensure_assumption_transition,
)
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.tables import AssumptionRow
from kae_memory.persistence.transactions import run_transaction


class AssumptionNotFoundError(LookupError):
    """No assumption with that id exists in this project."""


class AssumptionService:
    """Durable assumptions, and nothing that could promote one."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        project_id: ProjectId,
        subject: str,
        assumed_value: str,
        reason: str,
        origin: AssumptionOrigin = AssumptionOrigin.KAE_INFERRED,
        consequence: Consequence = Consequence.REWORK,
        confidence: float = 0.5,
        reversible: bool = True,
        revisit: RevisitTrigger = RevisitTrigger.ON_REQUEST,
        evidence: Sequence[str] | None = None,
        delegated: bool = False,
    ) -> Assumption:
        """Record an assumption as proposed.

        Proposed, never accepted, whoever asked. Acceptance is a person taking
        responsibility, and a caller that could record one already accepted
        would be recording a decision nobody made.
        """

        candidate = Assumption(
            id=AssumptionId(str(uuid4())),
            project_id=project_id,
            subject=subject.strip(),
            assumed_value=assumed_value.strip(),
            reason=reason.strip(),
            origin=origin,
            consequence=consequence,
            confidence=confidence,
            reversible=reversible,
            revisit=revisit,
            evidence=tuple(evidence or ()),
            delegated=delegated,
        )

        def operation(session: DbSession) -> Assumption:
            session.add(_as_row(candidate))
            session.flush()
            return candidate

        return run_transaction(self._session_factory, operation)

    def accept(self, project_id: ProjectId, assumption_id: str, actor: str) -> Assumption:
        """Record that a person is willing to proceed on this assumption.

        `actor` is required for the same reason `reviewer` is on confirmation:
        responsibility nobody is named for is none. Acceptance does not make
        the assumption true and does not create knowledge.
        """

        if not actor or not actor.strip():
            raise ValueError("an actor is required: acceptance is a person's decision")
        return self._transition(project_id, assumption_id, AssumptionState.ACCEPTED, actor.strip())

    def reject(self, project_id: ProjectId, assumption_id: str, actor: str) -> Assumption:
        """Record that this assumption should not be proceeded on."""

        return self._transition(project_id, assumption_id, AssumptionState.REJECTED, actor.strip())

    def retire(self, project_id: ProjectId, assumption_id: str) -> Assumption:
        """Record that the gap this covered has been answered.

        The healthy end of an assumption's life, and distinct from rejection:
        retired means the question was settled, rejected means the guess was
        wrong. A reader needs to tell those apart.
        """

        return self._transition(project_id, assumption_id, AssumptionState.RETIRED, None)

    def list_for_project(
        self, project_id: ProjectId, active_only: bool = True
    ) -> tuple[Assumption, ...]:
        def operation(session: DbSession) -> tuple[Assumption, ...]:
            statement = select(AssumptionRow).where(AssumptionRow.project_id == str(project_id))
            if active_only:
                statement = statement.where(
                    AssumptionRow.state.in_(
                        [AssumptionState.PROPOSED.value, AssumptionState.ACCEPTED.value]
                    )
                )
            rows = session.scalars(statement.order_by(AssumptionRow.created_at.desc())).all()
            return tuple(_as_assumption(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def _transition(
        self, project_id: ProjectId, assumption_id: str, target: AssumptionState, actor: str | None
    ) -> Assumption:
        def operation(session: DbSession) -> Assumption:
            row = session.scalars(
                select(AssumptionRow).where(
                    AssumptionRow.project_id == str(project_id),
                    AssumptionRow.assumption_id == assumption_id,
                )
            ).first()
            if row is None:
                raise AssumptionNotFoundError(f"no assumption {assumption_id!r} in this project")
            ensure_assumption_transition(AssumptionState(row.state), target)
            row.state = target.value
            if actor is not None:
                row.accepted_by = actor
            session.flush()
            return _as_assumption(row)

        return run_transaction(self._session_factory, operation)


def _as_row(assumption: Assumption) -> AssumptionRow:
    return AssumptionRow(
        assumption_id=str(assumption.id),
        project_id=str(assumption.project_id),
        subject=assumption.subject,
        assumed_value=assumption.assumed_value,
        reason=assumption.reason,
        origin=assumption.origin.value,
        consequence=assumption.consequence.value,
        confidence=assumption.confidence,
        state=assumption.state.value,
        reversible=assumption.reversible,
        scope=assumption.scope,
        revisit=assumption.revisit.value,
        evidence=list(assumption.evidence),
        accepted_by=assumption.accepted_by,
        delegated=assumption.delegated,
        supersedes=assumption.supersedes,
        created_at=datetime.now(UTC),
    )


def _as_assumption(row: AssumptionRow) -> Assumption:
    return Assumption(
        id=AssumptionId(str(row.assumption_id)),
        project_id=ProjectId(str(row.project_id)),
        subject=row.subject,
        assumed_value=row.assumed_value,
        reason=row.reason,
        origin=AssumptionOrigin(row.origin),
        consequence=Consequence(row.consequence),
        confidence=row.confidence,
        state=AssumptionState(row.state),
        reversible=row.reversible,
        scope=row.scope,
        revisit=RevisitTrigger(row.revisit),
        evidence=tuple(row.evidence or ()),
        accepted_by=row.accepted_by,
        delegated=row.delegated,
        supersedes=row.supersedes,
        created_at=row.created_at,
    )
