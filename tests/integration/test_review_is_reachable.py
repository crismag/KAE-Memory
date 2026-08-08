"""EM-5 — the review pass can be asked for, so readiness can move.

Found by giving KAE four real projects. They produced 1,575 statements between
them and every one reported **0% readiness with all ten areas empty**, which
looked like a broken readiness model and was not.

The chain is: extraction writes knowledge, review assigns each statement to a
discovery area, readiness counts statements per area. The middle link is
`IngestionService.enqueue_review`. It existed, it was correct, its docstring
argued well for why it is separate from ingestion — and **its only caller in the
repository was a unit test.** Neither adapter exposed it, so no caller could
ever run it, so no area was ever populated.

This is the fourth capability found complete and unreachable. The pattern is
worth naming: a service method with tests passes every unit test, and contract
tests only check that declared capabilities exist — not that existing behaviour
is declared. The gap is invisible from both directions.
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
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import ProjectId

DOCUMENT = """
The system records invoices for freelance work. An invoice must be sent within
three days of a job finishing, and every invoice carries a client reference so
that payments can be reconciled. Only the freelancer who owns the account may
issue an invoice.
"""


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


@pytest.fixture
def project(client: TestClient, factory: sessionmaker[Session]) -> str:
    ReadinessService(factory).install_template()
    return str(client.post("/v1/projects", json={"name": "EM-5"}).json()["id"])


def _ingest(client: TestClient, project: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/projects/{project}/documents",
        json={"document": "invoicing.md", "text": DOCUMENT},
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


def _enqueue_review(client: TestClient, project: str, key: str = "review-1") -> Any:
    return client.post(f"/v1/projects/{project}/review/runs", json={"idempotency_key": key})


class TestTheCapabilityIsReachable:
    def test_review_can_be_queued_over_http(self, client: TestClient, project: str) -> None:
        """The whole finding, in one assertion.

        Before EM-5 there was no path here at all — not this one, not any other.
        """

        response = _enqueue_review(client, project)

        assert response.status_code == 202, response.text
        assert response.json()["run_id"]

    def test_it_queues_a_review_run_and_reviews_nothing_yet(
        self, client: TestClient, project: str, factory: sessionmaker[Session]
    ) -> None:
        """202 means queued. A worker does the work.

        Reporting otherwise would repeat the mistake ingestion is careful to
        avoid: three separate facts — accepted, queued, nothing changed.
        """

        _enqueue_review(client, project)

        runs = MemoryService(factory).runs_for_project(ProjectId(project))
        review = [r for r in runs if r.role is AgentRole.REVIEW]
        assert len(review) == 1
        assert review[0].status is RunStatus.PENDING

    def test_a_retry_with_the_same_key_does_not_queue_a_second_pass(
        self, client: TestClient, project: str, factory: sessionmaker[Session]
    ) -> None:
        """Review is a model call over every statement the project holds.

        A retried request without idempotency is a second bill and a second set
        of classifications for one intent, which is why the key is required
        rather than optional.
        """

        _enqueue_review(client, project, "same-key")
        _enqueue_review(client, project, "same-key")

        runs = MemoryService(factory).runs_for_project(ProjectId(project))
        assert len([r for r in runs if r.role is AgentRole.REVIEW]) == 1

    def test_the_key_is_required(self, client: TestClient, project: str) -> None:
        response = client.post(f"/v1/projects/{project}/review/runs", json={})

        assert response.status_code == 422

    def test_an_unknown_project_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/v1/projects/00000000-0000-0000-0000-000000000000/review/runs",
            json={"idempotency_key": "x"},
        )

        assert response.status_code == 404


class TestItSaysWhatItWillMiss:
    def test_it_reports_outstanding_extraction(self, client: TestClient, project: str) -> None:
        """Review reads what exists when it runs.

        Queued alongside extraction it would classify an almost empty project
        and report success, which is worse than refusing — the caller would
        believe readiness was measured.
        """

        _ingest(client, project)

        body = _enqueue_review(client, project).json()

        assert body["outstanding_extraction_runs"] > 0
        assert body["warnings"], "a pass that will miss most of the project must say so"

    def test_it_warns_rather_than_refuses(self, client: TestClient, project: str) -> None:
        """Reported, not blocked.

        Re-running review over a partially extracted project is legitimate — a
        caller may be re-classifying after a correction. Refusing would make the
        common case impossible to serve the uncommon one.
        """

        _ingest(client, project)

        assert _enqueue_review(client, project).status_code == 202

    def test_a_quiet_project_carries_no_warning(self, client: TestClient, project: str) -> None:
        body = _enqueue_review(client, project).json()

        assert body["outstanding_extraction_runs"] == 0
        assert body["warnings"] == []


class TestTheIngestionResponseNamesTheNextStep:
    def test_ingesting_tells_the_caller_review_is_required(
        self, client: TestClient, project: str
    ) -> None:
        """The omission that hid this for as long as it was hidden.

        The ingestion response listed draining extraction and confirming
        candidates, and never mentioned review. A caller following it exactly
        ends with a project reporting 0% and no reason given — which is what
        happened, four times, to me.
        """

        from kae_memory.mcp import tools

        source = tools.__doc__ or ""
        payload = tools._ingestion_payload.__doc__ or ""
        assert source is not None and payload is not None

        import inspect

        rendered = inspect.getsource(tools._ingestion_payload)
        assert "kae_enqueue_review" in rendered, (
            "the ingestion response must name review as the next step, or the "
            "next caller loses the same day to the same gap"
        )
