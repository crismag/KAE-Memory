"""T0.2 — a project can be removed, with everything scoped to it (F-021).

Nine tables reference `projects` and every foreign key is `NO ACTION`, so
`DELETE FROM projects` fails on a violation. Nothing on any adapter deletes or
archives, and `ProjectStatus.ARCHIVED` is modelled and never set — so clearing
55 accumulated test projects meant hand-ordered SQL against production.

These tests exist because a half-completed deletion is the worst outcome
available here: it leaves rows pointing at a project that no longer exists, and
nothing reports it. The interesting assertions are therefore the negative ones —
what is *still there* afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.project_deletion_service import (
    ProjectDeletionError,
    ProjectDeletionService,
)
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.workspace import ActorType, SessionType
from kae_memory.persistence.tables import KnowledgeItemRow, KnowledgeVersionRow, MessageRow


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def deletion(factory: sessionmaker[Session]) -> ProjectDeletionService:
    return ProjectDeletionService(factory)


def _populated(factory: sessionmaker[Session], name: str) -> ProjectId:
    """A project with something in most of the tables a deletion must clear."""

    ReadinessService(factory).install_template()
    memory = MemoryService(factory)
    project = ProjectId(str(memory.create_project(name).id))

    session = memory.open_session(project, SessionType.DISCOVERY)
    memory.record_message(project, session.id, "Invoices go out within three days.", ActorType.USER)

    run = memory.start_run(project, AgentRole.REQUIREMENTS, f"del-{name}")
    written = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(KnowledgeKind.RULE.value, f"{name}: a rule.", "interview"),
            WriteKnowledgeRequest(KnowledgeKind.ACTOR.value, f"{name}: an actor.", "interview"),
        ],
    )
    memory.confirm_knowledge(written[0].id)

    readiness = ReadinessService(factory)
    readiness.assign_area(project, written[1].id, "users_and_stakeholders")
    readiness.calculate(project)
    return project


def _count(factory: sessionmaker[Session], table: Any, column: Any, value: str) -> int:
    with factory() as session:
        return int(
            session.execute(
                select(func.count()).select_from(table).where(column == value)
            ).scalar_one()
        )


class TestThePlanReportsBeforeAnythingChanges:
    def test_it_names_the_projects_and_counts_the_rows(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        project = _populated(factory, "plan")

        plan = deletion.plan([project])

        assert [p.name for p in plan.projects] == ["plan"]
        assert plan.rows["knowledge_items"] == 2
        assert plan.rows["messages"] == 1
        assert plan.total_rows > 0

    def test_planning_deletes_nothing(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """The whole point of a dry run.

        A plan that changed anything would be a plan nobody could safely run
        twice, and this one is meant to be run repeatedly while a person reads
        the list.
        """

        project = _populated(factory, "unchanged")

        deletion.plan([project])
        deletion.plan([project])

        assert _count(factory, KnowledgeItemRow, KnowledgeItemRow.project_id, str(project)) == 2

    def test_an_id_that_no_longer_exists_is_reported_not_raised(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """A caller planning from a stale list needs to see *which* id is gone.

        Raising would tell them only that one of them was.
        """

        project = _populated(factory, "partly stale")
        ghost = "00000000-0000-0000-0000-000000000000"

        plan = deletion.plan([project, ghost])

        assert plan.missing == (ghost,)
        assert [p.name for p in plan.projects] == ["partly stale"]


class TestDeletionRemovesEverythingScoped:
    def test_the_project_and_its_rows_are_gone(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        project = _populated(factory, "target")

        deletion.delete([project])

        assert _count(factory, KnowledgeItemRow, KnowledgeItemRow.project_id, str(project)) == 0
        assert _count(factory, MessageRow, MessageRow.project_id, str(project)) == 0
        assert deletion.plan([project]).projects == ()

    def test_knowledge_versions_go_with_their_items(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """The one table with no `project_id`.

        Versions hang off knowledge items, so nothing else would remove them —
        and orphaned versions are invisible: they break no constraint and appear
        in no project-scoped read.
        """

        project = _populated(factory, "versions")
        with factory() as session:
            item_ids = [
                row.id
                for row in session.execute(
                    select(KnowledgeItemRow).where(KnowledgeItemRow.project_id == str(project))
                ).scalars()
            ]
        assert item_ids

        deletion.delete([project])

        for item_id in item_ids:
            assert (
                _count(
                    factory,
                    KnowledgeVersionRow,
                    KnowledgeVersionRow.knowledge_item_id,
                    item_id,
                )
                == 0
            )

    def test_it_succeeds_despite_every_foreign_key_being_no_action(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """F-021, stated as a test.

        `DELETE FROM projects` alone raises here. That this does not is the
        entire contribution — the ordering is the feature.
        """

        project = _populated(factory, "ordering")

        deletion.delete([project])  # must not raise

        assert deletion.plan([project]).projects == ()


class TestOtherProjectsAreUntouched:
    def test_a_neighbour_keeps_every_row(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """The assertion that matters most.

        A deletion that removed slightly too much would look identical to a
        correct one from the deleted project's side.
        """

        doomed = _populated(factory, "doomed")
        keeper = _populated(factory, "keeper")
        before = deletion.plan([keeper])

        deletion.delete([doomed])

        after = deletion.plan([keeper])
        assert after.rows == before.rows
        assert [p.name for p in after.projects] == ["keeper"]

    def test_deleting_two_leaves_the_third(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        first = _populated(factory, "first")
        second = _populated(factory, "second")
        third = _populated(factory, "third")

        deletion.delete([first, second])

        assert [p.name for p in deletion.plan([first, second, third]).projects] == ["third"]


class TestItRefusesWhatItShould:
    def test_an_empty_request_is_refused(self, deletion: ProjectDeletionService) -> None:
        """A filter that matched nothing must not report success.

        Returning quietly teaches the caller their filter worked, and the next
        one is run with more confidence and a wider pattern.
        """

        with pytest.raises(ProjectDeletionError, match="matched nothing"):
            deletion.delete([])

    def test_a_protected_project_is_refused(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """Checked here as well as by the caller.

        A caller that has already produced a wrong list is not a caller whose
        filtering should be trusted a second time in the same operation.
        """

        keeper = _populated(factory, "protected")
        doomed = _populated(factory, "doomed too")

        with pytest.raises(ProjectDeletionError, match="protected"):
            deletion.delete([doomed, keeper], protected=[keeper])

    def test_a_refused_deletion_removes_nothing(
        self, factory: sessionmaker[Session], deletion: ProjectDeletionService
    ) -> None:
        """Refusal is not partial completion.

        The protected project is second in the list, so a naive implementation
        that checked per item would already have deleted the first.
        """

        keeper = _populated(factory, "protected two")
        doomed = _populated(factory, "doomed three")

        with pytest.raises(ProjectDeletionError):
            deletion.delete([doomed, keeper], protected=[keeper])

        assert len(deletion.plan([doomed, keeper]).projects) == 2
