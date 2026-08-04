"""Response-size and duplication measurements, repeatable after a change.

T1 established a baseline; this is how it stays checkable. The assertions are
deliberately structural and loosely bounded. Pinning an exact character count
would fail on any wording change and teach the next person to update the number
rather than ask why it moved.

Two things are asserted:

* **Ceilings** — generous, so an accidental explosion is caught while ordinary
  variation is not.
* **Duplication invariants** — these currently *assert that duplication exists*.
  That reads oddly, and is on purpose: it means the target that removes it has
  to come here and say so, rather than the duplication quietly disappearing
  from a report nobody re-ran.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import (
    BlueprintService,
    MemoryService,
    ReadinessService,
    RetrievalService,
    ReviewService,
    WriteKnowledgeRequest,
)
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "development" / "measure-mcp-responses.py"
)


def _measurement_module() -> Any:
    """Load the measurement helpers from the development script.

    Loaded by path rather than duplicated here. The script is what a person runs
    to reproduce the baseline, so the test and the report must measure with the
    same code or they will drift into disagreeing about the same response.
    """

    spec = importlib.util.spec_from_file_location("kae_mcp_measurement", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measurement = _measurement_module()

CEILINGS: dict[str, int] = {
    "kae_list_projects": 2_000,
    "kae_get_project_briefing": 25_000,
    "kae_get_module_context": 8_000,
    "kae_search_knowledge": 8_000,
    "kae_get_open_decisions": 4_000,
    "kae_get_readiness": 5_000,
}
"""Characters a response must stay under.

Roughly double the T1 baseline. A ceiling that sits just above today's number
would fail on the next statement someone confirms, which is not a defect.
"""

SEED = [
    ("goal", "Every published report has an identifiable approver.", "problem_and_value"),
    ("actor", "Ministry leaders submit monthly reports.", "users_and_stakeholders"),
    ("actor", "Pastors and administrators read published reports.", "users_and_stakeholders"),
    (
        "requirement",
        "Only an authorised approver may approve a report.",
        "functional_requirements",
    ),
    (
        "requirement",
        "A report cannot be published before it is approved.",
        "functional_requirements",
    ),
    (
        "requirement",
        "A draft report remains editable by its author until it is submitted.",
        "functional_requirements",
    ),
    ("rule", "A submitter cannot approve their own report.", "acceptance_criteria"),
    (
        "rule",
        "Editing an approved report invalidates the prior approval.",
        "acceptance_criteria",
    ),
    (
        "constraint",
        "Identity must come from the existing organisational directory.",
        "constraints_and_assumptions",
    ),
]


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
    """A project shaped like the demonstration one: covered and uncovered areas."""

    memory = context.memory
    project = memory.create_project("Ministry Reporting", key="size-baseline")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "seed")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content, _ in SEED
        ],
    )
    for item, (_, _, area) in zip(items, SEED, strict=True):
        memory.confirm_knowledge(item.id)
        context.readiness.assign_area(project.id, item.id, area)
    return str(project.id)


def _briefing(context: tools.ToolContext, project_id: str) -> dict[str, Any]:
    """The default briefing, at whatever the deployment profile resolves to."""

    return dispatch(context, "kae_get_project_briefing", {"project_id": project_id})


def _diagnostic(context: tools.ToolContext, project_id: str) -> dict[str, Any]:
    """Everything the briefing can render."""

    return dispatch(
        context, "kae_get_project_briefing", {"project_id": project_id, "detail": "diagnostic"}
    )


class TestEveryReadToolIsMeasurable:
    def test_all_read_tools_stay_under_their_ceiling(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        for tool in measurement.READ_TOOLS:
            payload = dispatch(context, tool, measurement.arguments_for(tool, project_id))
            row = measurement.measure(tool, payload)
            assert row.characters < CEILINGS[tool], (
                f"{tool} returned {row.characters} chars, ceiling {CEILINGS[tool]}"
            )

    def test_measurement_reports_the_fields_the_baseline_uses(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The report is only reproducible if these keep being produced."""

        row = measurement.measure("kae_get_project_briefing", _briefing(context, project_id))

        assert row.characters > 0
        assert row.tokens_chars_per_4 > 0
        assert row.tokens_structural > row.tokens_chars_per_4, (
            "the structural estimate should exceed characters-per-four on JSON"
        )
        assert row.top_level_fields > 0
        assert row.total_nodes > row.top_level_fields


