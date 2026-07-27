"""ADR-0005 approval criteria.

Each question the schema was approved to answer, answered relationally — no
process memory, log scraping, provider transcripts, or JSON parsing.
"""

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.workspace import SessionType
from kae_memory.persistence import (
    AgentRunRepository,
    MessageRepository,
    ProjectRepository,
    ProvenanceLinkRepository,
    SessionRepository,
)

PROJECT_KEY = "approval"


def _seed(factory: sessionmaker[Session]) -> None:
    """Build a project that exercises every approval query."""

    service = MemoryService(factory)
    project = service.create_project("Approval", key=PROJECT_KEY)

    discovery = service.open_session(project.id, SessionType.DISCOVERY)
    message = service.record_message(project.id, discovery.id, "Coordinators file reports.")
    writer = service.start_run(project.id, AgentRole.REQUIREMENTS, "req-1", discovery.id)
    items = service.write_knowledge(
        writer.id,
        [
            WriteKnowledgeRequest(
                kind="requirement",
                content="Coordinators file monthly reports.",
                source="discovery interview",
                from_message_id=message.id,
            )
        ],
    )
    service.confirm_knowledge(items[0].id)
    service.close_session(discovery.id)

    architecture = service.open_session(project.id, SessionType.ARCHITECTURE)
    reader = service.start_run(project.id, AgentRole.ARCHITECTURE, "arch-1", architecture.id)
    service.retrieve_knowledge(project.id, used_by_run_id=reader.id)
    service.fail_run(reader.id, "provider_unavailable", "model provider timed out")


def _project_id(factory: sessionmaker[Session]) -> ProjectId:
    with factory() as db:
        project = ProjectRepository(db).get_by_key(PROJECT_KEY)
        assert project is not None
        return project.id


def test_what_sessions_belong_to_this_project(factory: sessionmaker[Session]) -> None:
    _seed(factory)

    with factory() as db:
        sessions = SessionRepository(db).list_for_project(_project_id(factory))

    assert {session.type for session in sessions} == {
        SessionType.DISCOVERY,
        SessionType.ARCHITECTURE,
    }


def test_what_messages_occurred_in_a_session_and_in_what_order(
    factory: sessionmaker[Session],
) -> None:
    _seed(factory)
    project_id = _project_id(factory)

    with factory() as db:
        discovery = next(
            session
            for session in SessionRepository(db).list_for_project(project_id)
            if session.type is SessionType.DISCOVERY
        )
        messages = MessageRepository(db).list_for_session(discovery.id)

    assert [message.sequence_number for message in messages] == [1]
    assert messages[0].content == "Coordinators file reports."


def test_which_agent_executions_ran_and_with_what_status(
    factory: sessionmaker[Session],
) -> None:
    _seed(factory)
    project_id = _project_id(factory)

    with factory() as db:
        repository = AgentRunRepository(db)
        runs = repository.list_for_project(project_id)
        failed = repository.list_for_project(project_id, RunStatus.FAILED)

    assert {run.role for run in runs} == {AgentRole.REQUIREMENTS, AgentRole.ARCHITECTURE}
    assert len(failed) == 1
    assert failed[0].error_code == "provider_unavailable"
    assert failed[0].error_message == "model provider timed out"
    assert failed[0].failed_at is not None


def test_which_run_produced_or_used_a_piece_of_knowledge(
    factory: sessionmaker[Session],
) -> None:
    _seed(factory)
    project_id = _project_id(factory)

    with factory() as db:
        runs = AgentRunRepository(db).list_for_project(project_id)
        writer = next(run for run in runs if run.role is AgentRole.REQUIREMENTS)
        reader = next(run for run in runs if run.role is AgentRole.ARCHITECTURE)
        links = ProvenanceLinkRepository(db)
        produced = links.items_produced_by(writer.id)
        used = links.items_used_by(reader.id)
        for_run = links.list_for_run(writer.id)

    assert len(produced) == 1
    assert used == produced
    assert len(for_run) == 1


def test_what_current_confirmed_knowledge_exists(factory: sessionmaker[Session]) -> None:
    _seed(factory)
    service = MemoryService(factory)

    confirmed = service.retrieve_knowledge(_project_id(factory), lifecycle=LifecycleState.VALIDATED)

    assert len(confirmed) == 1
    assert confirmed[0].current_version.content == "Coordinators file monthly reports."


def test_a_new_process_can_reconstruct_context(factory: sessionmaker[Session]) -> None:
    """Nothing below reads state from the process that wrote it."""

    _seed(factory)

    fresh = MemoryService(factory)
    project_id = _project_id(factory)
    resumable = fresh.resumable_runs(project_id)

    assert len(resumable) == 1
    assert resumable[0].role is AgentRole.ARCHITECTURE
    assert fresh.retrieve_knowledge(project_id) != ()
