"""Quality findings, and what a review run is allowed to do.

FR-015: a reviewer can read what is unresolved without inspecting the database.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.review_service import (
    FindingKind,
    ReviewService,
    Severity,
    classify_offline,
    unambiguous_area_for,
)
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.readiness import AreaResult, AreaState, BlockerSeverity, ReadinessSnapshot
from kae_memory.domain.workspace import SessionType
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

IDEA = (
    "We need a way for ministry staff to submit monthly reports. "
    "Approval should happen before publication, but we have not decided who approves."
)


def _kinds(service: ReviewService, project_id: ProjectId) -> set[FindingKind]:
    return {finding.kind for finding in service.findings(project_id)}


def _write(memory: MemoryService, project_id: ProjectId, kind: str, key: str) -> object:
    """Write one item, distinct per ``key``.

    Two items with identical content are one item now, so a contradiction
    between them is not expressible — which is correct, and means fixtures must
    say different things when they mean different statements.
    """

    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind=kind, content=f"A {kind} for {key}.", source="test")],
    )[0]


def test_an_empty_project_reports_every_mandatory_gap(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    review = ReviewService(factory)
    project = memory.create_project("Empty")

    findings = review.findings(project.id)

    missing = [f for f in findings if f.kind is FindingKind.MISSING_AREA]
    assert len(missing) == 10
    assert sum(1 for f in missing if f.severity is Severity.CRITICAL) == 8
    assert all(f.recommended_action for f in findings)


def test_findings_are_ordered_most_severe_first(factory: sessionmaker[Session]) -> None:
    """A report where everything is urgent is a report nobody reads."""

    memory = MemoryService(factory)
    review = ReviewService(factory)
    project = memory.create_project("Ordering")

    severities = [finding.severity for finding in review.findings(project.id)]

    assert severities == sorted(
        severities, key=lambda s: [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR].index(s)
    )


def test_unconfirmed_and_unclassified_knowledge_is_reported(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    review = ReviewService(factory)
    project = memory.create_project("Candidates")
    _write(memory, project.id, "requirement", "one")

    kinds = _kinds(review, project.id)

    assert FindingKind.UNCONFIRMED_KNOWLEDGE in kinds
    assert FindingKind.UNCLASSIFIED_KNOWLEDGE in kinds


def test_an_open_question_is_reported_as_one(factory: sessionmaker[Session]) -> None:
    """A gap the project recorded about itself is worth surfacing."""

    memory = MemoryService(factory)
    review = ReviewService(factory)
    project = memory.create_project("Questions")
    _write(memory, project.id, "unknown", "q1")

    assert FindingKind.OPEN_QUESTION in _kinds(review, project.id)


def test_blockers_and_contradictions_surface_as_critical(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    review = ReviewService(factory)
    project = memory.create_project("Conflicts")
    first = _write(memory, project.id, "requirement", "a")
    second = _write(memory, project.id, "requirement", "b")
    readiness.record_contradiction(project.id, first.id, second.id)  # type: ignore[attr-defined]
    readiness.raise_blocker(project.id, "Licensing unresolved.", BlockerSeverity.CRITICAL)

    findings = {f.kind: f for f in review.findings(project.id)}

    assert findings[FindingKind.UNRESOLVED_CONTRADICTION].severity is Severity.CRITICAL
    assert findings[FindingKind.OPEN_BLOCKER].severity is Severity.CRITICAL
    assert len(findings[FindingKind.UNRESOLVED_CONTRADICTION].knowledge_item_ids) == 2


def test_resolving_the_condition_removes_the_finding(factory: sessionmaker[Session]) -> None:
    """Findings have no identity and cannot be dismissed — only resolved."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    review = ReviewService(factory)
    project = memory.create_project("Resolution")
    blocker = readiness.raise_blocker(project.id, "Pending decision.")
    assert FindingKind.OPEN_BLOCKER in _kinds(review, project.id)

    readiness.resolve_blocker(blocker.id, note="Decided.")

    assert FindingKind.OPEN_BLOCKER not in _kinds(review, project.id)


def test_offline_classification_refuses_to_guess() -> None:
    """`requirement` is accepted by four areas, so choosing one is a judgement."""

    assert unambiguous_area_for("actor") == "users_and_stakeholders"
    assert unambiguous_area_for("requirement") is None
    assert unambiguous_area_for("unknown") is None


