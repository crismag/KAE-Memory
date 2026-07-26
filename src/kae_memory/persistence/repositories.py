"""Repository contracts and SQLAlchemy implementation."""

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from kae_memory.domain.identifiers import AgentId, ExecutionId, KnowledgeItemId, ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeVersion, Provenance

from .tables import KnowledgeItemRow, KnowledgeVersionRow


class KnowledgeRepository(Protocol):
    """Persistence boundary for durable knowledge items."""

    def add(self, item: KnowledgeItem) -> None: ...

    def get(self, item_id: KnowledgeItemId) -> KnowledgeItem | None: ...


class SqlAlchemyKnowledgeRepository:
    """SQLAlchemy-backed repository with explicit domain mapping."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, item: KnowledgeItem) -> None:
        self._session.add(
            KnowledgeItemRow(
                id=str(item.id),
                project_id=str(item.project_id),
                kind=item.kind,
                lifecycle=item.lifecycle.value,
            )
        )
        self._session.add_all(
            [
                KnowledgeVersionRow(
                    knowledge_item_id=str(item.id),
                    version_number=version.number,
                    content=version.content,
                    source=version.provenance.source,
                    actor_id=str(version.provenance.actor_id),
                    execution_id=str(version.provenance.execution_id),
                    recorded_at=version.provenance.recorded_at,
                    created_at=version.created_at,
                )
                for version in item.versions
            ]
        )

    def get(self, item_id: KnowledgeItemId) -> KnowledgeItem | None:
        row = self._session.get(KnowledgeItemRow, str(item_id))
        if row is None:
            return None
        versions = self._session.scalars(
            select(KnowledgeVersionRow)
            .where(KnowledgeVersionRow.knowledge_item_id == str(item_id))
            .order_by(KnowledgeVersionRow.version_number)
        ).all()
        return _to_domain(row, versions)


def _to_domain(row: KnowledgeItemRow, versions: Sequence[KnowledgeVersionRow]) -> KnowledgeItem:
    return KnowledgeItem(
        id=KnowledgeItemId(row.id),
        project_id=ProjectId(row.project_id),
        kind=row.kind,
        lifecycle=LifecycleState(row.lifecycle),
        versions=tuple(
            KnowledgeVersion(
                number=version.version_number,
                content=version.content,
                provenance=Provenance(
                    source=version.source,
                    actor_id=AgentId(version.actor_id),
                    execution_id=ExecutionId(version.execution_id),
                    recorded_at=version.recorded_at,
                ),
                created_at=version.created_at,
            )
            for version in versions
        ),
    )
