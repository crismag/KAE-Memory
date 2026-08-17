"""Every `ModuleRelation` can be written, and comes back out saying which it is.

`D-219`. :class:`ModuleRelation`'s docstring said *"Nothing persists these
yet"*. It was true when the enum was declared before its model (N17) and has
been false since ``module_relationships`` was added: :meth:`ModuleService.relate`
writes every member, the graph loader reads them back, and ``kae_relate_modules``
reaches the write path from outside the process.

The cost of the stale sentence was paid downstream. `ARC-EDGE-KINDS` traced
KAE-Studio's architecture diagram dropping five of the six relations, checked
whether anything could produce one, and recorded the row as latent under `D-45`.
The check was a grep for ``ModuleService.record_edge`` — a method that does not
exist under that name in this repository or any other, so it returned nothing
for the same reason a grep for any misspelling does. Three relations a project
can record today were filed as unproducible on that evidence.

So these hold the claim the docstring now makes, rather than the docstring:

* every member survives the write and comes back over ``/modules/graph`` under
  its own name, which is what makes a consumer dropping one a defect;
* the two that run to statements arrive with a knowledge target and no module
  target, and the other four the other way round — the partition KAE-Studio's
  ``drawnRelations.ts`` splits on is a fact about this service, not an
  assumption Studio made;
* the write path is declared reachable in :mod:`kae_memory.capabilities`, which
  is the register a producibility question should be asked of. A `D-45` stop
  that reads it cannot be defeated by a typo.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application.module_service import ModuleService
from kae_memory.capabilities import by_key, declared_mcp_tools
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.modules import KNOWLEDGE_TARGETED
from kae_memory.domain.relationships import ModuleRelation


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def modules(factory: sessionmaker[Session]) -> ModuleService:
    return ModuleService(factory)


@pytest.fixture
def project(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Architecture"}).json()["id"])


def _record(modules: ModuleService, project: str, relation: ModuleRelation) -> None:
    """One edge of `relation`, between two modules or from one to a statement.

    A fresh pair per relation because `owns` is exclusive and `depends_on` and
    `owns` must stay acyclic — six edges over one pair would be refused by the
    domain for reasons that have nothing to do with what is under test.
    """

    identifier = ProjectId(project)
    source, target = f"{relation.value}-source", f"{relation.value}-target"
    modules.define(identifier, source, source)
    if relation in KNOWLEDGE_TARGETED:
        modules.relate(identifier, source, relation, knowledge_id=f"k-{relation.value}")
        return
    modules.define(identifier, target, target)
    modules.relate(identifier, source, relation, target_key=target)


class TestEveryRelationSurvivesTheRoundTrip:
    @pytest.mark.parametrize("relation", list(ModuleRelation))
    def test_it_is_written_and_read_back_as_itself(
        self, client: TestClient, modules: ModuleService, project: str, relation: ModuleRelation
    ) -> None:
        _record(modules, project, relation)

        graph = client.get(f"/v1/projects/{project}/modules/graph").json()

        assert [edge["relation"] for edge in graph["edges"]] == [relation.value]

    def test_no_relation_is_dropped_between_the_write_and_the_wire(
        self, client: TestClient, modules: ModuleService, project: str
    ) -> None:
        # The parametrised case above would still pass if five of six were
        # silently unstorable, one empty project at a time.
        for relation in ModuleRelation:
            _record(modules, project, relation)

        graph = client.get(f"/v1/projects/{project}/modules/graph").json()

        assert {edge["relation"] for edge in graph["edges"]} == {r.value for r in ModuleRelation}


class TestWhatEachRelationPointsAt:
    @pytest.mark.parametrize("relation", sorted(KNOWLEDGE_TARGETED))
    def test_a_knowledge_relation_arrives_with_no_module_target(
        self, client: TestClient, modules: ModuleService, project: str, relation: ModuleRelation
    ) -> None:
        _record(modules, project, relation)

        edge = client.get(f"/v1/projects/{project}/modules/graph").json()["edges"][0]

        assert edge["target_module"] is None
        assert edge["target_knowledge"] == f"k-{relation.value}"

    @pytest.mark.parametrize("relation", sorted(set(ModuleRelation) - KNOWLEDGE_TARGETED))
    def test_a_structural_relation_arrives_with_a_module_at_both_ends(
        self, client: TestClient, modules: ModuleService, project: str, relation: ModuleRelation
    ) -> None:
        # Which is why a diagram cannot exclude these for the reason it
        # excludes `satisfies`: there is a box to point at (`D-219`).
        _record(modules, project, relation)

        edge = client.get(f"/v1/projects/{project}/modules/graph").json()["edges"][0]

        assert edge["target_module"] == f"{relation.value}-target"
        assert edge["target_knowledge"] is None


class TestTheWritePathIsDeclaredReachable:
    def test_the_register_names_the_tool_that_records_an_edge(self) -> None:
        """The control a producibility check needs.

        `ARC-EDGE-KINDS` concluded *no HTTP route, no MCP tool* from a grep. The
        capability register answers the same question by construction, and a
        `D-45` stop that consults it states a caller it did or did not find
        rather than an absence that a misspelling produces for free.
        """

        assert by_key("module.relate").mcp == ("kae_relate_modules",)
        assert "kae_relate_modules" in declared_mcp_tools()