def test_a_review_run_classifies_what_it_can_and_reports_the_rest(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Review run")
    _write(memory, project.id, "actor", "actor-1")
    _write(memory, project.id, "requirement", "req-1")
    memory.enqueue_run(project.id, AgentRole.REVIEW, "review-1")

    executed = Worker(
        factory,
        AgentStepExecutor(factory, object()),  # type: ignore[arg-type]
        WorkerConfig(worker_id="reviewer"),
    ).run_once()

    assert executed is not None
    assert executed.status is RunStatus.SUCCEEDED
    summary = executed.output_summary or {}
    assert summary["areas_assigned"] == 1, "only the unambiguous actor is classified"
    assert summary["critical_findings"] > 0
    assert summary["classification"] == "offline_by_kind"

    links = readiness.area_links(project.id)
    assert [link.area_key for link in links] == ["users_and_stakeholders"]
    assert links[0].assigned_by_agent_run_id == executed.id, "classification is attributable"


def test_a_review_run_never_records_a_contradiction(factory: sessionmaker[Session]) -> None:
    """A false positive would stall a project on a model's say-so."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("No auto-contradiction")
    _write(memory, project.id, "requirement", "a")
    _write(memory, project.id, "requirement", "b")
    memory.enqueue_run(project.id, AgentRole.REVIEW, "review-1")

    Worker(
        factory,
        AgentStepExecutor(factory, object()),  # type: ignore[arg-type]
        WorkerConfig(worker_id="reviewer"),
    ).run_once()

    snapshot = readiness.calculate(project.id)
    assert snapshot.unresolved_contradiction_count == 0


def test_a_review_run_never_confirms_knowledge(factory: sessionmaker[Session]) -> None:
    """Confirmation is a human act (FR-005)."""

    from kae_memory.domain.lifecycle import LifecycleState

    memory = MemoryService(factory)
    project = memory.create_project("No auto-confirm")
    _write(memory, project.id, "actor", "actor-1")
    memory.enqueue_run(project.id, AgentRole.REVIEW, "review-1")

    Worker(
        factory,
        AgentStepExecutor(factory, object()),  # type: ignore[arg-type]
        WorkerConfig(worker_id="reviewer"),
    ).run_once()

    assert memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.VALIDATED) == ()


def test_classification_alone_cannot_manufacture_coverage(
    factory: sessionmaker[Session],
) -> None:
    """An area still needs *confirmed* knowledge to become sufficient.

    Classification moves an area from missing to partial, because a proposed
    candidate is worth half credit under ADR-0012. It cannot move it to
    sufficient — only a human confirming the knowledge does that.
    """

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("No free coverage")
    item = _write(memory, project.id, "actor", "actor-1")
    memory.enqueue_run(project.id, AgentRole.REVIEW, "review-1")
    Worker(
        factory,
        AgentStepExecutor(factory, object()),  # type: ignore[arg-type]
        WorkerConfig(worker_id="reviewer"),
    ).run_once()

    classified_only = readiness.calculate(project.id)
    memory.confirm_knowledge(item.id)  # type: ignore[attr-defined]
    confirmed = readiness.calculate(project.id)

    def area_of(snapshot: ReadinessSnapshot) -> AreaResult:
        return next(a for a in snapshot.areas if a.key == "users_and_stakeholders")

    # Grounded — a person's statement — and still not covered, which is the
    # claim this test makes. Classification moved the area onto `ADR-0008`'s
    # ladder and only confirmation reaches the top of it.
    assert area_of(classified_only).state is AreaState.EVIDENCED
    assert area_of(confirmed).state is AreaState.SUFFICIENT
    assert confirmed.score > classified_only.score


def test_the_endpoint_reports_findings_with_counts(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project = memory.create_project("HTTP review")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    memory.record_message(project.id, session.id, IDEA)

    with TestClient(create_app(factory)) as client:
        body = client.get(f"/v1/projects/{project.id}/review").json()

    assert body["counts"]["total"] == len(body["findings"])
    assert body["counts"]["critical"] > 0
    assert body["findings"][0]["severity"] == "critical"
    assert "id" not in body["findings"][0], "findings are derived, so they have no identity"


def test_classify_offline_maps_only_unambiguous_kinds(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project = memory.create_project("Mapping")
    _write(memory, project.id, "actor", "a")
    _write(memory, project.id, "requirement", "r")

    assignments = classify_offline(memory.retrieve_knowledge(project.id, lifecycle=None))

    assert [area for _item, area in assignments] == ["users_and_stakeholders"]
