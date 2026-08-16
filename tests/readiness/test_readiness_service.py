"""Readiness over real persisted state, against CockroachDB.

Covers the four things ADR-0012 recorded as missing: relationship wiring,
blockers, the project knowledge revision, and area assignment.
"""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.readiness import (
    AreaState,
    BlockerSeverity,
    BlockerStatus,
    ReadinessStatus,
)

# One confirmed item per area, except functional_requirements, which the shipped
# template requires three of.
#
# `problem_and_value` appears twice because it is the one divided area: it is
# sufficient only when a project can state both what hurts and why solving it is
# worth doing (`RUN-D14`). One statement there used to complete it.
FULL_COVERAGE: tuple[tuple[str, str], ...] = (
    ("problem_and_value", "goal"),
    ("problem_and_value", "goal"),
    ("users_and_stakeholders", "actor"),
    ("scope_and_boundaries", "goal"),
    ("functional_requirements", "requirement"),
    ("functional_requirements", "requirement"),
    ("functional_requirements", "requirement"),
    ("quality_attributes", "constraint"),
    ("domain_model_and_data", "rule"),
    ("interfaces_and_integrations", "decision"),
    ("constraints_and_assumptions", "assumption"),
    ("acceptance_criteria", "rule"),
    ("delivery_and_operations", "decision"),
)


def _write(
    memory: MemoryService,
    project_id: ProjectId,
    kind: str,
    key: str,
    confirm: bool = True,
) -> KnowledgeItem:
    """Write one knowledge item through a run, confirming it by default.

    Content varies by ``key``. Identical statements now collapse into one item
    on write, so a helper that wrote the same sentence for every area would
    silently cover one area instead of several — which is the inflation the
    collapse exists to prevent, seen from the other side.
    """

    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    item = memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind=kind, content=f"A {kind} for {key}.", source="test")],
    )[0]
    return memory.confirm_knowledge(item.id) if confirm else item


def _cover(
    memory: MemoryService, readiness: ReadinessService, project_id: ProjectId, confirm: bool = True
) -> None:
    """Write and assign enough knowledge to satisfy every area."""

    # The claims of a divided area, in the order its statements appear above.
    # Named rather than derived, so a test that stops covering both halves fails
    # loudly instead of quietly leaving one unestablished.
    claims = {
        ("problem_and_value", 0): "problem_statement",
        ("problem_and_value", 1): "value_proposition",
    }
    seen: dict[str, int] = {}

    for index, (area, kind) in enumerate(FULL_COVERAGE):
        item = _write(memory, project_id, kind, f"{area}-{index}", confirm=confirm)
        nth = seen.get(area, 0)
        seen[area] = nth + 1
        readiness.assign_area(project_id, item.id, area, claim_key=claims.get((area, nth)))


def test_an_untouched_project_scores_zero(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Empty")

    snapshot = readiness.calculate(project.id)

    assert snapshot.score == 0.0
    assert snapshot.status is ReadinessStatus.NOT_STARTED
    assert not snapshot.draft_eligible
    assert not snapshot.implementation_eligible


def test_unassigned_knowledge_covers_nothing(factory: sessionmaker[Session]) -> None:
    """Coverage requires an explicit area link, not merely a matching kind."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Unassigned")
    for index in range(5):
        _write(memory, project.id, "requirement", f"loose-{index}")

    snapshot = readiness.calculate(project.id)

    assert snapshot.score == 0.0


def test_confirming_knowledge_moves_the_score(factory: sessionmaker[Session]) -> None:
    """The proof moment: readiness rises only as knowledge is confirmed."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Moving")

    proposed = _write(memory, project.id, "actor", "actor-1", confirm=False)
    readiness.assign_area(project.id, proposed.id, "users_and_stakeholders")
    before = readiness.calculate(project.id)

    memory.confirm_knowledge(proposed.id)
    after = readiness.calculate(project.id)

    assert before.score < after.score
    area = next(a for a in after.areas if a.key == "users_and_stakeholders")
    assert area.state is AreaState.SUFFICIENT


