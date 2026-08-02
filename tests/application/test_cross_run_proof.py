"""The M5 persistent-memory proof.

Agent A writes knowledge, its process ends, and Agent B retrieves it in a separate
run and session with no shared in-process state.
"""

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import ProvenanceLinkType
from kae_memory.domain.workspace import ActorType, MessageType, SessionType


def test_agent_b_retrieves_knowledge_written_by_agent_a(factory: sessionmaker[Session]) -> None:
    """The success condition for M5."""

    # --- Agent A's process -------------------------------------------------
    service_a = MemoryService(factory)
    project = service_a.create_project("Ministry reporting", key="ministry-reporting")
    session_a = service_a.open_session(project.id, SessionType.DISCOVERY)
    message = service_a.record_message(
        project.id,
        session_a.id,
        "We need to replace the physical reporting binder used by ministry coordinators.",
    ).message
    run_a = service_a.start_run(
        project.id,
        AgentRole.REQUIREMENTS,
        idempotency_key="requirements-1",
        session_id=session_a.id,
    )
    written = service_a.write_knowledge(
        run_a.id,
        [
            WriteKnowledgeRequest(
                kind="requirement",
                content="The system replaces the physical reporting binder.",
                source="discovery interview",
                from_message_id=message.id,
            )
        ],
    )
    confirmed = service_a.confirm_knowledge(written[0].id)
    service_a.close_session(session_a.id)

    assert confirmed.lifecycle is LifecycleState.VALIDATED

    # --- Agent A's process ends. Nothing is carried forward. ---------------
    del service_a, run_a, written, confirmed, message, session_a

    # --- Agent B's process, a separate service over the same database ------
    service_b = MemoryService(factory)
    session_b = service_b.open_session(project.id, SessionType.ARCHITECTURE)
    run_b = service_b.start_run(
        project.id,
        AgentRole.ARCHITECTURE,
        idempotency_key="architecture-1",
        session_id=session_b.id,
    )
    recalled = service_b.retrieve_knowledge(project.id, used_by_run_id=run_b.id)

    assert len(recalled) == 1
    item = recalled[0]
    assert item.current_version.content == "The system replaces the physical reporting binder."
    assert item.lifecycle is LifecycleState.VALIDATED
    assert item.current_version.provenance.recorded_at.tzinfo is not None

    # The knowledge resolves to the run that produced it, in the earlier session.
    producing_run_id = item.current_version.provenance.execution_id
    producing_run = service_b.get_run(type(run_b.id)(str(producing_run_id)))
    assert producing_run is not None
    assert producing_run.role is AgentRole.REQUIREMENTS
    assert producing_run.status is RunStatus.SUCCEEDED
    assert producing_run.session_id != run_b.session_id


def test_provenance_answers_produced_and_used_relationally(
    factory: sessionmaker[Session],
) -> None:
    """Both 'which run produced this' and 'which run used this' are queryable."""

    service = MemoryService(factory)
    project = service.create_project("Traceability")
    session = service.open_session(project.id, SessionType.DISCOVERY)
    message = service.record_message(
        project.id, session.id, "Reporting cycles are configurable."
    ).message
    writer = service.start_run(project.id, AgentRole.REQUIREMENTS, "req-1", session.id)
    items = service.write_knowledge(
        writer.id,
        [
            WriteKnowledgeRequest(
                kind="rule",
                content="Reporting-cycle duration is configurable.",
                source="discovery interview",
                from_message_id=message.id,
            )
        ],
    )
    service.confirm_knowledge(items[0].id)

    reader = service.start_run(project.id, AgentRole.ARCHITECTURE, "arch-1", session.id)
    service.retrieve_knowledge(project.id, used_by_run_id=reader.id)

    links = service.provenance_for_item(items[0].id)
    by_type = {link.link_type: link for link in links}

    assert by_type[ProvenanceLinkType.PRODUCED_BY].agent_run_id == writer.id
    assert by_type[ProvenanceLinkType.USED_BY].agent_run_id == reader.id
    assert by_type[ProvenanceLinkType.DERIVED_FROM_MESSAGE].message_id == message.id


def test_message_content_is_stored_verbatim(factory: sessionmaker[Session]) -> None:
    """Extraction never rewrites the user's words."""

    service = MemoryService(factory)
    project = service.create_project("Verbatim")
    session = service.open_session(project.id, SessionType.DISCOVERY)
    original = "  Ministry coordinators file reports MONTHLY -- sometimes late.\n"

    service.record_message(project.id, session.id, original)
    stored = service.messages_for_session(session.id)

    assert len(stored) == 1
    assert stored[0].content == original
    assert stored[0].actor_type is ActorType.USER
    assert stored[0].message_type is MessageType.INPUT


def test_messages_are_ordered_within_a_session(factory: sessionmaker[Session]) -> None:
    """Sequence numbers are assigned in submission order and start at one."""

    service = MemoryService(factory)
    project = service.create_project("Ordering")
    session = service.open_session(project.id, SessionType.DISCOVERY)

    for text in ("first", "second", "third"):
        service.record_message(project.id, session.id, text)

    stored = service.messages_for_session(session.id)

    assert [message.sequence_number for message in stored] == [1, 2, 3]
    assert [message.content for message in stored] == ["first", "second", "third"]


def test_unconfirmed_knowledge_is_not_returned_as_confirmed(
    factory: sessionmaker[Session],
) -> None:
    """A candidate the human never confirmed must not surface as durable truth."""

    service = MemoryService(factory)
    project = service.create_project("Confirmation gate")
    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "req-1")
    service.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind="requirement", content="Unreviewed claim.", source="model")],
    )

    assert service.retrieve_knowledge(project.id) == ()
    assert len(service.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)) == 1
