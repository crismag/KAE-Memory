"""The document ingestion surface (T19).

Ingestion records evidence and queues the runs that will read it. What it must
never do is imply that reading has happened.

The response therefore separates three facts — text recorded, extraction
queued, knowledge unchanged — and every assertion here defends that separation.
A caller that read "recorded" as "known" would plan against statements no run
has produced and no person has confirmed, which is the failure the whole review
model exists to prevent.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.ingestion_service import IngestionService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.mcp import tools
from kae_memory.mcp.errors import CapabilityUnavailableError, InvalidArgumentError
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

DOCUMENT = "docs/requirements.md"

_SECTIONS = (
    "Ministry leaders submit a report at the end of every month. The reporting "
    "period closes on the last day and submissions are due within five working "
    "days. A leader who misses the window may still submit, and the record shows "
    "that it was late rather than hiding it.",
    "A report must be approved before it is published. The approver has not been "
    "decided, and nothing should assume one. Approval applies to a specific "
    "version, so a later edit does not inherit an earlier decision.",
    "Pastors and administrators read published reports. Ministry leaders do not "
    "read one another's submissions. Readership and submission are separate "
    "permissions and are checked separately.",
    "A draft stays editable until it is submitted. After approval it is "
    "immutable, so a correction has to supersede rather than overwrite. The "
    "superseded version stays readable, because an audit trail that forgets is "
    "not an audit trail.",
    "Every approval decision is recorded with the approver, the time, and the "
    "version it applied to. Retention is seven years. Nothing in the system "
    "deletes a decision, and an administrator cannot edit one after the fact.",
)

TEXT = "\n\n".join(_SECTIONS * 6)
"""Long enough to split at the default 500-token target.

