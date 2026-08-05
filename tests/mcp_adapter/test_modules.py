"""Modules, the graph, and module-scoped context (N17, N18, N19).

`kae_get_module_context` reported a capability gap through all twenty-five
T-targets. What made it unavailable was never the assembly — it was that
modules had no model, no edges, and no traversal, so any context it produced
would have been invented by the adapter rather than retrieved from the domain.

Three things this defends.

**A cycle is refused at write time.** A graph checked only when traversed
stores state it cannot answer from, and the caller who discovers that is the
one who least caused it.

**Ownership is exclusive.** Two modules that each own the target means nobody
is answerable, which is the whole reason `owns` is distinguished from
`depends_on`.

**A dependency arrives as a stub.** An implementer needs to know what a
dependency offers, not how it is built. Expanding them would reproduce the
whole project one edge at a time, which is what a module scope exists to
prevent.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.module_service import ModuleService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.modules import (
    CyclicModuleGraphError,
    ModuleEdge,
    ModuleGraph,
    ModuleId,
)
from kae_memory.domain.relationships import ModuleRelation
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        modules=ModuleService(factory),
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Ministry", key="n17-ministry").id)


def _define(context: tools.ToolContext, project_id: str, key: str, name: str) -> dict[str, Any]:
    return dispatch(
        context, "kae_define_module", {"project_id": project_id, "key": key, "name": name}
    )


def _relate(
    context: tools.ToolContext, project_id: str, source: str, relation: str, **extra: Any
) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_relate_modules",
        {"project_id": project_id, "source": source, "relation": relation, **extra},
    )


class TestTheDomainRules:
    """Checked without a database, because they are not database rules."""

    def _edge(self, source: str, relation: ModuleRelation, target: str) -> ModuleEdge:
        return ModuleEdge(ModuleId(source), relation, target_module=ModuleId(target))

    def test_a_module_cannot_relate_to_itself(self) -> None:
        """A typo, not a cycle. Reporting it as one would bury the real ones."""

        with pytest.raises(Exception, match="itself"):
            self._edge("a", ModuleRelation.DEPENDS_ON, "a")

    def test_an_edge_names_exactly_one_target(self) -> None:
        with pytest.raises(Exception, match="exactly one target"):
            ModuleEdge(ModuleId("a"), ModuleRelation.DEPENDS_ON)

    def test_satisfies_targets_a_statement_not_a_module(self) -> None:
        with pytest.raises(Exception, match="statement"):
            self._edge("a", ModuleRelation.SATISFIES, "b")

    def test_depends_on_targets_a_module_not_a_statement(self) -> None:
        with pytest.raises(Exception, match="module"):
            ModuleEdge(ModuleId("a"), ModuleRelation.DEPENDS_ON, target_knowledge="k1")

    def test_a_cycle_is_visible_before_it_is_written(self) -> None:
        graph = ModuleGraph(
            edges=(
                self._edge("a", ModuleRelation.DEPENDS_ON, "b"),
                self._edge("b", ModuleRelation.DEPENDS_ON, "c"),
            )
        )

        assert graph.would_cycle(self._edge("c", ModuleRelation.DEPENDS_ON, "a")) is True
        assert graph.would_cycle(self._edge("a", ModuleRelation.DEPENDS_ON, "c")) is False

    def test_consumption_may_be_mutual(self) -> None:
        """Two modules consuming each other's interfaces is legitimate."""

        graph = ModuleGraph(edges=(self._edge("a", ModuleRelation.CONSUMES, "b"),))

        assert graph.would_cycle(self._edge("b", ModuleRelation.CONSUMES, "a")) is False

    def test_build_order_puts_dependencies_first(self) -> None:
        graph = ModuleGraph(
            edges=(
                self._edge("web", ModuleRelation.DEPENDS_ON, "api"),
                self._edge("api", ModuleRelation.DEPENDS_ON, "store"),
            )
        )

        order = [
            str(m) for m in graph.build_order((ModuleId("web"), ModuleId("api"), ModuleId("store")))
        ]

        assert order.index("store") < order.index("api") < order.index("web")

    def test_build_order_is_stable(self) -> None:
        """An order that varies cannot be compared to the previous one."""

        graph = ModuleGraph()
        modules = (ModuleId("c"), ModuleId("a"), ModuleId("b"))

        first = [str(m) for m in graph.build_order(modules)]
        second = [str(m) for m in graph.build_order(modules)]

        assert first == second == ["a", "b", "c"]

    def test_an_unreachable_cycle_raises_rather_than_truncating(self) -> None:
        """A partial order looks like an answer, which is worse than an error."""

        graph = ModuleGraph(
            edges=(
                self._edge("a", ModuleRelation.DEPENDS_ON, "b"),
                self._edge("b", ModuleRelation.DEPENDS_ON, "a"),
            )
        )

        with pytest.raises(CyclicModuleGraphError):
            graph.build_order((ModuleId("a"), ModuleId("b")))


