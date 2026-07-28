"""Readiness over real persisted state, against CockroachDB.

Covers the four things ADR-0012 recorded as missing: relationship wiring,
blockers, the project knowledge revision, and area assignment.
"""

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
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
FULL_COVERAGE: tuple[tuple[str, str], ...] = (
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
    """Write one knowledge item through a run, confirming it by default."""

    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    item = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind=kind, content=f"A {kind}.", source="test")]
    )[0]
    return memory.confirm_knowledge(item.id) if confirm else item


def _cover(
    memory: MemoryService, readiness: ReadinessService, project_id: ProjectId, confirm: bool = True
) -> None:
    """Write and assign enough knowledge to satisfy every area."""

    for index, (area, kind) in enumerate(FULL_COVERAGE):
        item = _write(memory, project_id, kind, f"{area}-{index}", confirm=confirm)
        readiness.assign_area(project_id, item.id, area)


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
    assert area.state is AreaState.PARTIAL
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
