"""Describing a project must not change it.

D-13. `open_questions()` materialises: it turns derived clarifications into
durable messages so a caller has something answerable. That is right when
somebody is about to be asked, and wrong when somebody is merely looking.

Two paths were merely looking. `preliminary_context_service` builds a
disclosure document — its own comment reads *"a context document is not asking,
it is disclosing"* — and called the method that asks. So composing a context
wrote every outstanding question into the conversation, and a monitor, a
refresh, or a retry did it again.

The cost was not noise alone. **Which id a question received depended on which
endpoint was read first**, because materialising is what assigns one.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId


@pytest.fixture
def project(factory: sessionmaker[Session]) -> ProjectId:
    """A project holding an unknown, which is what produces a question."""

    readiness = ReadinessService(factory)
    readiness.install_template()
    memory = MemoryService(factory)
    created = memory.create_project("Listing", key="listing-does-not-ask")
    run = memory.start_run(created.id, AgentRole.REQUIREMENTS, "seed-listing")
    memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="unknown",
                content="Who approves a report before publication?",
                source="interview",
            )
        ],
    )
    return created.id


def _messages(memory: MemoryService, project_id: ProjectId) -> int:
    return sum(
        len(memory.messages_for_session(session.id))
        for session in memory.sessions_for_project(project_id)
    )


def test_listing_candidates_writes_nothing(
    factory: sessionmaker[Session], project: ProjectId
) -> None:
    memory = MemoryService(factory)
    clarifications = ClarificationService(factory)

    before = _messages(memory, project)
    first = clarifications.candidates(project)
    second = clarifications.candidates(project)
    after = _messages(memory, project)

    assert first, "the project holds an unknown, so something should be askable"
    assert after == before, "listing candidates recorded a message"
    assert [c.candidate_key for c in first] == [c.candidate_key for c in second], (
        "a candidate key must be stable across derivations, or it is not an identity"
    )


def test_an_unasked_candidate_has_no_id(factory: sessionmaker[Session], project: ProjectId) -> None:
    """`None` is the honest answer, not a missing field.

    Nobody has been shown it, so there is no message and no id — which is what
    distinguishes a candidate from an OpenQuestion.
    """

    candidate = ClarificationService(factory).candidates(project)[0]

    assert candidate.asked_id is None
    assert candidate.asked_at is None
    assert not candidate.is_asked
    assert candidate.candidate_key


def test_composing_a_context_document_does_not_ask_anybody(
    factory: sessionmaker[Session], project: ProjectId
) -> None:
    """The path whose own comment said it was not asking, and then asked."""

    memory = MemoryService(factory)
    preliminary = PreliminaryContextService(factory)

    before = _messages(memory, project)
    context = preliminary.compose(project)
    after = _messages(memory, project)

    assert after == before, "composing a preliminary context wrote to the transcript"
    unknowns = context.material_unknowns + context.deferrable_unknowns
    assert unknowns, "the unknown must still be disclosed — silence is the other failure"


def test_asking_is_what_writes(factory: sessionmaker[Session], project: ProjectId) -> None:
    """The counterpart. If nothing wrote, the split would have broken asking.

    A question a person can answer needs an id, and an id needs a record.
    """

    memory = MemoryService(factory)
    clarifications = ClarificationService(factory)

    before = _messages(memory, project)
    asked = clarifications.open_questions(project)
    after = _messages(memory, project)

    assert asked
    assert after > before, "asking must record the question it asked"
    assert asked[0].id


def test_a_candidate_reports_the_question_once_it_has_been_asked(
    factory: sessionmaker[Session], project: ProjectId
) -> None:
    """Listing after asking reports the same subject, now carrying its id.

    The two views must not disagree about what is outstanding — a candidate
    list that forgot an asked question would re-offer it, which is the
    re-asking defect wearing different clothes.
    """

    clarifications = ClarificationService(factory)
    asked = clarifications.open_questions(project)[0]

    candidate = clarifications.candidates(project)[0]

    assert candidate.asked_id == asked.id
    assert candidate.is_asked
    assert candidate.asked_at is not None


def test_the_route_is_a_get_that_does_not_write(
    factory: sessionmaker[Session], project: ProjectId
) -> None:
    """The half a proxy, a prefetch or a retry will exercise without meaning to.

    Its sibling is a POST for a reason — materialising is a command. This one
    must be safe to call as often as anything likes.
    """

    from fastapi.testclient import TestClient

    from kae_memory.api import create_app
    from kae_memory.api.security import AuthPolicy

    memory = MemoryService(factory)
    with TestClient(create_app(factory, auth=AuthPolicy())) as client:
        before = _messages(memory, project)
        first = client.get(f"/v1/projects/{project}/clarifications/candidates")
        client.get(f"/v1/projects/{project}/clarifications/candidates")
        after = _messages(memory, project)

    assert first.status_code == 200
    body = first.json()
    assert body["candidates"], "the project holds an unknown"
    assert body["candidates"][0]["asked_id"] is None
    assert body["candidates"][0]["candidate_key"]
    assert after == before, "a GET wrote to the transcript"
    assert "did not ask anybody" in body["note"]


def test_a_limit_bounds_what_is_asked_not_only_what_is_returned(
    factory: sessionmaker[Session], project: ProjectId
) -> None:
    """Asking for one question must not put ten to a person.

    `limit` used to slice the result *after* materialising every pending
    clarification, so a caller wanting a single question asked all of them and
    displayed the first. That is the mechanism behind a transcript filling with
    ten area questions before its second human message — the caller looked
    restrained and the person did not experience restraint.

    Verified as a *count of messages*, not of returned questions, because the
    old behaviour returned exactly one too.
    """

    clarifications = ClarificationService(factory)
    memory = MemoryService(factory)

    available = len(clarifications.candidates(project))
    assert available > 1, "this project must hold more than one unknown to prove anything"

    before = _messages(memory, project)
    asked = clarifications.open_questions(project, limit=1)

    assert len(asked) == 1
    assert _messages(memory, project) == before + 1, "a limit of one asked more than one question"