Truncation and multi-span provenance are only reachable on a document that
actually chunks, and a sample that fits in one span would test neither.
"""


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    memory = MemoryService(factory)
    return tools.ToolContext(
        memory=memory,
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        ingestion=IngestionService(factory, memory),
        assembly=AssemblyService(factory),
        embedder_name="deterministic",
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Ministry Reporting", key="ministry").id)


def _ingest(context: tools.ToolContext, project_id: str, **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "project_id": project_id,
        "document": DOCUMENT,
        "text": TEXT,
    }
    arguments.update(overrides)
    return dispatch(context, "kae_ingest_document", arguments)


class TestWhatIngestionClaims:
    def test_evidence_is_recorded_and_knowledge_is_not(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The three facts stay separate, and only one of them is 'yes'."""

        payload = _ingest(context, project_id)

        assert payload["evidence_recorded"] is True
        assert payload["knowledge_changed"] is False
        assert payload["workflow_state"] == "extraction_queued"

    def test_no_knowledge_exists_after_ingesting(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The claim is checked against the database, not just the response."""

        _ingest(context, project_id)

        assert context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()

    def test_the_runs_are_queued_not_finished(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Queued work is not done work, and the response must not blur that."""

        payload = _ingest(context, project_id)

        assert payload["extraction_runs_queued"]
        assert payload["outstanding_runs"] == len(payload["extraction_runs_queued"])
        runs = context.memory.runs_for_project(ProjectId(project_id))
        assert {run.status for run in runs} == {RunStatus.PENDING}

    def test_next_steps_name_the_person(self, context: tools.ToolContext, project_id: str) -> None:
        joined = " ".join(_ingest(context, project_id)["next_steps"]).lower()

        assert "worker" in joined
        assert "confirm" in joined


class TestEvidenceIsStoredVerbatim:
    def test_spans_are_recorded_as_messages(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A statement traces to a stored span, so the span has to be stored."""

        payload = _ingest(context, project_id)
        messages = context.memory.messages_for_session(payload["session_id"])

        assert len(messages) == payload["chunks_recorded"]
        combined = " ".join(message.content for message in messages)
        assert "The approver has not been decided" in combined

    def test_the_document_name_is_carried(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        assert _ingest(context, project_id)["document"] == DOCUMENT


class TestRetryIsSafe:
    def test_re_ingesting_the_same_document_does_not_read_it_twice(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        first = _ingest(context, project_id)
        second = _ingest(context, project_id)

        assert second["idempotent_replay"] is True
        assert second["chunks_recorded"] == first["chunks_recorded"]
        assert second["extraction_runs_queued"] == first["extraction_runs_queued"]
        assert len(context.memory.runs_for_project(ProjectId(project_id))) == len(
            first["extraction_runs_queued"]
        )


class TestTruncationIsReportedNotHidden:
    def test_an_unread_remainder_is_stated(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Silently dropping the tail of a document is the worst available failure.

        The rest of the workflow cannot tell an absent requirement from one that
        was never read, so the omission has to be said out loud.
        """

        payload = _ingest(context, project_id, max_chunks=1)

        assert payload["complete"] is False
        assert payload["truncated_chunks"] >= 1
        assert any("not queued" in warning for warning in payload["warnings"])

    def test_a_complete_ingestion_says_so(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _ingest(context, project_id)

        assert payload["complete"] is True
        assert payload["truncated_chunks"] == 0


class TestArgumentValidation:
    def test_a_document_name_is_required(self, context: tools.ToolContext, project_id: str) -> None:
        """Evidence without a source cannot be traced, so it is refused."""

        with pytest.raises(InvalidArgumentError):
            tools.kae_ingest_document(context, project_id, "  ", TEXT)

    def test_empty_text_is_refused(self, context: tools.ToolContext, project_id: str) -> None:
        with pytest.raises(InvalidArgumentError):
            tools.kae_ingest_document(context, project_id, DOCUMENT, "   ")

    def test_max_chunks_must_be_positive(self, context: tools.ToolContext, project_id: str) -> None:
        with pytest.raises(InvalidArgumentError):
            tools.kae_ingest_document(context, project_id, DOCUMENT, TEXT, max_chunks=0)

    def test_an_unknown_project_is_structured(self, context: tools.ToolContext) -> None:
        payload = _ingest(context, "00000000-0000-0000-0000-000000000000")

        assert payload["error"] == "project_not_found"

    def test_the_capability_gap_is_reported_when_unwired(
        self, factory: sessionmaker[Session]
    ) -> None:
        readiness = ReadinessService(factory)
        readiness.install_template()
        bare = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
        )
        project = bare.memory.create_project("Unwired", key="unwired")

        with pytest.raises(CapabilityUnavailableError):
            tools.kae_ingest_document(bare, str(project.id), DOCUMENT, TEXT)


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        declared = {definition["name"] for definition in TOOL_DEFINITIONS}

        assert "kae_ingest_document" in declared

    def test_the_schema_is_strict(self) -> None:
        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_ingest_document")
        schema = definition["inputSchema"]

        assert schema["additionalProperties"] is False
        # `project_id` left `required` with T25.2 — a project may be named by
        # key. What a document ingestion cannot do without is the document.
        assert set(schema["required"]) == {"document", "text"}
        assert "project_key" in schema["properties"]

    def test_the_description_does_not_promise_knowledge(self) -> None:
        """The surface must not advertise what the response then denies."""

        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_ingest_document")

        assert "queued" in definition["description"]
        assert "no knowledge has changed" in definition["description"]


class TestIngestionFeedsExtraction:
    def test_extraction_produces_proposed_knowledge_from_ingested_evidence(
        self, factory: sessionmaker[Session], context: tools.ToolContext, project_id: str
    ) -> None:
        """T20: the queued runs, once drained, yield candidates — not facts.

        This is the join between ingestion and the review model. Draining the
        queue must produce knowledge that is *proposed*: if a document could
        confirm its own contents, ingesting a file would silently become the
        project's opinion.
        """

        from kae_memory.agents import DeterministicExtractionAdapter
        from kae_memory.worker.execution import AgentStepExecutor
        from kae_memory.worker.runner import Worker, WorkerConfig

        _ingest(context, project_id)

        worker = Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter()),
            WorkerConfig(worker_id="ingestion-test"),
        )
        while worker.run_once() is not None:
            pass

        items = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
        assert items, "draining the queue must produce candidates"
        assert all(item.lifecycle is LifecycleState.PROPOSED for item in items), (
            "ingested evidence may propose, never confirm"
        )

    def test_each_candidate_traces_to_an_ingested_span(
        self, factory: sessionmaker[Session], context: tools.ToolContext, project_id: str
    ) -> None:
        """Provenance is the point: a candidate names the span it came from."""

        from kae_memory.agents import DeterministicExtractionAdapter
        from kae_memory.worker.execution import AgentStepExecutor
        from kae_memory.worker.runner import Worker, WorkerConfig

        payload = _ingest(context, project_id)
        span_ids = {
            str(message.id)
            for message in context.memory.messages_for_session(payload["session_id"])
        }

        worker = Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter()),
            WorkerConfig(worker_id="provenance-test"),
        )
        while worker.run_once() is not None:
            pass

        items = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
        for item in items:
            links = context.memory.provenance_for_item(item.id)
            sources = {str(link.message_id) for link in links if link.message_id}
            assert sources & span_ids, f"{item.id} does not trace to an ingested span"
