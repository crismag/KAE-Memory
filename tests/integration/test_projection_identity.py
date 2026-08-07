"""EM-1 — a consumer can name the project and revision it is looking at.

The gap this closes was found by misdiagnosis. A deployed Studio showed one
project's worth of unrelated-looking content and it read as cross-project
leakage; isolation was proven intact (F-012) and the real cause was a client
pinned to the first of eighteen projects. **Nothing in the payload said which
project it described**, so "these are different projects" and "these numbers
disagree" looked identical from the outside.

Two revisions matter here and they are easy to confuse:

* ``Project.knowledge_revision`` — where the project is **now**;
* ``ReadinessSnapshot.knowledge_revision`` — the revision readiness was
  **calculated at**.

Studio displayed the second and labelled it "revision". It is a real number that
stops moving whenever readiness stops being recalculated, which is worse than a
blank: a blank prompts a question, a stale number answers one wrongly. Both are
now carried, and `is_stale` is the difference between them.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.module_service import ModuleService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.relationships import ModuleRelation


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def memory(factory: sessionmaker[Session]) -> MemoryService:
    return MemoryService(factory)


def _new(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post("/v1/projects", json={"name": name})
    assert response.status_code in (200, 201), response.text
    return dict(response.json())


def _write(memory: MemoryService, project: ProjectId, text: str) -> Any:
    run = memory.start_run(project, AgentRole.REQUIREMENTS, f"identity-{text[:16]}")
    (item,) = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, text, "interview")]
    )
    return item


class TestAProjectNamesItsRevision:
    def test_a_new_project_reports_revision_zero(self, client: TestClient) -> None:
        """Zero is data, not a missing value.

        It has to be readable as "nobody has written to this yet" rather than as
        "this field is not populated", which is the reading that made a stale
        revision invisible.
        """

        assert _new(client, "EM-1 fresh")["knowledge_revision"] == 0

    def test_the_revision_advances_when_knowledge_changes(
        self, client: TestClient, memory: MemoryService
    ) -> None:
        project = ProjectId(_new(client, "EM-1 advancing")["id"])
        before = client.get(f"/v1/projects/{project}").json()["knowledge_revision"]

        _write(memory, project, "Invoices are sent within three days.")

        after = client.get(f"/v1/projects/{project}").json()["knowledge_revision"]
        assert after > before, "a write must move the revision, or it cannot be compared against"

    def test_confirmation_advances_it_too(self, client: TestClient, memory: MemoryService) -> None:
        """Not only writes. A person ruling on a candidate changes what the
        project knows, and a consumer caching on revision would otherwise serve
        the pre-confirmation state indefinitely."""

        project = ProjectId(_new(client, "EM-1 confirming")["id"])
        item = _write(memory, project, "Every invoice carries a client reference.")
        after_write = client.get(f"/v1/projects/{project}").json()["knowledge_revision"]

        memory.confirm_knowledge(item.id)

        assert client.get(f"/v1/projects/{project}").json()["knowledge_revision"] > after_write

    def test_the_listing_carries_it_too(self, client: TestClient, memory: MemoryService) -> None:
        """A client choosing among projects needs this before it picks one.

        Studio's selector is the caller: without a revision in the list it can
        show eighteen names and nothing about which are alive.
        """

        project = ProjectId(_new(client, "EM-1 listed")["id"])
        _write(memory, project, "Reports are approved before publication.")

        listed = next(p for p in client.get("/v1/projects").json() if p["id"] == str(project))
        assert listed["knowledge_revision"] > 0


class TestOneProjectDoesNotMoveAnother:
    def test_a_write_leaves_the_other_projects_revision_alone(
        self, client: TestClient, memory: MemoryService
    ) -> None:
        """The revision must be per-project or it is a global clock.

        A shared counter would make every project look changed whenever any
        project changed, and a consumer polling on it would refetch everything
        forever while learning nothing.
        """

        left = ProjectId(_new(client, "EM-1 left")["id"])
        right = ProjectId(_new(client, "EM-1 right")["id"])
        right_before = client.get(f"/v1/projects/{right}").json()

        _write(memory, left, "Invoices must be sent within three days.")

        assert client.get(f"/v1/projects/{right}").json() == right_before


class TestReadinessDistinguishesTheTwoRevisions:
    def test_it_reports_both(
        self, client: TestClient, factory: sessionmaker[Session], memory: MemoryService
    ) -> None:
        ReadinessService(factory).install_template()
        project = ProjectId(_new(client, "EM-1 readiness")["id"])
        readiness = client.get(f"/v1/projects/{project}/readiness").json()

        assert "knowledge_revision" in readiness
        assert "current_knowledge_revision" in readiness

    def test_a_write_moves_current_and_leaves_the_snapshot_behind(
        self, client: TestClient, factory: sessionmaker[Session], memory: MemoryService
    ) -> None:
        """The whole point of carrying both.

        After a write the snapshot is behind, `current` is ahead, and `is_stale`
        is exactly that difference — so a reader can say *how far* behind
        readiness is rather than only that it is.
        """

        ReadinessService(factory).install_template()
        project = ProjectId(_new(client, "EM-1 staleness")["id"])
        client.get(f"/v1/projects/{project}/readiness")

        _write(memory, project, "A thought is captured in one step.")

        readiness = client.get(f"/v1/projects/{project}/readiness").json()
        assert readiness["current_knowledge_revision"] > readiness["knowledge_revision"]
        assert readiness["is_stale"] is True

    def test_the_project_and_readiness_agree_on_current(
        self, client: TestClient, factory: sessionmaker[Session], memory: MemoryService
    ) -> None:
        """Two surfaces, one answer.

        If these could disagree, a consumer would have to know which endpoint to
        believe — and the reason this phase exists is that it had no way to.
        """

        ReadinessService(factory).install_template()
        project = ProjectId(_new(client, "EM-1 agreement")["id"])
        _write(memory, project, "Nothing is deleted; completed items stay readable.")

        project_view = client.get(f"/v1/projects/{project}").json()
        readiness = client.get(f"/v1/projects/{project}/readiness").json()

        assert readiness["current_knowledge_revision"] == project_view["knowledge_revision"]


class TestCrossProjectReferencesAreRejected:
    """The one EM-1 acceptance proof F-012 did not already cover.

    F-012 proves reads do not *leak* across projects. It does not prove a write
    cannot *create* a link across them, which is the other half — an accepted
    cross-project edge would make every later isolation guarantee conditional on
    nobody having written one.
    """

    def test_a_module_cannot_depend_on_another_projects_module(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        modules = ModuleService(factory)
        left = ProjectId(_new(client, "EM-1 xref left")["id"])
        right = ProjectId(_new(client, "EM-1 xref right")["id"])
        modules.define(left, "billing", "Billing")
        modules.define(right, "ledger", "Ledger")

        # Named from the left project, where "ledger" does not exist. The lookup
        # is project-scoped, so the target is simply absent rather than
        # borrowable — which is the guarantee, expressed as a missing row.
        with pytest.raises((DomainInvariantError, LookupError)):
            modules.relate(left, "billing", ModuleRelation.DEPENDS_ON, "ledger")

    def test_the_rejection_leaves_no_edge_behind(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        modules = ModuleService(factory)
        left = ProjectId(_new(client, "EM-1 xref rollback left")["id"])
        right = ProjectId(_new(client, "EM-1 xref rollback right")["id"])
        modules.define(left, "billing", "Billing")
        modules.define(right, "ledger", "Ledger")

        with pytest.raises((DomainInvariantError, LookupError)):
            modules.relate(left, "billing", ModuleRelation.DEPENDS_ON, "ledger")

        billing = next(m for m in modules.list_modules(left) if m.key == "billing")
        graph = modules.graph(left)
        assert graph.outgoing(billing.id, ModuleRelation.DEPENDS_ON) == ()

    def test_the_other_project_is_untouched(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        modules = ModuleService(factory)
        left = ProjectId(_new(client, "EM-1 xref untouched left")["id"])
        right = ProjectId(_new(client, "EM-1 xref untouched right")["id"])
        modules.define(left, "billing", "Billing")
        modules.define(right, "ledger", "Ledger")

        with pytest.raises((DomainInvariantError, LookupError)):
            modules.relate(left, "billing", ModuleRelation.DEPENDS_ON, "ledger")

        assert [m.key for m in modules.list_modules(right)] == ["ledger"]
