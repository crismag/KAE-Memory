"""Token reduction, verified against what it must not remove (T5).

T1 measured the surface, T2-T4 reduced it. T5 is the only one of the four that
can fail in a way the others cannot detect: a reduction that works.

Size is easy to check and, on its own, worthless. A response can be made
arbitrarily small by deleting the fields that carry meaning, and every
size-only assertion would go green. So each test here pairs a reduction with
the thing the reduction is not allowed to cost:

    economy is smaller than detailed          — and still says whether a
                                                statement is confirmed
    the briefing dropped fields               — and said which, and how to
                                                get them back
    prose was compacted                       — and the integrity statements
                                                shortened rather than vanished

The specific loss being defended against is a caller reading a proposed
statement as an established one because compaction removed `state`. That
caller does not see an error; it sees a smaller, apparently complete response,
and implements a requirement nobody approved.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.workspace import SessionType
from kae_memory.mcp import response_policy, tools
from kae_memory.mcp.response_policy import (
    INTEGRITY_FIELDS,
    DetailLevel,
    ResponseProfile,
)
from kae_memory.mcp.server import TOOL_FIELD_LEVELS, dispatch

PROFILES = ("economy", "regular", "detailed")

READ_CALLS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("kae_get_project_briefing", {}),
    ("kae_get_readiness", {}),
    ("kae_get_module_context", {"module": "approval workflow"}),
    ("kae_search_knowledge", {"query": "approval"}),
    ("kae_get_open_decisions", {}),
    ("kae_list_projects", {}),
)
"""The read surface, with arguments that match the seeded corpus.

