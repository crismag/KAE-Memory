"""The module graph is readable by the person who owns the project.

`D-19`. `ModuleService` has computed the graph, both directions of a module's
neighbourhood, and a stable build order since N17/N18. The only adapter over it
was `kae_get_module_graph`, an MCP tool — so **a coding agent could read a
project's architecture and its owner could not**, which is the wrong way round,
and it is why Studio's `/dependencies` is empty on every deployment.

Reads only. Defining a module and drawing an edge stay on MCP until somebody
rules who may draw an architecture; three GETs create nothing and decide
nothing, which is what makes adding them safe without that ruling.

## What these hold

That the graph arrives in the vocabulary a caller can draw with — **keys, not
internal identifiers** — that build order is an answer rather than a listing,
and that an empty project says *"no modules"* rather than looking like a failure
to read.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application.module_service import ModuleService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.relationships import ModuleRelation


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Architecture"}).json()["id"])


@pytest.fixture
def modules(factory: sessionmaker[Session]) -> ModuleService:
    return ModuleService(factory)


@pytest.fixture
def architecture(modules: ModuleService, project: str) -> str:
    """A small system: reporting depends on approval, which depends on identity.

    Built through the service rather than through fixtures, because the point of
    these tests is that what the write path stores is what the read path
    returns.
    """

    identifier = ProjectId(project)
    modules.define(identifier, "identity", "Identity")
    modules.define(identifier, "approval", "Approval workflow")
    modules.define(identifier, "reporting", "Reporting")
    modules.relate(identifier, "approval", ModuleRelation.DEPENDS_ON, target_key="identity")
    modules.relate(identifier, "reporting", ModuleRelation.DEPENDS_ON, target_key="approval")
    return project


class TestTheGraphIsReadable:
    def test_it_lists_every_module(self, client: TestClient, architecture: str) -> None:
        response = client.get(f"/v1/projects/{architecture}/modules")

        assert response.status_code == 200
        assert [module["key"] for module in response.json()] == [
            "approval",
            "identity",
            "reporting",
        ]

    def test_edges_arrive_as_keys_a_caller_can_draw_with(
        self, client: TestClient, architecture: str
    ) -> None:
        """Not internal identifiers.

        A graph returned in module ids is one every caller has to resolve
        before it can be drawn, and every caller would resolve it identically.
        """

        edges = client.get(f"/v1/projects/{architecture}/modules/graph").json()["edges"]

        assert {(edge["source"], edge["target_module"]) for edge in edges} == {
            ("approval", "identity"),
            ("reporting", "approval"),
        }
        assert {edge["relation"] for edge in edges} == {"depends_on"}

    def test_build_order_puts_dependencies_first(
        self, client: TestClient, architecture: str
    ) -> None:
        """The question a dependency graph exists to answer."""

        graph = client.get(f"/v1/projects/{architecture}/modules/graph").json()

        assert graph["build_order"] == ["identity", "approval", "reporting"]

    def test_it_says_what_build_order_does_not_mean(
        self, client: TestClient, architecture: str
    ) -> None:
        # An order with nothing said about it reads as "these are ready to
        # build in this sequence", which is a claim about knowledge the graph
        # has not looked at.
        graph = client.get(f"/v1/projects/{architecture}/modules/graph").json()

        assert "not yet confirmed" in graph["note"]


class TestDiggingIntoOneModule:
    def test_it_answers_both_directions_at_once(
        self, client: TestClient, architecture: str
    ) -> None:
        """What must exist before I build this, and what breaks if I change it.

        Opposite questions, needed at the same moment, which is why they are
        one response rather than two calls.
        """

        approval = client.get(f"/v1/projects/{architecture}/modules/approval").json()

        assert [module["key"] for module in approval["depends_on"]] == ["identity"]
        assert [module["key"] for module in approval["dependents"]] == ["reporting"]

    def test_a_module_nobody_defined_is_not_found(
        self, client: TestClient, architecture: str
    ) -> None:
        response = client.get(f"/v1/projects/{architecture}/modules/invented")

        # Not an empty neighbourhood, which would read as a module that exists
        # and touches nothing.
        assert response.status_code == 404
        # And it says *which* thing is missing. A 404 reading "project not
        # found" sends a reader to check the project id, which is correct, and
        # they will find it fine, and they will have learned nothing. The
        # subject of a not-found is the whole message.
        assert "invented" in response.text
        assert "module" in response.text


class TestWhatItSaysWhenThereIsNothing:
    def test_a_project_with_no_modules_returns_an_empty_list(
        self, client: TestClient, project: str
    ) -> None:
        """A real answer, and the one that could not be given before.

        Studio's projection hardcodes `modules: unavailable` because there was
        no route to call. *"This project has no modules"* and *"modules cannot
        be read here"* are different statements and a surface has to be able to
        tell them apart.
        """

        response = client.get(f"/v1/projects/{project}/modules")

        assert response.status_code == 200
        assert response.json() == []

    def test_an_empty_graph_is_still_a_graph(self, client: TestClient, project: str) -> None:
        graph = client.get(f"/v1/projects/{project}/modules/graph").json()

        assert graph["modules"] == []
        assert graph["edges"] == []
        assert graph["build_order"] == []

    def test_a_project_that_does_not_exist_is_not_an_empty_project(
        self, client: TestClient
    ) -> None:
        response = client.get("/v1/projects/00000000-0000-0000-0000-000000000000/modules/graph")

        assert response.status_code == 404


class TestItStaysReadOnly:
    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_no_write_verb_is_exposed(
        self, client: TestClient, architecture: str, method: str
    ) -> None:
        """Drawing an architecture is not a decision this loop may hand out.

        `D-19` added reads because reads create nothing. The write path is
        `kae_define_module` and `kae_relate_modules` over MCP, and it stays
        there until somebody rules who may draw an architecture — so a write
        verb appearing here is a ruling taken by accident.
        """

        response = getattr(client, method)(f"/v1/projects/{architecture}/modules")

        assert response.status_code == 405