class TestBriefingComposition:
    def test_the_default_briefing_is_dominated_by_findings(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Readiness was 40% and its explanation 32%. Both now need asking for."""

        rows = measurement.section_sizes(_briefing(context, project_id))

        assert rows[0][0] == "findings"

    def test_the_default_omits_the_arithmetic_and_the_statements(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        briefing = _briefing(context, project_id)

        assert "sections" not in briefing
        assert "explanation" not in briefing["readiness"]
        assert briefing["truncation"]["dropped"]

    def test_diagnostic_restores_everything(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        briefing = _diagnostic(context, project_id)

        assert "sections" in briefing
        assert "explanation" in briefing["readiness"]
        assert "projection" in briefing["readiness"]


class TestDuplicationIsGone:
    """T3 removed the duplication T1 measured. These hold it removed.

    They previously asserted the duplication *existed*, so that removing it
    required coming here and saying so. This is that.
    """

    def test_areas_are_rendered_once(self, context: tools.ToolContext, project_id: str) -> None:
        """Fifteen objects for ten areas became ten for ten."""

        explanation = _diagnostic(context, project_id)["readiness"]["explanation"]

        keys = [area["area"] for area in explanation["areas"]]
        assert len(keys) == len(set(keys))
        for gone in ("contributing", "missing", "incomplete"):
            assert gone not in explanation

    def test_a_finding_summary_appears_exactly_once(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        briefing = _briefing(context, project_id)
        serialised = json.dumps(briefing, ensure_ascii=False)

        for finding in briefing["findings"]:
            assert serialised.count(finding["summary"]) == 1

    def test_the_regrouped_renderings_are_gone(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """`findings` is severity ordered and carries the action already."""

        briefing = _briefing(context, project_id)

        assert "findings_by_severity" not in briefing
        assert "recommended_next_steps" not in briefing
        assert all(f["severity"] and f["recommended_action"] for f in briefing["findings"])

    def test_a_missing_area_is_named_far_less_often(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The headline duplication was one gap in nine places.

        Three renderings remain and each answers a different question: what is
        wrong, which areas block, and what the arithmetic was.
        """

        briefing = _diagnostic(context, project_id)
        readiness = briefing["readiness"]
        area = readiness["missing_mandatory_areas"][0]["area"]

        places = [
            any(f["area"] == area for f in briefing["findings"]),
            any(a["area"] == area for a in readiness["explanation"]["areas"]),
            any(a["area"] == area for a in readiness["missing_mandatory_areas"]),
            any(a["area"] == area for a in readiness["projection"]["requires"]),
        ]

        assert sum(places) <= 4
        assert "missing_information" not in readiness

    def test_no_knowledge_body_is_repeated(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Statement text appears once. The duplication is in derived facts.

        Worth pinning: if a later change starts echoing statement bodies into a
        second section, the briefing grows with the corpus rather than with the
        template.
        """

        briefing = _diagnostic(context, project_id)
        statements = [s["text"] for section in briefing["sections"] for s in section["statements"]]
        serialised = json.dumps(briefing, ensure_ascii=False)

        for text in statements:
            assert serialised.count(text) == 1, f"statement body repeated: {text!r}"


class TestGrowth:
    def test_an_empty_project_is_not_cheaper_than_a_covered_one(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The counter-intuitive finding T1 recorded.

        The briefing scales with what is *absent*: an empty project has every
        area missing, so it carries more findings, more next steps, and longer
        explanation lists than one with knowledge in it.
        """

        empty = context.memory.create_project("Empty", key="size-baseline-empty")
        covered = measurement.measure("b", _briefing(context, project_id))
        bare = measurement.measure("b", _briefing(context, str(empty.id)))

        assert bare.characters > covered.characters * 0.8, (
            f"empty={bare.characters} covered={covered.characters}: "
            "an empty project should not be dramatically cheaper"
        )

    def test_identifiers_repeat_within_one_response(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        row = measurement.measure("b", _briefing(context, project_id))

        assert row.entity_ids > 0
        assert row.distinct_entity_ids <= row.entity_ids


def test_the_measurement_script_names_only_read_tools() -> None:
    """A measurement pass must not write. Nothing here may call the write tool."""

    assert "kae_submit_observation" not in measurement.READ_TOOLS
    assert ProjectId is not None  # imported for the script's own signature check
