"""The capability registry, enforced (N6, ADR-0023).

The twelve-capability gap N1 measured did not happen because anyone decided
HTTP should lack search. It happened because nothing noticed, for five phases,
that each new target landed on one adapter. Every planning document said the two
surfaces were peers; nothing checked.

So this file checks, in both directions:

    a capability the registry says is on both adapters is on both;
    a tool or route that is *not* in the registry fails the suite.

The second is the half that prevents recurrence. A register nobody has to
remember to update is a register that describes the past — the reverse check is
what makes forgetting it impossible rather than merely discouraged.

Parity here is about *reachability*, not payloads. Whether two adapters return
the same behaviour is asserted in `test_pipeline_contract.py`; this asserts they
offer the same things to ask.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.capabilities import (
    REGISTRY,
    Capability,
    Exposure,
    by_key,
    declared_http_routes,
    declared_mcp_tools,
)
from kae_memory.mcp.server import TOOL_DEFINITIONS

UNREGISTERED_PATHS = frozenset({"/health"})
"""Paths outside the capability model.

`/health` reports whether the process and its database are alive. It is not a
capability of the product, and registering it would mean asserting an adapter
exposure for something that exists to answer when the adapters do not.
"""


@pytest.fixture
def http_routes(factory: sessionmaker[Session]) -> Iterator[frozenset[str]]:
    """The routes the application actually declares.

    Read from the OpenAPI document rather than from a list kept beside it,
    because a list beside it is the thing that drifts.
    """

    application = create_app(factory, auth=AuthPolicy())
    spec = application.openapi()["paths"]
    yield frozenset(
        f"{method.upper()} {path}"
        for path, operations in spec.items()
        for method in operations
        if path.startswith("/v1")
    )


def _mcp_tools() -> frozenset[str]:
    return frozenset(definition["name"] for definition in TOOL_DEFINITIONS)


class TestTheRegistryDescribesReality:
    @pytest.mark.parametrize("capability", REGISTRY, ids=lambda c: c.key)
    def test_every_declared_mcp_tool_exists(self, capability: Capability) -> None:
        missing = set(capability.mcp) - _mcp_tools()

        assert not missing, f"{capability.key} names MCP tools that do not exist: {sorted(missing)}"

    @pytest.mark.parametrize("capability", REGISTRY, ids=lambda c: c.key)
    def test_every_declared_http_route_exists(
        self, capability: Capability, http_routes: frozenset[str]
    ) -> None:
        missing = set(capability.http) - http_routes

        assert not missing, f"{capability.key} names routes that do not exist: {sorted(missing)}"


class TestParityIsRequiredWhereDeclared:
    @pytest.mark.parametrize(
        "capability",
        [c for c in REGISTRY if c.exposure is Exposure.BOTH],
        ids=lambda c: c.key,
    )
    def test_a_both_capability_is_on_both_adapters(
        self, capability: Capability, http_routes: frozenset[str]
    ) -> None:
        """The assertion the whole file exists for."""

        assert capability.mcp, f"{capability.key} is required on both and names no MCP tool"
        assert capability.http, f"{capability.key} is required on both and names no HTTP route"

    @pytest.mark.parametrize(
        "capability",
        [c for c in REGISTRY if c.exposure is Exposure.AGENT_ONLY],
        ids=lambda c: c.key,
    )
    def test_an_agent_only_capability_is_not_on_http(self, capability: Capability) -> None:
        assert capability.mcp
        assert not capability.http, f"{capability.key} is agent-only and names an HTTP route"

    @pytest.mark.parametrize(
        "capability",
        [c for c in REGISTRY if c.exposure is Exposure.PRODUCT_ONLY],
        ids=lambda c: c.key,
    )
    def test_a_product_only_capability_is_not_on_mcp(self, capability: Capability) -> None:
        assert capability.http
        assert not capability.mcp, f"{capability.key} is product-only and names an MCP tool"

    @pytest.mark.parametrize(
        "capability",
        [c for c in REGISTRY if c.exposure is Exposure.INTERNAL],
        ids=lambda c: c.key,
    )
    def test_an_internal_capability_is_on_neither(self, capability: Capability) -> None:
        assert not capability.mcp
        assert not capability.http


class TestNothingEscapesTheRegistry:
    """The half that prevents the gap from happening again."""

    def test_every_mcp_tool_is_registered(self) -> None:
        """A tool added without a registry entry fails here, not in five phases."""

        unregistered = _mcp_tools() - declared_mcp_tools()

        assert not unregistered, (
            f"MCP tools with no capability entry: {sorted(unregistered)}. Add them to "
            f"kae_memory.capabilities with an exposure and, if asymmetric, a reason."
        )

    def test_every_http_route_is_registered(self, http_routes: frozenset[str]) -> None:
        """A route added without a registry entry fails here too."""

        unregistered = {
            route
            for route in http_routes - declared_http_routes()
            if route.split(" ", 1)[1] not in UNREGISTERED_PATHS
        }

        assert not unregistered, (
            f"HTTP routes with no capability entry: {sorted(unregistered)}. Add them to "
            f"kae_memory.capabilities with an exposure and, if asymmetric, a reason."
        )


class TestAnExceptionMustBeJustified:
    def test_every_asymmetric_capability_carries_a_reason(self) -> None:
        """An exception is a decision; an absence is a defect.

        Keeping both in the same file in the same shape is what stops the second
        being filed as the first, and a reason is what separates them.
        """

        for capability in REGISTRY:
            if capability.exposure is Exposure.BOTH:
                continue
            assert capability.reason, capability.key

    def test_the_reason_is_a_sentence_not_a_label(self) -> None:
        """ "internal" restates the field. It does not say why."""

        for capability in REGISTRY:
            if capability.exposure is Exposure.BOTH:
                continue
            assert len(capability.reason) > 40, capability.key

    def test_declaring_an_exception_without_a_reason_raises(self) -> None:
        with pytest.raises(ValueError):
            Capability(key="whatever", summary="", exposure=Exposure.INTERNAL)


class TestTheRegistryIsWellFormed:
    def test_keys_are_unique(self) -> None:
        keys = [capability.key for capability in REGISTRY]

        assert len(keys) == len(set(keys))

    def test_no_tool_is_claimed_by_two_capabilities(self) -> None:
        """A tool answering to two capabilities makes the register ambiguous."""

        seen: dict[str, str] = {}
        for capability in REGISTRY:
            for tool in capability.mcp:
                if tool in seen and capability.key != seen[tool]:
                    # The briefing legitimately serves two: it answers both
                    # "what is known" and "what is unresolved". Anything else
                    # is a boundary that has not been drawn.
                    assert tool == "kae_get_project_briefing", f"{tool} claimed twice"
                seen.setdefault(tool, capability.key)

    def test_no_route_is_claimed_by_two_capabilities(self) -> None:
        seen: dict[str, str] = {}
        for capability in REGISTRY:
            for route in capability.http:
                assert route not in seen, f"{route} claimed by {seen[route]} and {capability.key}"
                seen[route] = capability.key

    def test_lookup_by_key_works_and_fails_loudly(self) -> None:
        assert by_key("knowledge.search").exposure is Exposure.BOTH

        with pytest.raises(KeyError):
            by_key("not.a.capability")


class TestTheGapN1MeasuredIsClosed:
    def test_the_five_services_studio_could_not_reach_are_on_http(
        self, http_routes: frozenset[str]
    ) -> None:
        """Retrieval, ingestion, assembly, clarification, classification.

        N1 found all five reachable only through MCP. This is the assertion that
        says so in code rather than in a document that ages.
        """

        for key in (
            "knowledge.search",
            "document.ingest",
            "context.assemble",
            "clarification.open",
            "clarification.answer",
            "observation.classifications",
            "operational.read",
        ):
            capability = by_key(key)
            assert capability.http, key
            assert set(capability.http) <= http_routes, key

    def test_review_is_no_longer_one_sided_on_http(self, http_routes: frozenset[str]) -> None:
        """HTTP had confirm and neither reject nor correct."""

        for key in ("knowledge.confirm", "knowledge.reject", "knowledge.correct"):
            assert set(by_key(key).http) <= http_routes, key