def test_full_coverage_authorises_an_implementation_blueprint(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Covered")
    _cover(memory, readiness, project.id)

    snapshot = readiness.calculate(project.id)

    assert snapshot.percentage == 100
    assert snapshot.implementation_eligible
    assert snapshot.status is ReadinessStatus.BLUEPRINT_READY
    assert snapshot.missing_mandatory_areas == ()


def test_a_critical_blocker_blocks_a_fully_covered_project(
    factory: sessionmaker[Session],
) -> None:
    """A percentage alone never authorises an implementation blueprint."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Blocked")
    _cover(memory, readiness, project.id)
    blocker = readiness.raise_blocker(project.id, "Licensing unresolved.", owner="Cris")

    blocked = readiness.calculate(project.id)

    assert blocked.percentage == 100
    assert blocked.status is ReadinessStatus.BLOCKED
    assert not blocked.implementation_eligible
    assert blocked.critical_blocker_count == 1

    readiness.resolve_blocker(blocker.id, note="Cleared by legal.")
    cleared = readiness.calculate(project.id)

    assert cleared.status is ReadinessStatus.BLUEPRINT_READY
    assert cleared.implementation_eligible
    assert readiness.blockers(project.id, BlockerStatus.OPEN) == ()


def test_a_non_critical_blocker_does_not_block(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Minor")
    _cover(memory, readiness, project.id)
    readiness.raise_blocker(project.id, "Naming to revisit.", severity=BlockerSeverity.MINOR)

    snapshot = readiness.calculate(project.id)

    assert snapshot.open_blocker_count == 1
    assert snapshot.critical_blocker_count == 0
    assert snapshot.implementation_eligible


def test_an_unresolved_contradiction_on_a_mandatory_area_blocks(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Contradiction")
    _cover(memory, readiness, project.id)

    first = _write(memory, project.id, "requirement", "conflict-a")
    second = _write(memory, project.id, "requirement", "conflict-b")
    readiness.assign_area(project.id, first.id, "functional_requirements")
    readiness.assign_area(project.id, second.id, "functional_requirements")
    contradiction = readiness.record_contradiction(project.id, first.id, second.id)

    blocked = readiness.calculate(project.id)

    assert blocked.status is ReadinessStatus.BLOCKED
    assert not blocked.implementation_eligible
    assert blocked.unresolved_contradiction_count == 1

    assert readiness.resolve_contradiction(project.id, contradiction.id, note="Second supersedes.")
    resolved = readiness.calculate(project.id)

    assert resolved.status is ReadinessStatus.BLUEPRINT_READY
    assert resolved.unresolved_contradiction_count == 0


def test_resolving_a_contradiction_twice_reports_nothing_to_do(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Double resolve")
    first = _write(memory, project.id, "requirement", "a")
    second = _write(memory, project.id, "requirement", "b")
    contradiction = readiness.record_contradiction(project.id, first.id, second.id)

    assert readiness.resolve_contradiction(project.id, contradiction.id)
    assert not readiness.resolve_contradiction(project.id, contradiction.id)


def test_writing_and_confirming_knowledge_advances_the_revision(
    factory: sessionmaker[Session],
) -> None:
    """Staleness needs a monotonic counter, and this is what maintains it."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Revision")

    assert readiness.knowledge_revision(project.id) == 0

    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    item = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="test")]
    )[0]
    after_write = readiness.knowledge_revision(project.id)
    memory.confirm_knowledge(item.id)
    after_confirm = readiness.knowledge_revision(project.id)

    assert after_write == 1
    assert after_confirm == 2


