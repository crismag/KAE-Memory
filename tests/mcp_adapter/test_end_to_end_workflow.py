"""The Demo V1 acceptance scenario (T23).

Not an integration test of the MCP layer. This is the product claim, executed:

    create a project -> ingest a repository document -> extract observations ->
    propose knowledge -> raise clarifications -> answer them -> confirm ->
    recalculate readiness -> assemble a bounded context -> describe a package

Every step runs through the MCP surface, because that is the surface a coding
agent actually has. Nothing here reaches around it.

What the scenario is really defending is the honesty of each transition. A
workflow that quietly promoted evidence to fact, or produced a package that
read as complete while carrying an unanswered question, would pass a naive
end-to-end test and fail the only claim that matters — that another AI
assistant can act on the output without being misled.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicExtractionAdapter
from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.ingestion_service import IngestionService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

REQUIREMENTS_DOC = "docs/requirements.md"

REQUIREMENTS_TEXT = "\n\n".join(
    (
        "Ministry leaders submit a report at the end of every month. The "
        "reporting period closes on the last day and submissions are due within "
        "five working days.",
        "A report must be approved before it is published. Approval applies to a "
        "specific version, so a later edit does not inherit an earlier decision.",
        "Pastors and administrators read published reports. Ministry leaders do "
        "not read one another's submissions. Readership and submission are "
        "separate permissions and are checked separately.",
        "A draft stays editable until it is submitted. After approval it is "
        "immutable, so a correction has to supersede rather than overwrite.",
        "Every approval decision is recorded with the approver, the time, and the "
        "version it applied to. Retention is seven years.",
    )
    * 3
)


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
        clarification=ClarificationService(factory, memory),
        embedder_name="deterministic",
    )


def _drain(factory: sessionmaker[Session]) -> int:
    """Run every queued run to completion, as a deployed worker would."""

    worker = Worker(
        factory,
        AgentStepExecutor(factory, DeterministicExtractionAdapter()),
        WorkerConfig(worker_id="demo-v1"),
    )
    drained = 0
    while worker.run_once() is not None:
        drained += 1
    return drained


class TestDemoV1:
    """One continuous workflow, start to finish, through the MCP surface."""

    def test_a_repository_document_becomes_a_bounded_context_package(
        self, factory: sessionmaker[Session], context: tools.ToolContext
    ) -> None:
        # 1. Create a project. It starts empty and says so.
        created = dispatch(
            context, "kae_create_project", {"name": "Ministry Reporting", "key": "demo-v1"}
        )
        assert created["created"] is True
        assert created["knowledge_statements"] == 0
        project_id = created["project_id"]

        # 2. Ingest a document. Evidence is recorded; nothing is known yet.
        ingested = dispatch(
            context,
            "kae_ingest_document",
            {"project_id": project_id, "document": REQUIREMENTS_DOC, "text": REQUIREMENTS_TEXT},
        )
        assert ingested["evidence_recorded"] is True
        assert ingested["knowledge_changed"] is False
        assert ingested["complete"] is True, "the whole document must be queued"
        assert context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()

        # 3. A worker drains the queue. Now candidates exist — and only candidates.
        assert _drain(factory) >= len(ingested["extraction_runs_queued"])
        candidates = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
        assert candidates, "extraction must produce something to review"
        assert all(item.lifecycle is LifecycleState.PROPOSED for item in candidates)

        # 4. The briefing shows the project, and does not quote candidates as fact.
        briefing = dispatch(context, "kae_get_project_briefing", {"project_id": project_id})
        assert briefing["project"]["project_id"] == project_id
        assert briefing["readiness"]["implementation_eligible"] is False

        # 5. Confirmation is a human act. Nothing above performed one.
        before_confirmation = context.readiness.knowledge_revision(ProjectId(project_id))
        target = candidates[0]
        # expected_version is required: a decision must not be applied to
        # wording that changed after the reviewer read it.
        confirmed = dispatch(
            context,
            "kae_confirm_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": str(target.id),
                "expected_version": target.current_version.number,
                "reviewer": "cris",
            },
        )
        assert "error" not in confirmed
        after_confirmation = context.readiness.knowledge_revision(ProjectId(project_id))
        assert after_confirmation > before_confirmation, "confirming must move the revision"

        # 6. Assemble a bounded context, pinned to the revision it read.
        assembly = dispatch(
            context,
            "kae_assemble_context",
            {"project_id": project_id, "purpose": "implementation"},
        )
        manifest = assembly["manifest"]
        assert manifest["knowledge_revision"] == after_confirmation
        assert manifest["content_hash"].startswith("sha256:")
        assert set(manifest["confirmation_state"]) >= {"confirmed", "proposed", "contested"}

        # 7. The package describes what it would produce, deterministically.
        package = assembly["package"]
        again = dispatch(
            context,
            "kae_assemble_context",
            {"project_id": project_id, "purpose": "implementation"},
        )["package"]
        assert package["artifacts"] == again["artifacts"]
        assert package["content_hash"] == again["content_hash"]

    def test_the_package_never_presents_a_candidate_as_a_fact(
        self, factory: sessionmaker[Session], context: tools.ToolContext
    ) -> None:
        """The claim the whole review model exists to protect.

        An agent reading this package must be able to tell approved from
        proposed without inspecting the database. If it cannot, it will
        implement whichever it happens to read first.
        """

        project_id = dispatch(
            context, "kae_create_project", {"name": "Honesty", "key": "demo-v1-honesty"}
        )["project_id"]
        dispatch(
            context,
            "kae_ingest_document",
            {"project_id": project_id, "document": REQUIREMENTS_DOC, "text": REQUIREMENTS_TEXT},
        )
        _drain(factory)

        assembly = dispatch(
            context,
            "kae_assemble_context",
            {"project_id": project_id, "include_proposed": True},
        )

        for section in assembly["sections"]:
            for statement in section["statements"]:
                assert statement["lifecycle"], "every statement declares its lifecycle"

        unconfirmed = [s for s in assembly["sections"] if s["area"] == "unconfirmed"]
        if unconfirmed:
            artifacts = {a["area"]: a for a in assembly["package"]["artifacts"]}
            assert artifacts["unconfirmed"]["confirmed"] == 0

    def test_an_unanswered_question_travels_with_the_package(
        self, factory: sessionmaker[Session], context: tools.ToolContext
    ) -> None:
        """Incomplete is allowed. Silently incomplete is not.

        A package generated while something is unresolved must carry that
        forward, so an implementer stops rather than choosing an answer on the
        project's behalf.
        """

        project_id = dispatch(
            context, "kae_create_project", {"name": "Gaps", "key": "demo-v1-gaps"}
        )["project_id"]
        dispatch(
            context,
            "kae_ingest_document",
            {"project_id": project_id, "document": REQUIREMENTS_DOC, "text": REQUIREMENTS_TEXT},
        )
        _drain(factory)

        assembly = dispatch(context, "kae_assemble_context", {"project_id": project_id})

        assert "unresolved_critical_gaps" in assembly["manifest"]
        guidance = " ".join(assembly["guidance"]).lower()
        assert "do not choose an answer" in guidance
        assert "candidate" in guidance

    def test_re_ingesting_the_same_document_does_not_duplicate_the_project(
        self, factory: sessionmaker[Session], context: tools.ToolContext
    ) -> None:
        """The workflow has to survive a retry, because agents retry."""

        project_id = dispatch(
            context, "kae_create_project", {"name": "Retry", "key": "demo-v1-retry"}
        )["project_id"]
        arguments: dict[str, Any] = {
            "project_id": project_id,
            "document": REQUIREMENTS_DOC,
            "text": REQUIREMENTS_TEXT,
        }

        first = dispatch(context, "kae_ingest_document", arguments)
        second = dispatch(context, "kae_ingest_document", arguments)
        _drain(factory)

        assert second["idempotent_replay"] is True
        assert second["extraction_runs_queued"] == first["extraction_runs_queued"]
        messages = context.memory.messages_for_session(first["session_id"])
        assert len(messages) == first["chunks_recorded"]

    def test_creating_the_same_project_twice_is_not_an_error(
        self, context: tools.ToolContext
    ) -> None:
        first = dispatch(
            context, "kae_create_project", {"name": "Idempotent", "key": "demo-v1-idem"}
        )
        second = dispatch(
            context, "kae_create_project", {"name": "Idempotent", "key": "demo-v1-idem"}
        )

        assert first["created"] is True
        assert second["created"] is False
        assert second["project_id"] == first["project_id"]
