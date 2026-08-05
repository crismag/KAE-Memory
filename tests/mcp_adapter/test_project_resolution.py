"""Naming a project by key rather than by id (T25.2).

Cross-project isolation was never the gap. Every service call is scoped to one
project and no tool can return knowledge from a project the caller did not
name. What was missing is narrower and, in practice, the thing that actually
goes wrong: an agent that must call `kae_list_projects`, read the response, and
pick a UUID before it can ask anything will often skip the routing and answer
from its own context instead.

That failure is invisible. Nothing leaks, no error is raised, and the answer is
about the wrong project — or about no project at all. A key removes the hop
that provokes it, without adding server state.

Two rules keep the convenience from becoming its own failure:

    a call naming nothing is an error that lists the keys, never a guess
    an id and a key that disagree is an error, never a preference

And resolution is not authorisation. It decides which project a caller named,
never whether they may read it.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.mcp import tools
from kae_memory.mcp.errors import InvalidArgumentError, ProjectNotFoundError
from kae_memory.mcp.response_policy import INTEGRITY_FIELDS
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        embedder_name="deterministic",
    )


@pytest.fixture
def project(context: tools.ToolContext) -> object:
    return context.memory.create_project("Ministry Reporting", key="ministry-reporting")


class TestAKeyIdentifiesAProject:
    def test_a_key_in_project_id_resolves(
        self, context: tools.ToolContext, project: object
    ) -> None:
        """The whole point: no lookup call before the useful call."""

        payload = dispatch(context, "kae_get_readiness", {"project_id": "ministry-reporting"})

        assert "error" not in payload
        assert payload["project_id"] == str(project.id)  # type: ignore[attr-defined]

    def test_a_key_in_project_key_resolves(
        self, context: tools.ToolContext, project: object
    ) -> None:
        payload = dispatch(context, "kae_get_readiness", {"project_key": "ministry-reporting"})

        assert "error" not in payload

    def test_an_id_still_works(self, context: tools.ToolContext, project: object) -> None:
        """Every existing caller keeps working, or this was not worth doing."""

        payload = dispatch(
            context,
            "kae_get_readiness",
            {"project_id": str(project.id)},  # type: ignore[attr-defined]
        )

        assert "error" not in payload

    def test_an_id_and_a_matching_key_are_accepted(
        self, context: tools.ToolContext, project: object
    ) -> None:
        payload = dispatch(
            context,
            "kae_get_readiness",
            {
                "project_id": str(project.id),  # type: ignore[attr-defined]
                "project_key": "ministry-reporting",
            },
        )

        assert "error" not in payload


class TestTheResponseSaysWhatAnswered:
    def test_a_key_resolution_is_echoed(self, context: tools.ToolContext, project: object) -> None:
        """A response may reduce what it says, never what it admits."""

        payload = dispatch(context, "kae_get_readiness", {"project_key": "ministry-reporting"})

        echo = payload["resolved_project"]
        assert echo["project_id"] == str(project.id)  # type: ignore[attr-defined]
        assert echo["project_key"] == "ministry-reporting"
        assert echo["resolved_from"] == "project_key"

    def test_an_id_call_is_not_echoed(self, context: tools.ToolContext, project: object) -> None:
        """A caller who passed the id already knows which project answered."""

        payload = dispatch(
            context,
            "kae_get_readiness",
            {"project_id": str(project.id)},  # type: ignore[attr-defined]
        )

        assert "resolved_project" not in payload

    def test_the_echo_cannot_be_compacted_away(self) -> None:
        """Which project answered is not a detail level's business."""

        assert "resolved_project" in INTEGRITY_FIELDS

    def test_the_echo_survives_an_economy_briefing(
        self, context: tools.ToolContext, project: object
    ) -> None:
        payload = dispatch(
            context,
            "kae_get_project_briefing",
            {"project_key": "ministry-reporting", "profile": "economy"},
        )

        assert payload["resolved_project"]["project_key"] == "ministry-reporting"


