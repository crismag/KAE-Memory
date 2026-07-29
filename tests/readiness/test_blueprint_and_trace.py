"""Blueprint generation and traceability — AT-004.

*A generated blueprint section links each statement to the confirmed knowledge
item and source evidence that produced it.*
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import (
    BlueprintService,
    StatementLabel,
    render_markdown,
    statement_id,
)
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
from kae_memory.domain.workspace import SessionType

IDEA = "Ministry staff submit monthly reports. Approval happens before publication."


def _seed(factory: sessionmaker[Session]) -> tuple[ProjectId, KnowledgeItemId, str, str]:
    """Confirm one message-derived requirement, assigned to an area."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Reporting")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    message = memory.record_message(project.id, session.id, IDEA)
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    item = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="requirement",
                content="Ministry staff submit monthly reports.",
                source=IDEA,
                from_message_id=message.id,
            )
        ],
    )[0]
    memory.confirm_knowledge(item.id)
    readiness.assign_area(project.id, item.id, "functional_requirements")
    return project.id, item.id, str(message.id), str(run.id)


def _blueprint(factory: sessionmaker[Session], project_id: ProjectId) -> object:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.get_project(project_id)
    assert project is not None
    snapshot = readiness.calculate(project_id)
    return BlueprintService(factory).generate(
        project_id,
        project.name,
        snapshot.percentage,
        snapshot.draft_eligible,
        snapshot.implementation_eligible,
        snapshot.missing_mandatory_areas,
    )


def test_every_statement_has_a_label_and_a_trace_target(
    factory: sessionmaker[Session],
) -> None:
    """FR-008's acceptance condition, and it holds structurally."""

    project_id, _item_id, _message_id, _run_id = _seed(factory)

    blueprint = _blueprint(factory, project_id)

    statements = [s for section in blueprint.sections for s in section.statements]  # type: ignore[attr-defined]
    assert statements
    assert all(statement.label for statement in statements)
    assert all(statement.knowledge_item_id for statement in statements)
    assert all(statement.produced_by_run_id for statement in statements)


def test_a_statement_from_a_message_is_grounded(factory: sessionmaker[Session]) -> None:
    project_id, _item_id, _message_id, _run_id = _seed(factory)

    blueprint = _blueprint(factory, project_id)
    statement = blueprint.sections[0].statements[0]  # type: ignore[attr-defined]

    assert statement.label is StatementLabel.GROUNDED
    assert statement.source_message_id is not None


def test_knowledge_with_no_message_is_derived(factory: sessionmaker[Session]) -> None:
    """An architecture decision derives from other knowledge, not from words."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Derived")
    run = memory.start_run(project.id, AgentRole.ARCHITECTURE, "derive-1")
    item = memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="decision", content="Use one queue.", source="requirement")],
    )[0]
    memory.confirm_knowledge(item.id)
    readiness.assign_area(project.id, item.id, "scope_and_boundaries")

    blueprint = _blueprint(factory, project.id)

    assert blueprint.sections[0].statements[0].label is StatementLabel.DERIVED  # type: ignore[attr-defined]


def test_an_assumption_stays_an_assumption_even_when_a_message_prompted_it(
    factory: sessionmaker[Session],
) -> None:
    """Labelling it grounded would overstate its standing."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Assumed")
    session = memory.open_session(project.id, SessionType.DISCOVERY)
    message = memory.record_message(project.id, session.id, "Probably monthly.")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    item = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="assumption",
                content="Reporting is monthly.",
                source="Probably monthly.",
                from_message_id=message.id,
            )
        ],
    )[0]
    memory.confirm_knowledge(item.id)
    readiness.assign_area(project.id, item.id, "constraints_and_assumptions")

    blueprint = _blueprint(factory, project.id)

    assert blueprint.sections[0].statements[0].label is StatementLabel.ASSUMPTION  # type: ignore[attr-defined]


def test_unconfirmed_knowledge_never_reaches_the_blueprint(
    factory: sessionmaker[Session],
) -> None:
    """Only confirmed knowledge is renderable (FR-008)."""

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("Unconfirmed")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    item = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="test")]
    )[0]
    readiness.assign_area(project.id, item.id, "functional_requirements")

    blueprint = _blueprint(factory, project.id)

    assert blueprint.sections == ()  # type: ignore[attr-defined]
    assert blueprint.statement_count == 0  # type: ignore[attr-defined]


