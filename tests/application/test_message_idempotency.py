"""Idempotent evidence ingestion (ADR-0018).

A retried submission must not create a second piece of evidence. The guarantee
is a CockroachDB unique constraint, not an in-process guard: these tests use
real threads against the real engine, because a lookup-then-insert passes a
sequential test and still loses under concurrency.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.domain.errors import IdempotencyConflictError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId, SessionId
from kae_memory.domain.workspace import ActorType, MessageType, SessionType

OBSERVATION = "The approval endpoint accepts a single approver identifier."


def _project_and_session(service: MemoryService) -> tuple[ProjectId, SessionId]:
    project = service.create_project("Ministry reporting")
    working = service.open_session(project.id, SessionType.DISCOVERY)
    return project.id, working.id


def test_same_key_and_payload_returns_the_original(factory: sessionmaker[Session]) -> None:
    service = MemoryService(factory)
    project_id, session_id = _project_and_session(service)

    first = service.record_message(
        project_id, session_id, OBSERVATION, idempotency_key="agent-observation-1"
    )
    second = service.record_message(
        project_id, session_id, OBSERVATION, idempotency_key="agent-observation-1"
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.message.id == first.message.id
    assert len(service.messages_for_session(session_id)) == 1


def test_replay_tolerates_reformatted_payload(factory: sessionmaker[Session]) -> None:
    """Whitespace is normalised, so a re-wrapped resubmission is still a replay.

    Reporting a conflict here would be a false alarm: the statement is the same.
    """

    service = MemoryService(factory)
    project_id, session_id = _project_and_session(service)

    first = service.record_message(
        project_id, session_id, OBSERVATION, idempotency_key="agent-observation-1"
    )
    rewrapped = OBSERVATION.replace(" a single", "\n  a  single")
    second = service.record_message(
        project_id, session_id, rewrapped, idempotency_key="agent-observation-1"
    )

    assert second.replayed is True
    assert second.message.id == first.message.id


def test_same_key_with_different_payload_conflicts(factory: sessionmaker[Session]) -> None:
    """Returning the original would silently discard the caller's new content."""

    service = MemoryService(factory)
    project_id, session_id = _project_and_session(service)

    service.record_message(
        project_id, session_id, OBSERVATION, idempotency_key="agent-observation-1"
    )

    with pytest.raises(IdempotencyConflictError):
        service.record_message(
            project_id,
            session_id,
            "The approval endpoint accepts a list of approvers.",
            idempotency_key="agent-observation-1",
        )

    assert len(service.messages_for_session(session_id)) == 1


def test_same_key_from_a_different_actor_conflicts(factory: sessionmaker[Session]) -> None:
    """Identical words from a different actor are a different submission."""

    service = MemoryService(factory)
    project_id, session_id = _project_and_session(service)
    run = service.start_run(project_id, AgentRole.REQUIREMENTS, "run-key-1", session_id)

    service.record_message(
        project_id, session_id, OBSERVATION, idempotency_key="agent-observation-1"
    )

    with pytest.raises(IdempotencyConflictError):
        service.record_message(
            project_id,
            session_id,
            OBSERVATION,
            actor_type=ActorType.AGENT,
            message_type=MessageType.PROPOSAL,
            agent_run_id=run.id,
            idempotency_key="agent-observation-1",
        )


@pytest.mark.real_commits
def test_concurrent_retries_create_exactly_one_record(factory: sessionmaker[Session]) -> None:
    """The constraint, not the lookup, is what makes this true.

    Eight threads submit the same key simultaneously. A read-then-insert would
    let several find nothing and all insert; the unique index lets exactly one
    win and the rest resolve to a replay.
    """

    service = MemoryService(factory)
    project_id, session_id = _project_and_session(service)

    def submit() -> bool:
        return service.record_message(
            project_id, session_id, OBSERVATION, idempotency_key="concurrent-key"
        ).replayed

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: submit(), range(8)))

    assert len(service.messages_for_session(session_id)) == 1
    assert results.count(False) == 1, "exactly one submission may create the record"
    assert results.count(True) == 7


def test_messages_without_a_key_are_unaffected(factory: sessionmaker[Session]) -> None:
    """Existing callers keep working; many rows may carry no key at all."""

    service = MemoryService(factory)
    project_id, session_id = _project_and_session(service)

    service.record_message(project_id, session_id, "First statement.")
    service.record_message(project_id, session_id, "First statement.")

    assert len(service.messages_for_session(session_id)) == 2


def test_the_key_is_scoped_to_one_project(factory: sessionmaker[Session]) -> None:
    """A key reused in a different project is a different submission."""

    service = MemoryService(factory)
    first_project, first_session = _project_and_session(service)
    second_project, second_session = _project_and_session(service)

    service.record_message(first_project, first_session, OBSERVATION, idempotency_key="shared")
    second = service.record_message(
        second_project, second_session, OBSERVATION, idempotency_key="shared"
    )

    assert second.replayed is False
    assert len(service.messages_for_session(second_session)) == 1
