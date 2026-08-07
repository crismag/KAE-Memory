"""A message a person sends is interpreted, not only stored (N42, HTTP side).

N42 gave `kae_submit_observation` the edge from evidence to interpretation. The
capability register recorded, correctly, that Studio's equivalent is a
conversation message — "a different durable act with its own session ordering" —
and nobody gave that act the same edge.

The result was the exact failure N42 existed to fix, surviving in the adapter
N42 did not touch: a project driven entirely through Studio stored every word a
person said, and derived nothing from any of it. Found by manual testing, not by
a test, because both adapters were individually consistent.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def session_id(client: TestClient) -> str:
    project = client.post("/v1/projects", json={"name": "Studio Conversation"}).json()
    opened = client.post(
        f"/v1/projects/{project['id']}/sessions", json={"session_type": "discovery"}
    ).json()
    return str(opened["id"])


@pytest.fixture
def project_id(client: TestClient, session_id: str) -> ProjectId:
    listing = client.get("/v1/projects").json()
    return ProjectId(str(listing[0]["id"]))


def _say(client: TestClient, session_id: str, text: str, **extra: object) -> dict[str, object]:
    body = {"content": text, "actor_type": "user", "message_type": "input", **extra}
    response = client.post(f"/v1/sessions/{session_id}/messages", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


class TestAPersonsMessageReachesExtraction:
    def test_it_queues_a_discovery_run(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        """The edge that was missing. Without it a Studio-driven project is
        evidence with nothing derived from it."""

        _say(client, session_id, "I want an inbox that turns notes into tasks.")

        runs = MemoryService(factory).runs_for_project(project_id)

        assert [run.role for run in runs] == [AgentRole.DISCOVERY]

    def test_the_run_names_the_message_it_will_read(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        """Provenance starts here: a candidate must trace to stored text."""

        recorded = _say(client, session_id, "Notes should become tasks with due dates.")

        run = MemoryService(factory).runs_for_project(project_id)[0]

        assert run.input_context is not None
        assert run.input_context["message_id"] == recorded["id"]
        assert run.input_context["source"] == "conversation"

    def test_discovery_not_requirements(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        """`requirements.v1` is disciplined about not inventing requirements
        nobody expressed, which is right for a specification and reads an early
        description almost to nothing (N46)."""

        _say(client, session_id, "Something for keeping thoughts.")

        assert MemoryService(factory).runs_for_project(project_id)[0].role is AgentRole.DISCOVERY

    def test_the_message_is_stored_verbatim(self, client: TestClient, session_id: str) -> None:
        """Extraction derives beside the evidence, never over it."""

        text = "I want an inbox that turns notes into tasks."
        _say(client, session_id, text)

        stored = client.get(f"/v1/sessions/{session_id}/messages").json()
        assert any(message["content"] == text for message in stored)


class TestOnlyAPersonsWordsAreInterpreted:
    def test_an_agent_turn_queues_nothing(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        """An agent's own turn is already derived. Extracting from it would let
        a model's output re-enter as evidence for the next inference — a loop
        that manufactures confidence out of its own prior output."""

        _say(
            client,
            session_id,
            "What should the inbox do with a captured thought?",
            actor_type="agent",
            message_type="question",
            # Required: an agent message must name the run or external actor
            # that produced it, so a model's words are never anonymous in the
            # evidence log.
            actor_id="kae",
        )

        assert MemoryService(factory).runs_for_project(project_id) == ()

    def test_a_person_and_an_agent_in_one_session_queue_once(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        _say(client, session_id, "Notes become tasks.")
        _say(
            client,
            session_id,
            "By when?",
            actor_type="agent",
            message_type="question",
            actor_id="kae",
        )

        assert len(MemoryService(factory).runs_for_project(project_id)) == 1


class TestARetryDoesNotPayTwice:
    def test_the_same_message_reuses_its_run(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        """A retried submission must not produce a second model call, nor a
        second set of candidates for one thing a person said once."""

        _say(client, session_id, "Notes become tasks.", idempotency_key="studio-1")
        _say(client, session_id, "Notes become tasks.", idempotency_key="studio-1")

        assert len(MemoryService(factory).runs_for_project(project_id)) == 1

    def test_two_different_messages_get_their_own_runs(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        _say(client, session_id, "Notes become tasks.", idempotency_key="studio-a")
        _say(client, session_id, "Tasks need due dates.", idempotency_key="studio-b")

        assert len(MemoryService(factory).runs_for_project(project_id)) == 2


class TestNothingIsConfirmedByTalking:
    def test_no_knowledge_exists_yet(
        self,
        client: TestClient,
        factory: sessionmaker[Session],
        session_id: str,
        project_id: ProjectId,
    ) -> None:
        """Queued is not read, and read would not be confirmed either (FR-005)."""

        _say(client, session_id, "The inbox must support tags.")

        assert MemoryService(factory).retrieve_knowledge(project_id, lifecycle=None) == ()