def test_a_snapshot_goes_stale_when_knowledge_changes(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Stale")
    item = _write(memory, project.id, "actor", "actor-1")
    readiness.assign_area(project.id, item.id, "users_and_stakeholders")

    snapshot = readiness.calculate(project.id)
    assert not snapshot.is_stale_against(readiness.knowledge_revision(project.id))

    _write(memory, project.id, "requirement", "later-1")

    assert snapshot.is_stale_against(readiness.knowledge_revision(project.id))


def test_snapshots_are_append_only_history(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("History")

    readiness.calculate(project.id)
    item = _write(memory, project.id, "actor", "actor-1")
    readiness.assign_area(project.id, item.id, "users_and_stakeholders")
    readiness.calculate(project.id)

    history = readiness.history(project.id)
    latest = readiness.latest(project.id)

    assert len(history) == 2
    assert history[0].score < history[1].score
    assert latest is not None
    assert latest.id == history[-1].id


def test_a_snapshot_explains_itself(factory: sessionmaker[Session]) -> None:
    """A single mutable percentage would answer none of these questions."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Explainable")
    item = _write(memory, project.id, "requirement", "one")
    readiness.assign_area(project.id, item.id, "functional_requirements")

    snapshot = readiness.latest(project.id) or readiness.calculate(project.id)
    reloaded = readiness.latest(project.id)

    assert reloaded is not None
    area = next(a for a in reloaded.areas if a.key == "functional_requirements")
    # Also the round trip of a rung that did not exist before `EPI-5b`. Area
    # results persist as JSON strings, so a new state has to survive being
    # written and read back rather than degrading to an older one — and
    # `missing_mandatory_areas` below has to keep naming it.
    assert area.state is AreaState.EVIDENCED
    assert area.confirmed_count == 1
    assert area.minimum_confirmed == 3
    assert "functional_requirements" in reloaded.missing_mandatory_areas
    assert reloaded.calculation_version == snapshot.calculation_version


def test_excluded_areas_leave_the_denominator(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Excluded")
    item = _write(memory, project.id, "actor", "actor-1")
    readiness.assign_area(project.id, item.id, "users_and_stakeholders")

    included = readiness.calculate(project.id)
    excluded = readiness.calculate(
        project.id, not_applicable_areas=["interfaces_and_integrations", "delivery_and_operations"]
    )

    assert excluded.score > included.score
    area = next(a for a in excluded.areas if a.key == "delivery_and_operations")
    assert area.state is AreaState.NOT_APPLICABLE


def test_the_shipped_template_persists_and_reloads(factory: sessionmaker[Session]) -> None:
    from kae_memory.domain.readiness import SOFTWARE_TEMPLATE
    from kae_memory.persistence import ReadinessTemplateRepository

    readiness = ReadinessService(factory)
    readiness.install_template()
    readiness.install_template()  # idempotent

    with factory() as session:
        stored = ReadinessTemplateRepository(session).latest_active("software")

    assert stored == SOFTWARE_TEMPLATE


def test_an_area_refuses_knowledge_of_a_kind_it_cannot_count(
    factory: sessionmaker[Session],
) -> None:
    """Otherwise "assigned" and "counts" become two different things.

    A blueprint would then render a statement contributing nothing to the score
    printed beside it — which is exactly the kind of quiet divergence the
    readiness model exists to prevent.
    """

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Kind guard")
    question = _write(memory, project.id, "unknown", "q1", confirm=False)

    with pytest.raises(DomainInvariantError) as error:
        readiness.assign_area(project.id, question.id, "problem_and_value")

    assert "does not accept 'unknown'" in str(error.value)
    assert readiness.area_links(project.id) == ()


def test_the_api_reports_a_rejected_assignment_as_422(factory: sessionmaker[Session]) -> None:
    from fastapi.testclient import TestClient

    from kae_memory.api import create_app

    memory = MemoryService(factory)
    project = memory.create_project("Kind guard over HTTP")
    question = _write(memory, project.id, "unknown", "q1", confirm=False)

    with TestClient(create_app(factory)) as client:
        response = client.post(
            f"/v1/projects/{project.id}/readiness/areas",
            json={"knowledge_item_id": str(question.id), "area_key": "problem_and_value"},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "domain_invariant_violated"