def test_statement_identifiers_are_stable_across_regeneration(
    factory: sessionmaker[Session],
) -> None:
    """A client can link to a statement; a disappearing one changed, not churned."""

    project_id, item_id, _message_id, _run_id = _seed(factory)

    first = _blueprint(factory, project_id)
    second = _blueprint(factory, project_id)

    assert first.sections[0].statements[0].id == second.sections[0].statements[0].id  # type: ignore[attr-defined]
    assert first.sections[0].statements[0].id == statement_id(  # type: ignore[attr-defined]
        project_id, "functional_requirements", item_id
    )


def test_an_incomplete_blueprint_reports_what_is_missing(
    factory: sessionmaker[Session],
) -> None:
    """The most useful thing an early blueprint can say."""

    project_id, _item_id, _message_id, _run_id = _seed(factory)

    blueprint = _blueprint(factory, project_id)

    assert not blueprint.complete  # type: ignore[attr-defined]
    assert not blueprint.implementation_eligible  # type: ignore[attr-defined]
    assert blueprint.missing_mandatory_areas  # type: ignore[attr-defined]


def test_confirmed_knowledge_with_no_area_is_counted_not_hidden(
    factory: sessionmaker[Session],
) -> None:
    """An empty blueprint over a full knowledge base must explain itself."""

    memory = MemoryService(factory)
    project = memory.create_project("Unassigned")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "extract-1")
    item = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="test")]
    )[0]
    memory.confirm_knowledge(item.id)

    blueprint = _blueprint(factory, project.id)

    assert blueprint.sections == ()  # type: ignore[attr-defined]
    assert blueprint.unassigned_confirmed_count == 1  # type: ignore[attr-defined]


def test_markdown_carries_the_same_labels_and_identifiers(
    factory: sessionmaker[Session],
) -> None:
    """An exported document is as traceable as the API response."""

    project_id, item_id, _message_id, _run_id = _seed(factory)

    markdown = render_markdown(_blueprint(factory, project_id))  # type: ignore[arg-type]

    assert "# Reporting" in markdown
    assert "Draft blueprint — incomplete" in markdown
    assert "[grounded; knowledge " in markdown
    assert str(item_id) in markdown
    assert "## Missing mandatory areas" in markdown


def test_trace_resolves_a_statement_to_its_evidence(factory: sessionmaker[Session]) -> None:
    """AT-004: statement to confirmed knowledge to the source evidence behind it."""

    project_id, item_id, message_id, run_id = _seed(factory)

    trace = BlueprintService(factory).trace(item_id)

    assert trace is not None
    assert str(trace.project_id) == str(project_id)
    assert [str(m) for m in trace.source_message_ids] == [message_id]
    assert str(trace.produced_by_run_id) == run_id
    assert trace.session_ids
    relations = {step.relation for step in trace.steps}
    assert relations >= {"project", "session", "source_message", "produced_by_run"}
    assert any(step.relation == "knowledge_version" for step in trace.steps)


def test_trace_records_which_runs_consumed_the_knowledge(
    factory: sessionmaker[Session],
) -> None:
    """`used_by` is what makes "which run relied on this?" answerable."""

    memory = MemoryService(factory)
    project_id, item_id, _message_id, _run_id = _seed(factory)
    consumer = memory.start_run(project_id, AgentRole.ARCHITECTURE, "derive-1")
    memory.retrieve_knowledge(project_id, used_by_run_id=consumer.id)

    trace = BlueprintService(factory).trace(item_id)

    assert trace is not None
    assert str(consumer.id) in [str(run) for run in trace.used_by_run_ids]


def test_the_endpoints_serve_the_blueprint_and_the_trace(
    factory: sessionmaker[Session],
) -> None:
    project_id, item_id, message_id, run_id = _seed(factory)

    with TestClient(create_app(factory)) as client:
        blueprint = client.get(f"/v1/projects/{project_id}/blueprint").json()
        markdown = client.get(f"/v1/projects/{project_id}/blueprint.md")
        trace = client.get(f"/v1/knowledge/{item_id}/trace").json()
        missing = client.get("/v1/knowledge/00000000-0000-0000-0000-000000000000/trace")

    statement = blueprint["sections"][0]["statements"][0]
    assert statement["label"] == "grounded"
    assert statement["knowledge_item_id"] == str(item_id)
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert trace["source_message_ids"] == [message_id]
    assert trace["produced_by_run_id"] == run_id
    assert missing.status_code == 404