class TestAmbiguityIsRefused:
    def test_naming_nothing_is_an_error_that_names_the_alternatives(
        self, context: tools.ToolContext, project: object
    ) -> None:
        """An inferred project is the failure this target exists to prevent."""

        payload = dispatch(context, "kae_get_readiness", {})

        assert payload["error"] == "invalid_argument"
        assert "ministry-reporting" in payload["message"]

    def test_an_id_and_key_that_disagree_are_refused(
        self, context: tools.ToolContext, project: object
    ) -> None:
        """Picking one would answer about a project the caller did not intend."""

        context.memory.create_project("Other", key="other-project")

        payload = dispatch(
            context,
            "kae_get_readiness",
            {
                "project_id": str(project.id),  # type: ignore[attr-defined]
                "project_key": "other-project",
            },
        )

        assert payload["error"] == "invalid_argument"
        assert "other-project" in payload["message"]

    def test_an_unknown_key_lists_what_exists(
        self, context: tools.ToolContext, project: object
    ) -> None:
        payload = dispatch(context, "kae_get_readiness", {"project_key": "no-such-project"})

        assert payload["error"] == "project_not_found"
        assert "ministry-reporting" in payload["message"]

    def test_an_unknown_id_is_still_a_missing_project(self, context: tools.ToolContext) -> None:
        """A UUID-shaped argument is an id, and a wrong id is not a key."""

        payload = dispatch(
            context,
            "kae_get_readiness",
            {"project_id": "00000000-0000-0000-0000-000000000000"},
        )

        assert payload["error"] == "project_not_found"


class TestTheResolverItself:
    def test_a_uuid_is_never_looked_up_as_a_key(
        self, context: tools.ToolContext, project: object
    ) -> None:
        with pytest.raises(ProjectNotFoundError):
            tools.resolve_project(context, "00000000-0000-0000-0000-000000000000")

    def test_neither_argument_raises_invalid_argument(self, context: tools.ToolContext) -> None:
        with pytest.raises(InvalidArgumentError):
            tools.resolve_project(context, "")

    def test_whitespace_is_not_an_identifier(self, context: tools.ToolContext) -> None:
        with pytest.raises(InvalidArgumentError):
            tools.resolve_project(context, "   ", "  ")


class TestEveryProjectScopedToolAcceptsAKey:
    def test_the_schemas_declare_it(self) -> None:
        """A convenience available on some tools is a convenience nobody trusts."""

        for definition in TOOL_DEFINITIONS:
            properties = definition["inputSchema"]["properties"]
            if "project_id" not in properties:
                continue
            assert "project_key" in properties, definition["name"]

    def test_project_id_is_not_schema_required_anywhere(self) -> None:
        """It cannot be, or a key-only call would fail validation before dispatch."""

        for definition in TOOL_DEFINITIONS:
            required = definition["inputSchema"].get("required", [])
            assert "project_id" not in required, definition["name"]

    @pytest.mark.parametrize(
        "tool,extra",
        [
            ("kae_get_project_briefing", {}),
            ("kae_get_readiness", {}),
            ("kae_get_open_decisions", {}),
            ("kae_search_knowledge", {"query": "approval"}),
            ("kae_get_module_context", {"module": "approval"}),
        ],
    )
    def test_reads_resolve_a_key(
        self, context: tools.ToolContext, project: object, tool: str, extra: dict[str, object]
    ) -> None:
        payload = dispatch(context, tool, {"project_key": "ministry-reporting", **extra})

        assert payload.get("error") not in {"invalid_argument", "project_not_found"}

    def test_a_write_resolves_a_key_too(self, context: tools.ToolContext, project: object) -> None:
        """Routing an observation to the wrong project is worse than a bad read."""

        payload = dispatch(
            context,
            "kae_submit_observation",
            {
                "project_key": "ministry-reporting",
                "observation": "Reports close monthly.",
                "idempotency_key": "t25-observation-1",
            },
        )

        assert payload.get("error") is None
        assert payload["resolved_project"]["project_key"] == "ministry-reporting"


class TestResolutionIsNotAuthorisation:
    def test_naming_any_project_by_key_reads_it(self, context: tools.ToolContext) -> None:
        """Focus must never become the thing preventing access to another project.

        Keeping these separate now means later authorisation work sits at the
        project boundary every tool already respects, rather than unpicking a
        convenience that had quietly become a security control.
        """

        context.memory.create_project("First", key="first-project")
        context.memory.create_project("Second", key="second-project")

        first = dispatch(context, "kae_get_readiness", {"project_key": "first-project"})
        second = dispatch(context, "kae_get_readiness", {"project_key": "second-project"})

        assert "error" not in first
        assert "error" not in second
        assert first["project_id"] != second["project_id"]
