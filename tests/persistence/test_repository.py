from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.identifiers import AgentId, ExecutionId, KnowledgeItemId, ProjectId
from kae_memory.domain.models import KnowledgeItem, KnowledgeVersion, Provenance
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.tables import Base


def test_repository_round_trip_preserves_versions_and_provenance() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    timestamp = datetime(2026, 7, 26, tzinfo=UTC)
    item = KnowledgeItem(
        id=KnowledgeItemId("knowledge-1"),
        project_id=ProjectId("project-1"),
        kind="requirement",
        versions=(
            KnowledgeVersion(
                number=1,
                content="The system preserves durable context.",
                provenance=Provenance(
                    source="interview",
                    actor_id=AgentId("requirements-agent"),
                    execution_id=ExecutionId("execution-1"),
                    recorded_at=timestamp,
                ),
                created_at=timestamp,
            ),
        ),
    )

    with factory.begin() as session:
        SqlAlchemyKnowledgeRepository(session).add(item)

    with factory() as session:
        restored = SqlAlchemyKnowledgeRepository(session).get(item.id)

    assert restored == item


def test_repository_returns_none_for_unknown_item() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with sessionmaker(engine)() as session:
        restored = SqlAlchemyKnowledgeRepository(session).get(KnowledgeItemId("missing"))

    assert restored is None