Measuring a query that matches nothing would understate every response that
carries results, and would make a reduction look better than it is.
"""


def _seed(context: tools.ToolContext) -> str:
    """A project with confirmed knowledge, candidates, and open questions.

    All three states have to be present. A project holding only confirmed
    statements cannot show whether compaction preserves the confirmed/proposed
    distinction, because there is nothing for it to blur.
    """

    project = context.memory.create_project("Reduction", key="t5-reduction")
    session = context.memory.open_session(project.id, SessionType.DISCOVERY)
    message = context.memory.record_message(
        project.id, session.id, "A report must be approved before it is published."
    ).message
    run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, "t5-1", session.id)
    written = context.memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                KnowledgeKind.REQUIREMENT.value,
                f"Approval requirement {index}: a report is approved before publication.",
                "seed",
                message.id,
            )
            for index in range(6)
        ]
        + [
            WriteKnowledgeRequest(
                KnowledgeKind.UNKNOWN.value,
                f"Who approves a report in case {index}?",
                "seed",
                message.id,
            )
            for index in range(4)
        ],
    )
    for item in written[:4]:
        context.memory.confirm_knowledge(item.id)
    return str(project.id)


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
def project_id(context: tools.ToolContext) -> str:
    return _seed(context)


def _call(
    context: tools.ToolContext, tool: str, project_id: str, profile: str, **extra: Any
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"profile": profile}
    if tool != "kae_list_projects":
        arguments["project_id"] = project_id
    arguments.update(extra)
    return dispatch(context, tool, arguments)


def _size(payload: Any) -> int:
    return len(json.dumps(payload, ensure_ascii=False))


def _fields(payload: Any, prefix: str = "") -> set[str]:
    """Every dotted field path in a payload, including inside list elements."""

    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}{key}"
            found.add(path)
            found |= _fields(value, f"{path}.")
    elif isinstance(payload, list):
        for element in payload:
            found |= _fields(element, prefix)
    return found


class TestTheReductionIsReal:
    """The easy half. Necessary, and not sufficient on its own."""

    @pytest.mark.parametrize("tool", [name for name, _ in READ_CALLS if name in TOOL_FIELD_LEVELS])
    def test_economy_is_smaller_than_detailed(
        self, context: tools.ToolContext, project_id: str, tool: str
    ) -> None:
        extra = dict(next(args for name, args in READ_CALLS if name == tool))

        economy = _call(context, tool, project_id, "economy", **extra)
        detailed = _call(context, tool, project_id, "detailed", **extra)

        assert _size(economy) < _size(detailed), tool

    def test_the_briefing_reduction_is_substantial(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The briefing was 40% of the whole surface at baseline (T1).

        A few percent would not have been worth the risk of compacting it, so
        the threshold is set where the work stops paying for itself.
        """

        economy = _call(context, "kae_get_project_briefing", project_id, "economy")
        detailed = _call(context, "kae_get_project_briefing", project_id, "detailed")

        saved = 1 - _size(economy) / _size(detailed)
        assert saved >= 0.25, f"only {saved:.0%} saved"

    def test_a_page_is_smaller_than_the_collection(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """T4's pagination is part of the reduction, not separate from it."""

        page = dispatch(context, "kae_get_open_decisions", {"project_id": project_id, "limit": 2})
        whole = dispatch(
            context, "kae_get_open_decisions", {"project_id": project_id, "limit": 100}
        )

        assert _size(page) < _size(whole)
        assert page["total"] == whole["total"], "reducing the page must not reduce the count"


class TestNothingEssentialIsLost:
    """The half that makes the reduction trustworthy rather than merely small."""

    @pytest.mark.parametrize("tool,extra", READ_CALLS)
    def test_every_integrity_field_survives_economy(
        self, context: tools.ToolContext, project_id: str, tool: str, extra: dict[str, Any]
    ) -> None:
        """A field present at `detailed` and registered as integrity must remain.

        This is the assertion that separates compaction from data loss. It is
        computed by comparing the two responses rather than by listing expected
        fields, so a tool that grows a new integrity field is covered the day
        it is added.
        """

        detailed = _call(context, tool, project_id, "detailed", **extra)
        economy = _call(context, tool, project_id, "economy", **extra)

        present = {path for path in _fields(detailed) if path.split(".")[-1] in INTEGRITY_FIELDS}
        surviving = _fields(economy)
        # A whole section may be withheld, and then its contents go with it —
        # `readiness.explanation` is dropped entire, so the `state` inside it
        # is not a stripped field but part of a reported absence. What the
        # registry forbids is a section that stays and loses its integrity
        # fields, because that response looks complete and is not.
        withheld = tuple(economy.get("truncation", {}).get("dropped", ()))

        missing = sorted(
            path
            for path in present
            if path not in surviving and not any(path.startswith(f"{d}.") for d in withheld)
        )
        assert not missing, f"{tool} lost integrity fields at economy: {missing}"

    def test_a_statement_still_declares_whether_it_is_confirmed(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The specific loss this target exists to prevent.

        A caller that cannot tell confirmed from proposed will implement
        whichever it reads first, and a smaller response gives it no reason to
        doubt what it read.
        """

        economy = _call(context, "kae_search_knowledge", project_id, "economy", query="approval")

        assert economy["results"], "the corpus must produce hits or this proves nothing"
        for hit in economy["results"]:
            assert hit.get("lifecycle") or hit.get("state"), hit

    def test_the_confirmed_count_is_never_compacted_away(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """How much is actually known is the briefing's whole point."""

        economy = _call(context, "kae_get_project_briefing", project_id, "economy")

        assert "statement_count" in economy
        assert economy["readiness"]["implementation_eligible"] is not None

    def test_search_still_admits_it_is_not_semantic(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The hash-derived embedder must not become invisible under economy."""

        economy = _call(context, "kae_search_knowledge", project_id, "economy", query="approval")

        assert economy["semantic_search_available"] is False
        assert economy["search_mode"]


class TestWhatWasDroppedIsRecoverable:
    """A response that omits silently is worse than a large one."""

    def test_the_briefing_says_what_it_dropped(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        economy = _call(context, "kae_get_project_briefing", project_id, "economy")

        truncation = economy["truncation"]
        assert truncation["applied"] is True
        assert truncation["dropped"], "something was dropped or the reduction did nothing"
        assert "diagnostic" in truncation["retrieve_with"]

    def test_asking_again_at_diagnostic_returns_them(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The recovery instruction has to actually work."""

        economy = _call(context, "kae_get_project_briefing", project_id, "economy")
        dropped = set(economy["truncation"]["dropped"])

        detailed = _fields(_call(context, "kae_get_project_briefing", project_id, "detailed"))

        assert dropped <= detailed, sorted(dropped - detailed)

    def test_every_response_says_what_policy_produced_it(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A custom profile is irreproducible unless the response resolves it."""

        for tool, extra in READ_CALLS:
            if tool not in TOOL_FIELD_LEVELS:
                continue
            payload = _call(context, tool, project_id, "economy", **dict(extra))
            assert payload["response_policy"]["profile"] == "economy", tool
            assert payload["response_policy"]["detail"], tool


class TestProseShortensRatherThanVanishing:
    def test_registered_integrity_statements_keep_their_meaning(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Economy sets prose to `none`; integrity prose still has to say something."""

        economy = _call(context, "kae_search_knowledge", project_id, "economy", query="nothing")

        for warning in economy.get("warnings", []):
            assert warning.strip(), "an empty warning is a removed warning"

    def test_no_short_form_is_longer_than_what_it_replaces(self) -> None:
        for long_form, short in response_policy.SHORT_FORMS.items():
            assert len(short) < len(long_form), short

    def test_a_short_form_still_carries_the_negation(self) -> None:
        """Shortening must not turn "not confirmed" into silence."""

        negations = ("not", "no ", "only")
        for short in response_policy.SHORT_FORMS.values():
            assert any(word in short.lower() for word in negations), short


class TestTheGuaranteeCannotBeQuietlyWeakened:
    def test_integrity_fields_are_excluded_from_every_field_map(self) -> None:
        """A field map entry naming an integrity field would be dead — or worse.

        Dead if `_prune` keeps honouring the registry, and a silent removal the
        day someone reorders those two checks. Neither is a state to leave in
        the codebase.
        """

        for tool, field_levels in TOOL_FIELD_LEVELS.items():
            for path in field_levels:
                leaf = path.split(".")[-1]
                assert leaf not in INTEGRITY_FIELDS, f"{tool}: {path}"

    def test_every_field_map_path_reaches_a_real_field(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A path that matches nothing is a reduction that silently does not happen.

        Two entries were written as `questions[].knowledge_ids`. The pruner
        builds dotted paths, so neither ever matched, and both fields shipped
        at every detail level while the map said they did not. Nothing failed;
        the compaction simply was not there. Checking the paths against real
        payloads is what turns the map into something the code has to honour.
        """

        readiness = ReadinessService(factory)
        readiness.install_template()
        memory = MemoryService(factory)
        context = tools.ToolContext(
            memory=memory,
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
            retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
            clarification=ClarificationService(factory, memory),
            embedder_name="deterministic",
        )
        seeded = _seed(context)

        payloads = {
            "kae_get_project_briefing": _call(
                context, "kae_get_project_briefing", seeded, "detailed"
            ),
            "kae_get_readiness": _call(context, "kae_get_readiness", seeded, "detailed"),
            "kae_get_clarifications": _call(context, "kae_get_clarifications", seeded, "detailed"),
        }
        for tool, payload in payloads.items():
            reachable = _fields(payload)
            for path in TOOL_FIELD_LEVELS[tool]:
                assert path in reachable, f"{tool}: {path} matches no field"

    def test_the_summary_level_is_what_economy_resolves_to(self) -> None:
        assert response_policy.PROFILES[ResponseProfile.ECONOMY].detail is DetailLevel.SUMMARY
        assert response_policy.PROFILES[ResponseProfile.DETAILED].detail is DetailLevel.DIAGNOSTIC
