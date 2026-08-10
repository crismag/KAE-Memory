"""How much of what was submitted actually became knowledge.

`PLANNING_MODEL.md` requires this and nothing implemented it:

    Content loss is reported separately and never folded in. While F-018 is
    open, a project whose extraction abandoned chunks must say so.

F-018 measured 29–65% of chunks abandoned across four real corpora, every one
`retry_budget_exhausted` after `verify_quotes` rejected a citation that was a
directory tree or a code fence. Everything downstream is computed over what
survived — and what survived looks exactly like a complete project.

This does not repair the loss. It makes the existing number honest, which is
what makes deferring the repair defensible rather than convenient.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.workspace_repositories import AgentRunRepository


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


def _abandon(
    memory: MemoryService,
    factory: sessionmaker[Session],
    project_id: str,
    key: str,
    role: AgentRole,
) -> None:
    """Drive a run to the state F-018 leaves behind.

    Failed once, then abandoned — the transition the worker performs when the
    retry budget is spent. There is no service method for it because nothing
    outside the worker should abandon a run, so this reaches the domain the way
    the worker does.
    """

    run = memory.start_run(ProjectId(project_id), role, key)
    failed = memory.fail_run(
        run.id, "retry_budget_exhausted", "item 3 cites a quote that does not occur"
    )
    moment = datetime.now(UTC)
    with factory() as session:
        AgentRunRepository(session).save(
            failed.abandon(moment, "3 attempts exhausted: verify_quotes"), moment
        )
        session.commit()


def test_a_project_that_lost_nothing_says_nothing(client: TestClient) -> None:
    """Silence when there is nothing to disclose.

    A banner on every project saying something might be missing is a banner
    nobody reads — and the previous slice was about not handing people more to
    sort out.
    """

    project = client.post("/v1/projects", json={"name": "Clean"}).json()

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["complete"] is True
    assert coverage["abandoned"] == 0


def test_a_project_that_lost_content_says_how_much(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    memory = MemoryService(factory)
    project = client.post("/v1/projects", json={"name": "Lossy"}).json()
    memory.start_run(ProjectId(project["id"]), AgentRole.DISCOVERY, "ok-1")
    _abandon(memory, factory, project["id"], "lost-1", AgentRole.DISCOVERY)

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["abandoned"] == 1
    assert coverage["complete"] is False


def test_only_runs_that_read_source_content_count(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """Review and architecture read what already exists.

    Abandoning one loses classification or a derived decision — not source
    content — and counting it here would report a loss that did not happen.
    """

    memory = MemoryService(factory)
    project = client.post("/v1/projects", json={"name": "Review lost"}).json()
    _abandon(memory, factory, project["id"], "review-lost", AgentRole.REVIEW)

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["total"] == 0
    assert coverage["complete"] is True


class TestReadinessSaysHowItWasClassified:
    """AUD-025, AUD-026. The half of PPA/REVIEW-01 that was never met.

    The worker already computed whether a review ran on a model, degraded
    partway, or fell back to the offline unambiguous-only rule — and wrote it
    into the run's `output_summary`, which a reader of `GET /readiness` never
    sees. So a percentage capped by the 16% offline ceiling looked exactly like
    one a model produced, and the finding's exit ("a degraded run is visibly
    degraded") was satisfied at the run and not at the number.
    """

    def test_a_project_with_no_review_says_so(self, client: TestClient) -> None:
        project = client.post("/v1/projects", json={"name": "Unreviewed"}).json()

        body = client.get(f"/v1/projects/{project['id']}/readiness").json()

        # Never reviewed is a third state, distinct from "reviewed offline".
        # Collapsing them would tell somebody their classification degraded
        # when nothing has run at all.
        assert body["classification"]["engine"] is None
        assert body["classification"]["degraded"] is False
        assert "No review has run" in body["classification"]["note"]

    def test_a_degraded_review_is_visible_where_the_number_is_read(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = client.post("/v1/projects", json={"name": "Degraded"}).json()
        run = memory.start_run(ProjectId(project["id"]), AgentRole.REVIEW, "aud-025-degraded")
        memory.complete_run(
            run.id,
            output_summary={"classification": "offline_by_kind_after_reviewer_error"},
        )

        body = client.get(f"/v1/projects/{project['id']}/readiness").json()

        assert body["classification"]["engine"] == "offline_by_kind_after_reviewer_error"
        assert body["classification"]["degraded"] is True
        # The note has to say the cause is not the project. A reader looking at
        # a low percentage will otherwise conclude their project is thin.
        assert "not about the project" in body["classification"]["note"]

    def test_a_model_review_is_not_reported_as_degraded(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = client.post("/v1/projects", json={"name": "Model"}).json()
        run = memory.start_run(ProjectId(project["id"]), AgentRole.REVIEW, "aud-025-model")
        memory.complete_run(run.id, output_summary={"classification": "reviewed_by_model"})

        body = client.get(f"/v1/projects/{project['id']}/readiness").json()

        assert body["classification"]["degraded"] is False


def test_a_truncated_document_is_not_reported_as_complete(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """AUD-024. The blind spot was exactly where the largest documents are.

    Coverage counts runs, and a chunk dropped at ingest never becomes one — so
    a document cut off at `max_chunks` reported `complete: true` while most of
    it had never been read. The truncation *was* disclosed, once, on the 202
    that accepted the document, and nothing correlated it with coverage
    afterwards.
    """

    project = client.post("/v1/projects", json={"name": "Truncated"}).json()
    long_document = ". ".join(f"Statement number {n} about this system" for n in range(200)) + "."

    accepted = client.post(
        f"/v1/projects/{project['id']}/documents",
        json={"document": "big.md", "text": long_document, "max_chunks": 2},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["truncated_chunks"] > 0, "this document must actually truncate"

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["not_ingested"] == accepted.json()["truncated_chunks"]
    # The assertion the finding is about.
    assert coverage["complete"] is False
    # And it is not miscounted as an extraction failure: nothing failed on this
    # content, nothing read it.
    assert coverage["abandoned"] == 0


class TestKnowledgeSaysWhatProducedIt:
    """AUD-008. A fixture-derived requirement looked exactly like a real one.

    With `KAE_EXTRACTION` unset, `DeterministicExtractionAdapter` splits text on
    punctuation and labels every sentence of twelve characters or more,
    defaulting to `requirement`. Those items were written with `source` set to
    the sentence — the same shape a model-extracted item has — and
    `model="deterministic-fixture"` landed only in the run's `output_summary`,
    which nothing downstream read.

    So a project could report hundreds of "extracted requirements" that were
    sentences cut on full stops, and no surface anywhere could tell a reader.
    """

    def test_the_trace_names_the_engine_that_produced_it(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = client.post("/v1/projects", json={"name": "Provenance"}).json()
        run = memory.start_run(ProjectId(project["id"]), AgentRole.REQUIREMENTS, "aud-008")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="requirement",
                    content="The system must record what a person confirmed.",
                    source="The system must record what a person confirmed.",
                )
            ],
            output_summary={"model": "deterministic-fixture", "items_written": 1},
        )

        trace = client.get(f"/v1/knowledge/{written[0].id}/trace").json()

        assert trace["produced_by"] == "deterministic-fixture"

    def test_a_model_produced_item_names_the_model(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = client.post("/v1/projects", json={"name": "Modelled"}).json()
        run = memory.start_run(ProjectId(project["id"]), AgentRole.REQUIREMENTS, "aud-008-model")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="requirement",
                    content="Individual founders are the first users.",
                    source="Individual founders are the first users.",
                )
            ],
            output_summary={"model": "claude-sonnet-4", "items_written": 1},
        )

        trace = client.get(f"/v1/knowledge/{written[0].id}/trace").json()

        # The point is the *difference*. Either value is fine; being unable to
        # tell them apart is what was wrong.
        assert trace["produced_by"] == "claude-sonnet-4"

    def test_a_run_that_recorded_no_engine_says_nothing_rather_than_guessing(
        self, client: TestClient, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = client.post("/v1/projects", json={"name": "Unstated"}).json()
        run = memory.start_run(ProjectId(project["id"]), AgentRole.REQUIREMENTS, "aud-008-none")
        written = memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(kind="goal", content="A stated goal.", source="A stated goal.")],
            output_summary={"items_written": 1},
        )

        trace = client.get(f"/v1/knowledge/{written[0].id}/trace").json()

        assert trace["produced_by"] is None
