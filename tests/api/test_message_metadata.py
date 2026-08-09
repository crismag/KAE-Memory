"""Structure about a message, readable back.

`Message.metadata` has always existed in the domain and been persisted. The HTTP
surface accepted neither and returned neither, so anything a caller knew about a
turn — which statements it reflected, what it recommended doing next — had
nowhere durable to live.

The consequence was small and compounding: a client kept its own copy, and the
copy lived exactly as long as the tab. A recommendation reasoned once had to be
either recomputed or lost on refresh, and recomputing means another model call
for something already decided.
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


def _session(client: TestClient) -> str:
    project = client.post("/v1/projects", json={"name": "Metadata"}).json()
    return str(
        client.post(
            f"/v1/projects/{project['id']}/sessions", json={"session_type": "discovery"}
        ).json()["id"]
    )


def test_a_turn_can_record_what_it_recommended_and_read_it_back(client: TestClient) -> None:
    """The reason this exists.

    A ranked next action is reasoned once, per turn, from that turn's
    projection. Recomputing it on every page load would be a model call to
    re-decide something already decided; keeping it only in the browser loses it
    on refresh.
    """

    session_id = _session(client)
    posted = client.post(
        f"/v1/sessions/{session_id}/messages",
        json={
            "content": "So the problem is that notes scatter.",
            "actor_type": "agent",
            # Named, because an agent message must say what produced it — a
            # turn stored with no attributable author is a model's output
            # sitting in the evidence log as though nobody wrote it.
            "actor_id": "cie",
            "message_type": "question",
            "metadata": {
                "next_action": [
                    {"kind": "review", "label": "Review 3 requirements", "reason": "oldest work"}
                ],
                "provenance": ["know-1", "know-2"],
                "projection_fingerprint": "fp-abc",
            },
        },
    )

    assert posted.status_code == 201, posted.text
    assert posted.json()["metadata"]["provenance"] == ["know-1", "know-2"]

    listed = client.get(f"/v1/sessions/{session_id}/messages").json()
    assert listed[0]["metadata"]["next_action"][0]["label"] == "Review 3 requirements"
    assert listed[0]["metadata"]["projection_fingerprint"] == "fp-abc"


def test_a_message_without_metadata_carries_an_empty_mapping(client: TestClient) -> None:
    """Absent, not null. A caller reading `.metadata["x"]` on every message
    should not have to check whether the field exists first."""

    session_id = _session(client)
    client.post(f"/v1/sessions/{session_id}/messages", json={"content": "Plain."})

    assert client.get(f"/v1/sessions/{session_id}/messages").json()[0]["metadata"] == {}


def test_metadata_is_not_evidence(client: TestClient) -> None:
    """It is the caller's own record, never a way to write knowledge.

    Extraction reads `content`. A client that could seed candidate knowledge
    through a metadata field would be writing to the project without saying so —
    the same failure EM-2 fixed for message purpose, arriving through a
    different door.
    """

    session_id = _session(client)
    client.post(
        f"/v1/sessions/{session_id}/messages",
        json={
            "content": "Plain.",
            "metadata": {"content": "Ministry leaders submit reports.", "kind": "actor"},
        },
    )

    stored = client.get(f"/v1/sessions/{session_id}/messages").json()[0]
    assert stored["content"] == "Plain.", "the message is its content, not its metadata"