class TestDefiningModules:
    def test_a_module_is_proposed_not_confirmed(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """An agent that could confirm its own proposals makes review decorative."""

        payload = _define(context, project_id, "approval", "Approval workflow")

        assert payload["module"]["status"] == "proposed"
        assert payload["knowledge_changed"] is False

    def test_defining_twice_is_idempotent(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        first = _define(context, project_id, "approval", "Approval workflow")
        second = _define(context, project_id, "approval", "Approval workflow")

        assert first["module"]["key"] == second["module"]["key"]
        assert len(context.modules.list_modules(ProjectId(project_id))) == 1  # type: ignore[union-attr]

    def test_a_key_is_required(self, context: tools.ToolContext, project_id: str) -> None:
        payload = dispatch(
            context, "kae_define_module", {"project_id": project_id, "key": "  ", "name": "X"}
        )

        assert payload["error"] == "invalid_argument"


class TestRelatingModules:
    def test_a_dependency_is_recorded(self, context: tools.ToolContext, project_id: str) -> None:
        _define(context, project_id, "web", "Web")
        _define(context, project_id, "api", "API")

        payload = _relate(context, project_id, "web", "depends_on", target="api")

        assert payload["relation"] == "depends_on"

    def test_a_cycle_is_refused_at_write_time(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The assertion the write path exists for."""

        for key in ("a", "b", "c"):
            _define(context, project_id, key, key.upper())
        _relate(context, project_id, "a", "depends_on", target="b")
        _relate(context, project_id, "b", "depends_on", target="c")

        refused = _relate(context, project_id, "c", "depends_on", target="a")

        assert refused["error"] == "invalid_state_transition"
        assert "cycle" in refused["message"]

    def test_ownership_is_exclusive(self, context: tools.ToolContext, project_id: str) -> None:
        for key in ("billing", "reports", "ledger"):
            _define(context, project_id, key, key.title())
        _relate(context, project_id, "billing", "owns", target="ledger")

        refused = _relate(context, project_id, "reports", "owns", target="ledger")

        assert refused["error"] == "invalid_state_transition"
        assert "already owned" in refused["message"]

    def test_a_retired_relation_name_says_what_replaced_it(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Three of the four source documents use at least one retired name."""

        _define(context, project_id, "web", "Web")

        refused = _relate(context, project_id, "web", "implements", knowledge_id="k1")

        assert refused["error"] == "invalid_argument"
        assert "SATISFIES" in refused["message"]

    def test_an_epistemic_relation_is_refused_here(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """One statement does not depend on another, and modules do not contradict."""

        _define(context, project_id, "web", "Web")
        _define(context, project_id, "api", "API")

        refused = _relate(context, project_id, "web", "contradicts", target="api")

        assert refused["error"] == "invalid_argument"
        assert "two statements" in refused["message"]

    def test_an_unknown_module_is_reported(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _define(context, project_id, "web", "Web")

        refused = _relate(context, project_id, "web", "depends_on", target="nothing")

        assert refused["error"] == "knowledge_not_found"


class TestTheGraph:
    def test_build_order_is_returned(self, context: tools.ToolContext, project_id: str) -> None:
        for key in ("web", "api", "store"):
            _define(context, project_id, key, key.title())
        _relate(context, project_id, "web", "depends_on", target="api")
        _relate(context, project_id, "api", "depends_on", target="store")

        payload = dispatch(context, "kae_get_module_graph", {"project_id": project_id})

        order = payload["build_order"]
        assert order.index("store") < order.index("api") < order.index("web")

    def test_it_says_what_build_order_does_not_account_for(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = dispatch(context, "kae_get_module_graph", {"project_id": project_id})

        assert "depends_on only" in payload["note"]


class TestModuleContext:
    """N19 — the capability that reported a gap for twenty-five targets."""

    def _seeded(self, context: tools.ToolContext, project_id: str) -> str:
        run = context.memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "n19-seed")
        written = context.memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    KnowledgeKind.REQUIREMENT.value,
                    "A report must be approved before it is published.",
                    "seed",
                )
            ],
        )
        return str(written[0].id)

    def test_it_answers_instead_of_reporting_a_gap(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _define(context, project_id, "approval", "Approval workflow")

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "approval"}
        )

        assert payload.get("error") != "capability_unavailable"
        assert payload["module_scope_available"] is True
        assert payload["scope"] == "module"

    def test_dependencies_arrive_as_stubs(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Expanding them reproduces the project one edge at a time."""

        _define(context, project_id, "web", "Web")
        _define(context, project_id, "api", "API")
        _relate(context, project_id, "web", "depends_on", target="api")

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "web"}
        )

        assert [d["key"] for d in payload["depends_on"]] == ["api"]
        assert set(payload["depends_on"][0]) == {"key", "name", "summary"}

    def test_dependents_are_reported_too(self, context: tools.ToolContext, project_id: str) -> None:
        """What breaks if I change this is the other half of the question."""

        _define(context, project_id, "web", "Web")
        _define(context, project_id, "api", "API")
        _relate(context, project_id, "web", "depends_on", target="api")

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "api"}
        )

        assert [d["key"] for d in payload["dependents"]] == ["web"]

    def test_satisfied_statements_come_from_edges_not_word_matching(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The difference N17 exists for.

        "These statements mention approval" and "this module satisfies these
        requirements" are different claims, and the old behaviour could only
        make the first.
        """

        knowledge_id = self._seeded(context, project_id)
        _define(context, project_id, "approval", "Approval workflow")
        _relate(context, project_id, "approval", "satisfies", knowledge_id=knowledge_id)

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "approval"}
        )

        assert payload["statements"]
        assert payload["statements"][0]["knowledge_id"] == knowledge_id
        assert payload["statements"][0]["relation"] == "satisfies"
        assert payload["statements"][0]["label"] == "proposed"

    def test_an_unknown_module_names_the_ones_that_exist(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _define(context, project_id, "approval", "Approval workflow")

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "nope"}
        )

        assert payload["error"] == "knowledge_not_found"
        assert "approval" in payload["message"]

    def test_a_project_with_no_modules_still_gets_the_gap_and_its_substitute(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Module scope is unavailable *for this project*, which is a real gap.

        The substitute is offered and labelled, as it always was. What changed
        is that a project which has modelled its modules no longer reaches this
        path, and the way out now exists.
        """

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "approval"}
        )

        assert payload["error"] == "capability_unavailable"
        assert payload["available_now"]["module_scope_available"] is False
        assert "Register the module" in " ".join(payload["next_steps"])

    def test_the_context_says_what_it_did_not_read(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _define(context, project_id, "approval", "Approval workflow")

        payload = dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": "approval"}
        )

        joined = " ".join(payload["guidance"]).lower()
        assert "not implied to be absent" in joined
