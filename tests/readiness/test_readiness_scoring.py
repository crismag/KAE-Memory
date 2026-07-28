"""Readiness scoring: deterministic, explainable, and not inflatable.

These tests exercise the calculator directly, without a database. The property
that matters most is the last one: generating more unconfirmed candidates must
never raise the score.
"""

from datetime import UTC, datetime
from uuid import uuid4

from kae_memory.application.readiness_service import derive_status, evaluate_area, score_areas
from kae_memory.domain.identifiers import AgentId, ExecutionId, KnowledgeItemId, ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, KnowledgeVersion, Provenance
from kae_memory.domain.readiness import (
    SOFTWARE_TEMPLATE,
    AreaDefinition,
    AreaState,
    ReadinessStatus,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
PROJECT = ProjectId("11111111-1111-1111-1111-111111111111")


def item(kind: str, lifecycle: LifecycleState = LifecycleState.PROPOSED) -> KnowledgeItem:
    """Return a one-version knowledge item in the requested lifecycle state."""

    return KnowledgeItem(
        id=KnowledgeItemId(str(uuid4())),
        project_id=PROJECT,
        kind=kind,
        versions=(
            KnowledgeVersion(
                number=1,
                content=f"A {kind} claim.",
                provenance=Provenance(
                    source="test",
                    actor_id=AgentId("requirements"),
                    execution_id=ExecutionId(str(uuid4())),
                    recorded_at=NOW,
                ),
                created_at=NOW,
            ),
        ),
        lifecycle=lifecycle,
    )


REQUIREMENTS = AreaDefinition(
    key="functional_requirements",
    name="Functional requirements",
    weight=2.0,
    kinds=(KnowledgeKind.REQUIREMENT,),
    minimum_confirmed=3,
)


def test_no_knowledge_leaves_an_area_missing() -> None:
    result = evaluate_area(REQUIREMENTS, [], frozenset())

    assert result.state is AreaState.MISSING
    assert result.credit == 0.0


def test_proposed_knowledge_only_reaches_partial() -> None:
    """Proposed extraction steers the next question; it never completes an area."""

    proposed = [item("requirement", LifecycleState.PROPOSED) for _ in range(9)]

    result = evaluate_area(REQUIREMENTS, proposed, frozenset())

    assert result.state is AreaState.PARTIAL
    assert result.confirmed_count == 0
    assert result.proposed_count == 9


def test_confirmed_knowledge_below_the_threshold_is_partial() -> None:
    confirmed = [item("requirement", LifecycleState.VALIDATED) for _ in range(2)]

    result = evaluate_area(REQUIREMENTS, confirmed, frozenset())

    assert result.state is AreaState.PARTIAL
    assert result.confirmed_count == 2


def test_meeting_the_configured_minimum_is_sufficient() -> None:
    confirmed = [item("requirement", LifecycleState.VALIDATED) for _ in range(3)]

    result = evaluate_area(REQUIREMENTS, confirmed, frozenset())

    assert result.state is AreaState.SUFFICIENT
    assert result.credit == 1.0


def test_rejected_and_superseded_knowledge_contributes_nothing() -> None:
    dead = [
        item("requirement", LifecycleState.REJECTED),
        item("requirement", LifecycleState.SUPERSEDED),
    ]

    result = evaluate_area(REQUIREMENTS, dead, frozenset())

    assert result.state is AreaState.MISSING


def test_knowledge_of_a_disallowed_kind_does_not_count() -> None:
    """The area's configured kinds are a guard, not a suggestion."""

    misfiled = [item("actor", LifecycleState.VALIDATED) for _ in range(5)]

    result = evaluate_area(REQUIREMENTS, misfiled, frozenset())

    assert result.state is AreaState.MISSING


def test_not_applicable_areas_leave_the_denominator() -> None:
    """Excluding an area neither rewards nor punishes the project."""

    covered = evaluate_area(
        REQUIREMENTS, [item("requirement", LifecycleState.VALIDATED) for _ in range(3)], frozenset()
    )
    excluded = evaluate_area(REQUIREMENTS, [], frozenset(), not_applicable=True)

    assert score_areas([covered]) == 100.0
    assert score_areas([covered, excluded]) == 100.0


def test_score_is_weighted_by_area() -> None:
    heavy = evaluate_area(
        REQUIREMENTS, [item("requirement", LifecycleState.VALIDATED) for _ in range(3)], frozenset()
    )
    light = evaluate_area(
        AreaDefinition("users", "Users", 1.0, (KnowledgeKind.ACTOR,)), [], frozenset()
    )

    # 2.0 of 3.0 total weight is fully covered.
    assert round(score_areas([heavy, light]), 4) == round(200.0 / 3.0, 4)


def test_generating_more_candidates_cannot_raise_the_score() -> None:
    """The single most important property of this model.

    A system that raises its own readiness by talking more is worse than one with
    no score at all.
    """

    one_proposal = evaluate_area(REQUIREMENTS, [item("requirement")], frozenset())
    many_proposals = evaluate_area(
        REQUIREMENTS, [item("requirement") for _ in range(50)], frozenset()
    )

    assert score_areas([one_proposal]) == score_areas([many_proposals])


def test_status_is_not_started_before_any_knowledge_exists() -> None:
    areas = [evaluate_area(area, [], frozenset()) for area in SOFTWARE_TEMPLATE.areas]

    assert derive_status(areas, 0.0, implementation_eligible=False, blocked=False) is (
        ReadinessStatus.NOT_STARTED
    )


def test_blocked_outranks_blueprint_ready() -> None:
    """Coverage would permit generation, but something unresolved stands."""

    areas = [
        evaluate_area(
            REQUIREMENTS,
            [item("requirement", LifecycleState.VALIDATED) for _ in range(3)],
            frozenset(),
        )
    ]

    assert derive_status(areas, 100.0, implementation_eligible=False, blocked=True) is (
        ReadinessStatus.BLOCKED
    )


def test_partial_coverage_below_the_threshold_is_discovering() -> None:
    areas = [evaluate_area(REQUIREMENTS, [item("requirement")], frozenset())]

    assert derive_status(areas, 25.0, implementation_eligible=False, blocked=False) is (
        ReadinessStatus.DISCOVERING
    )


def test_the_shipped_template_defines_every_area_once() -> None:
    keys = [area.key for area in SOFTWARE_TEMPLATE.areas]

    assert len(keys) == len(set(keys))
    assert len(keys) == 10
    assert NOW.tzinfo is not None


def test_a_knowledge_item_carries_its_provenance() -> None:
    """Guards the factory these tests depend on."""

    built = item("requirement", LifecycleState.VALIDATED)

    assert isinstance(built, KnowledgeItem)
    assert isinstance(built.current_version, KnowledgeVersion)
    assert isinstance(built.current_version.provenance, Provenance)
