"""Listing questions does not manufacture a session for each one.

`open_questions` materialises every pending clarification, and each
`_materialise` opened its own session when the caller named none. Listing ten
questions produced ten sessions holding one message each.

That is not untidiness. Session count then tracks the number of clarifications
rather than the number of conversations, and "the project's session" stops
meaning anything — which is how one client writing a message and another
reading the transcript ended up in different ones, with the conversation
apparently losing what had just been said.

Found by wiring a real conversational turn through two clients, not by a test:
each was individually correct.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project_id(client: TestClient) -> str:
    return str(client.post("/v1/projects", json={"name": "Sessions"}).json()["id"])


def _sessions(client: TestClient, project_id: str) -> list[dict[str, object]]:
    payload = client.get(f"/v1/projects/{project_id}/sessions").json()
    items = payload if isinstance(payload, list) else payload.get("results", [])
    return [dict(item) for item in items]


def _list_questions(client: TestClient, project_id: str) -> list[dict[str, object]]:
    response = client.post(f"/v1/projects/{project_id}/clarifications", params={"limit": 20})
    assert response.status_code == 200, response.text
    payload = response.json()
    items = payload.get("questions", []) if isinstance(payload, dict) else payload
    return [dict(item) for item in items]


class TestOneSessionPerBatch:
    def test_many_questions_share_one_session(self, client: TestClient, project_id: str) -> None:
        questions = _list_questions(client, project_id)
        assert len(questions) > 1, "a fresh project should have several open areas"

        assert len(_sessions(client, project_id)) == 1

    def test_listing_again_opens_no_more(self, client: TestClient, project_id: str) -> None:
        """Questions already asked are returned, not re-asked — so a second
        call has nothing to record and needs no session at all."""

        _list_questions(client, project_id)
        before = len(_sessions(client, project_id))
        _list_questions(client, project_id)

        assert len(_sessions(client, project_id)) == before

    def test_an_open_conversation_is_joined(self, client: TestClient, project_id: str) -> None:
        """Questions go where the person is, not beside them.

        The failure this replaced: a project whose transcript was split in two,
        the person's own message in one half and everything asked of them in the
        other, each half looking complete on its own."""

        client.post(f"/v1/projects/{project_id}/sessions", json={"session_type": "discovery"})
        _list_questions(client, project_id)

        assert len(_sessions(client, project_id)) == 1

    def test_a_message_and_the_questions_share_a_transcript(
        self, client: TestClient, project_id: str
    ) -> None:
        """The whole point, end to end: what a person said and what they were
        asked are one conversation."""

        opened = client.post(
            f"/v1/projects/{project_id}/sessions", json={"session_type": "discovery"}
        ).json()
        session_id = str(opened["id"])
        client.post(
            f"/v1/sessions/{session_id}/messages",
            json={"content": "Notes become tasks.", "actor_type": "user", "message_type": "input"},
        )
        _list_questions(client, project_id)

        stored = client.get(f"/v1/sessions/{session_id}/messages").json()
        kinds = {m["actor_type"] for m in stored}

        assert {"user", "system"} <= kinds

    def test_the_questions_are_all_in_it(self, client: TestClient, project_id: str) -> None:
        questions = _list_questions(client, project_id)
        session_id = _sessions(client, project_id)[0]["id"]

        stored = client.get(f"/v1/sessions/{session_id}/messages").json()
        contents = {m["content"] for m in stored}

        assert all(q["question"] in contents for q in questions)
