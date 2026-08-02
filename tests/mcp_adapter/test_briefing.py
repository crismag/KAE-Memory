"""What the project briefing must report, and what it must never invent.

The defect these cover: the briefing filtered its findings down to open
questions, which hid every ``critical`` one — the discovery areas with no
confirmed knowledge at all — behind the least urgent thing the reviewer had to
say. A reader saw "2 open questions, major" on a project with three critical
gaps.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.mcp import tools

MINISTRY_KNOWLEDGE = [
    (
        "goal",
        "Every published report has an identifiable approver and approval time.",
        "problem_and_value",
    ),
    ("actor", "Ministry leaders submit monthly reports.", "users_and_stakeholders"),
    (
        "requirement",
        "Only an authorised approver may approve a report.",
        "functional_requirements",
    ),
    (
        "constraint",
        "Identity must come from the existing organisational directory.",
        "constraints_and_assumptions",
    ),
    ("rule", "A submitter cannot approve their own report.", "acceptance_criteria"),
]
"""Five covered areas, leaving scope, quality attributes, and domain model empty.

Each item carries its area because a kind alone cannot resolve one — "functional
requirements" and "quality attributes" are both ``requirement``, so coverage
needs an explicit link.
"""


@pytest.fixture
def briefing_context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
    )


@pytest.fixture
def briefed(briefing_context: tools.ToolContext) -> dict:
    """A project with confirmed knowledge, one open question, and empty areas."""

    memory = briefing_context.memory
    project = memory.create_project("Ministry Reporting", key="briefing-ministry")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "briefing-seed")
    # One write: a run reaches a terminal state after it produces its knowledge.
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content, _ in [
                *MINISTRY_KNOWLEDGE,
                ("unknown", "Which role holds approval authority?", None),
            ]
        ],
    )
    # The open question stays proposed on purpose: an unresolved question is a
    # candidate, and candidates must not count as knowledge anywhere below.
    for item, (_, _, area) in zip(items, MINISTRY_KNOWLEDGE, strict=False):
        memory.confirm_knowledge(item.id)
        briefing_context.readiness.assign_area(project.id, item.id, area)

    return tools.kae_get_project_briefing(briefing_context, str(project.id))


class TestFindings:
    def test_critical_findings_are_not_filtered_out(self, briefed: dict) -> None:
        """The regression. Areas with no confirmed knowledge are the worst news."""

        criticals = briefed["findings_by_severity"]["critical"]

        assert criticals, "a project with empty mandatory areas has critical findings"
        assert any("no confirmed knowledge" in summary for summary in criticals)

    def test_every_finding_reaches_the_response(self, briefed: dict) -> None:
        """Previously only three of seven finding kinds survived the filter."""

        kinds = {finding["kind"] for finding in briefed["findings"]}

        assert "missing_area" in kinds, "missing areas were the filtered-out kind"
        assert "open_question" in kinds

    def test_findings_are_grouped_by_severity(self, briefed: dict) -> None:
        grouped = briefed["findings_by_severity"]

        assert set(grouped) == {"critical", "major", "minor"}
        total = sum(len(items) for items in grouped.values())
        assert total == len(briefed["findings"])

    def test_a_finding_carries_its_recommended_action(self, briefed: dict) -> None:
        """The review service already computes one; the briefing used to drop it."""

        assert all(finding["recommended_action"] for finding in briefed["findings"])

    def test_next_steps_lead_with_the_most_severe(self, briefed: dict) -> None:
        steps = briefed["recommended_next_steps"]

        assert steps
        assert steps[0]["severity"] == "critical"
        order = ["critical", "major", "minor"]
        positions = [order.index(step["severity"]) for step in steps]
        assert positions == sorted(positions)


class TestReadinessExplanation:
    def test_the_explanation_reproduces_the_percentage(self, briefed: dict) -> None:
        """If the shown arithmetic disagrees with the score, one of them is lying."""

        readiness = briefed["readiness"]
        explanation = readiness["explanation"]

        computed = explanation["earned_weight"] / explanation["applicable_weight"] * 100
        assert round(computed) == readiness["percentage"]

    def test_areas_are_split_into_contributing_and_missing(self, briefed: dict) -> None:
        explanation = briefed["readiness"]["explanation"]

        assert explanation["contributing"], "some areas were covered by the seed"
        assert explanation["missing"], "some areas were deliberately left empty"
        contributing = {area["area"] for area in explanation["contributing"]}
        missing = {area["area"] for area in explanation["missing"]}
        assert contributing.isdisjoint(missing)

    def test_a_missing_area_states_what_would_close_it(self, briefed: dict) -> None:
        """ "Missing" without a threshold is a complaint, not an instruction."""

        missing = briefed["readiness"]["explanation"]["missing"]

        assert all(area["confirmed_needed"] >= 1 for area in missing)
        assert all(area["confirmed_statements"] == 0 for area in missing)

    def test_a_partial_area_reports_the_weight_it_still_owes(self, briefed: dict) -> None:
        """Half credit on a heavy area is a bigger gap than a light empty one.

        Reporting only earned weight hides it: a partial area sits under
        ``contributing`` and looks done.
        """

        explanation = briefed["readiness"]["explanation"]
        partial = [a for a in explanation["contributing"] if a["state"] == "partial"]

        assert partial, "the seed leaves functional requirements short of its minimum"
        assert all(0 < a["credit"] < 1.0 for a in partial)
        assert all(a["weight_outstanding"] > 0 for a in partial)
        assert {a["area"] for a in partial} <= {a["area"] for a in explanation["incomplete"]}

    def test_projection_is_arithmetic_not_prediction(self, briefed: dict) -> None:
        """Resolving the mandatory areas must land exactly on the weighted score.

        Re-derived here from the published weights rather than by calling the
        same helper, so a change to either side has to be deliberate.
        """

        readiness = briefed["readiness"]
        projection = readiness["projection"]
        explanation = readiness["explanation"]

        # Every mandatory area still short of full credit, partial ones included.
        outstanding = sum(
            area["weight_outstanding"] for area in explanation["incomplete"] if area["mandatory"]
        )
        expected = (
            (explanation["earned_weight"] + outstanding) / explanation["applicable_weight"] * 100
        )
        assert projection["percentage_if_mandatory_areas_resolved"] == round(expected)
        assert projection["percentage_if_mandatory_areas_resolved"] > readiness["percentage"]

    def test_projection_names_the_areas_it_assumes_resolved(self, briefed: dict) -> None:
        required = {area["area"] for area in briefed["readiness"]["projection"]["requires"]}

        assert required == set(briefed["readiness"]["missing_mandatory_areas"])


class TestKnowledgeHealth:
    def test_counts_come_from_statements_not_the_revision_counter(self, briefed: dict) -> None:
        """The knowledge revision is a version number, not a quantity.

        Reading it as a statement count is an easy mistake to make and an
        authoritative-looking one to publish.
        """

        health = briefed["knowledge_health"]

        assert health["confirmed_statements"] == briefed["statement_count"]
        assert health["confirmed_statements"] != briefed["knowledge_revision"]

    def test_labels_partition_the_confirmed_statements(self, briefed: dict) -> None:
        """Blurring these would undo the labelling the blueprint computes.

        Which label a statement gets is decided by provenance, so the fixture
        does not pin one; what must hold is that the counts partition the
        statements exactly and agree with the sections they came from.
        """

        health = briefed["knowledge_health"]
        statements = [s for section in briefed["sections"] for s in section["statements"]]

        assert (
            health["grounded"] + health["derived"] + health["assumptions"]
            == health["confirmed_statements"]
        )
        for label, key in (("grounded", "grounded"), ("assumption", "assumptions")):
            assert health[key] == sum(1 for s in statements if s["label"] == label)

    def test_unconfirmed_knowledge_is_not_counted_as_known(self, briefed: dict) -> None:
        """A proposed item is a candidate, and candidates are not knowledge."""

        health = briefed["knowledge_health"]

        assert health["awaiting_review"] >= 1
        assert health["open_questions"] >= 1

    def test_coverage_agrees_with_readiness(self, briefed: dict) -> None:
        assert (
            briefed["knowledge_health"]["coverage_percentage"]
            == (briefed["readiness"]["percentage"])
        )


class TestGroundingAndTraceability:
    def test_every_statement_keeps_its_source_and_label(self, briefed: dict) -> None:
        """A summary that loses provenance is no longer auditable."""

        statements = [s for section in briefed["sections"] for s in section["statements"]]

        assert statements
        assert all(s["knowledge_id"] for s in statements)
        assert all(s["label"] in {"grounded", "derived", "assumption"} for s in statements)

    def test_the_briefing_asserts_no_prose_nobody_confirmed(self, briefed: dict) -> None:
        """No purpose line, no narrative, no summary sentence.

        Every other field here is counted or computed from confirmed knowledge.
        A generated purpose statement would be the one claim in the response
        that no human ever made and no knowledge_id can back.
        """

        assert "purpose" not in briefed
        assert "narrative" not in briefed
        assert "summary" not in briefed

    def test_human_labels_ship_alongside_machine_values(self, briefed: dict) -> None:
        """Renaming the keys would break every existing consumer."""

        readiness = briefed["readiness"]

        assert readiness["status"] == "discovering"
        assert readiness["status_label"] == "In discovery"
        assert readiness["ready_for"]["Implementation"] is False
        assert readiness["implementation_eligible"] is False
        # Machine keys survive unchanged; the readable area names sit beside them.
        assert readiness["missing_mandatory_areas"] == [
            a["area"] for a in readiness["missing_information"]
        ]
        assert "Scope and boundaries" in [a["name"] for a in readiness["missing_information"]]
