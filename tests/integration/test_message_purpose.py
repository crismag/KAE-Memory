"""EM-2 — a message can be recorded without being interpreted.

Recording a message enqueued discovery extraction, unconditionally, for every
human message. A browser suite proving the round trip works therefore wrote
twelve copies of "It is only ever me, on my own phone." into a real project's
candidate knowledge, and nothing in the system could have known not to: there
was no way for a caller to say *store this, do not interpret it*.

The half of this that already shipped is worth stating so nobody rebuilds it.
Idempotency is mandatory and proven under concurrency
(`tests/application/test_message_idempotency.py`), and T24 classifies submitted
*observations* into retention tiers. Neither reaches this route. What was
missing is a declaration, on the conversational path, made by the caller before
anything reads the text.

**The gate is on the declaration, never on the words.** A model asked whether a
sentence "looks like a test" would be wrong about real requirements that mention
testing, and would be wrong invisibly.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService
from kae_memory.domain.identifiers import ProjectId, SessionId
from kae_memory.domain.workspace import MessagePurpose, SessionType

ROUND_TRIP = "connectivity check 12345, ignore"
REAL = "Every requirement must have an automated test before release."


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def session_id(factory: sessionmaker[Session]) -> str:
    memory = MemoryService(factory)
    project = ProjectId(str(memory.create_project("EM-2").id))
    return str(memory.open_session(project, SessionType.DISCOVERY).id)


def _record(client: TestClient, session_id: str, content: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"/v1/sessions/{session_id}/messages",
        json={"content": content, "actor_type": "user", **extra},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _runs(factory: sessionmaker[Session], session_id: str) -> int:
    """How many extraction runs this session has queued."""

    memory = MemoryService(factory)
    stored = memory.messages_for_session(SessionId(session_id))
    project = stored[0].project_id
    return len(memory.runs_for_project(project))


class TestADiagnosticIsStoredAndNotInterpreted:
    def test_it_produces_no_extraction_run(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        _record(client, session_id, ROUND_TRIP, purpose="diagnostic")

        assert _runs(factory, session_id) == 0

    def test_it_is_still_recorded_verbatim(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """Excluded is not discarded.

        "We never received it" and "we received it and did not interpret it" are
        different answers to a support question, and a system that drops the
        second silently can only give the first.
        """

        _record(client, session_id, ROUND_TRIP, purpose="diagnostic")

        stored = MemoryService(factory).messages_for_session(SessionId(session_id))
        assert [m.content for m in stored] == [ROUND_TRIP]

    def test_the_exclusion_is_readable_afterwards(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """Auditable, which means the reason survives on the record itself.

        Without this a support question — "why is this sentence not in the
        requirements?" — has no answer except re-running the pipeline and
        hoping.
        """

        _record(client, session_id, ROUND_TRIP, purpose="diagnostic")

        (stored,) = MemoryService(factory).messages_for_session(SessionId(session_id))
        assert stored.purpose is MessagePurpose.DIAGNOSTIC
        assert stored.is_interpreted is False

    def test_conversation_control_is_excluded_too(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        _record(
            client, session_id, "go back to the previous question", purpose="conversation_control"
        )

        assert _runs(factory, session_id) == 0


class TestProjectInputIsUnaffected:
    def test_the_default_is_interpreted(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """The default must not change.

        Any default other than `project_input` silently stops interpreting real
        conversations — a failure that looks exactly like extraction being
        broken, and would be found by someone wondering why a project learned
        nothing all week.
        """

        _record(client, session_id, "Invoices go out within three days.")

        assert _runs(factory, session_id) == 1

    def test_a_requirement_about_testing_is_still_extracted(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """The case a keyword filter gets wrong.

        This sentence contains "test" and is a genuine requirement. Anything
        deciding by inspecting the words drops it, and drops it invisibly.
        """

        _record(client, session_id, REAL)

        assert _runs(factory, session_id) == 1

    def test_saying_project_input_explicitly_is_the_same(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        _record(
            client, session_id, "Reports are approved before publication.", purpose="project_input"
        )

        assert _runs(factory, session_id) == 1


class TestTheDeclarationIsValidated:
    def test_an_unknown_purpose_is_refused(self, client: TestClient, session_id: str) -> None:
        """Refused rather than coerced.

        A typo'd purpose accepted as `project_input` would extract from a
        message somebody deliberately marked, and accepted as `diagnostic` would
        silently stop extracting from real ones. Neither is recoverable by the
        caller, because neither is reported.
        """

        response = client.post(
            f"/v1/sessions/{session_id}/messages",
            json={"content": "hello", "actor_type": "user", "purpose": "diagnostik"},
        )

        assert response.status_code == 422


class TestReplayStillEnqueuesNothing:
    def test_a_replayed_project_message_does_not_extract_twice(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """The pre-existing guarantee, re-proven alongside the new one.

        These two conditions guard the same enqueue and could disagree — a
        refactor satisfying one while dropping the other would double every
        retried message's candidates, which is the fault EM-2 exists to reduce.
        """

        _record(client, session_id, "Invoices carry a client reference.", idempotency_key="k1")
        _record(client, session_id, "Invoices carry a client reference.", idempotency_key="k1")

        assert _runs(factory, session_id) == 1

    def test_a_replayed_diagnostic_also_enqueues_nothing(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        _record(client, session_id, ROUND_TRIP, purpose="diagnostic", idempotency_key="k2")
        _record(client, session_id, ROUND_TRIP, purpose="diagnostic", idempotency_key="k2")

        assert _runs(factory, session_id) == 0


class TestHistoricalMessagesAreProjectInput:
    def test_a_null_purpose_reads_as_project_input(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """Revision 0022 adds the column nullable and backfills nothing.

        Every message written before EM-2 was project input, so NULL is accurate
        rather than unknown — and a consumer must not have to special-case the
        rows that predate the feature. Simulated by clearing the column, which
        is exactly the state an upgraded database is in.
        """

        from sqlalchemy import text

        _record(client, session_id, "Recorded before purposes existed.")
        with factory() as db:
            db.execute(text("UPDATE messages SET purpose = NULL"))
            db.commit()

        stored = MemoryService(factory).messages_for_session(SessionId(session_id))
        assert stored
        assert all(m.purpose is MessagePurpose.PROJECT_INPUT for m in stored)
        assert all(m.is_interpreted for m in stored)

    def test_an_unrecognised_stored_value_is_not_interpreted(
        self, client: TestClient, factory: sessionmaker[Session], session_id: str
    ) -> None:
        """A value written by a newer version, read by an older one.

        NULL and "something I do not recognise" must not resolve the same way.
        NULL is a message from before the feature and was project input; an
        unknown string is a caller declaring *something*, and the safe reading
        of a declaration you cannot parse is not "extract from it anyway".
        """

        from sqlalchemy import text

        _record(client, session_id, "Recorded by a future version.")
        with factory() as db:
            db.execute(text("UPDATE messages SET purpose = 'telemetry_probe'"))
            db.commit()

        (stored,) = MemoryService(factory).messages_for_session(SessionId(session_id))
        assert stored.is_interpreted is False
