"""One review path, two engines.

The worker owns the review run either way, so it keeps its lease, checkpoint,
and recovery. What changes is who proposes the classifications: an offline rule
that refuses ambiguous kinds, or a model that is asked precisely for them.

What does not change is the contradiction policy. Neither engine records one.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.review import ReviewRequest, UnverifiableReviewError
from kae_memory.agents.review_adapter import DeterministicReviewAdapter
from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.worker.execution import AgentStepExecutor, default_reviewer
from kae_memory.worker.runner import Worker, WorkerConfig

SEED = [
    ("actor", "Ministry leaders submit monthly reports."),
    ("requirement", "Only an authorised approver may approve a report."),
    ("rule", "A submitter cannot approve their own report."),
]


def _seed(memory: MemoryService, project_id: ProjectId, key: str) -> None:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in SEED
        ],
    )
    for item in items:
        memory.confirm_knowledge(item.id)


def _review(factory: sessionmaker[Session], project_id: ProjectId, reviewer: object) -> AgentRun:
    MemoryService(factory).enqueue_run(project_id, AgentRole.REVIEW, "review-1")
    executed = Worker(
        factory,
        AgentStepExecutor(factory, object(), reviewer),  # type: ignore[arg-type]
        WorkerConfig(worker_id="reviewer"),
    ).run_once()
    assert executed is not None, "a run was enqueued, so one must have been claimed"
    return executed


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, ReadinessService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="unified-review")
    _seed(memory, proj.id, "seed-1")
    return memory, readiness, proj.id


class TestWithoutAReviewer:
    def test_only_unambiguous_kinds_are_classified(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """Refusing to guess is the point when nothing can judge."""

        _, readiness, project_id = project

        executed = _review(factory, project_id, None)

        assert executed.status is RunStatus.SUCCEEDED
        assert (executed.output_summary or {})["classification"] == "offline_by_kind"
        assert [link.area_key for link in readiness.area_links(project_id)] == [
            "users_and_stakeholders"
        ]


class TestWithAReviewer:
    def test_the_run_reports_which_engine_classified(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """A reader must be able to tell a model's judgement from a rule."""

        _, _, project_id = project

        executed = _review(factory, project_id, DeterministicReviewAdapter())

        assert (executed.output_summary or {})["classification"] == "reviewed_by_model"
        assert (executed.output_summary or {})["prompt_version"] == "review.v1"

    def test_classification_is_still_attributable(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        _, readiness, project_id = project

        executed = _review(factory, project_id, DeterministicReviewAdapter())

        links = readiness.area_links(project_id)
        assert links
        assert all(link.assigned_by_agent_run_id == executed.id for link in links)

    def test_a_contradiction_is_proposed_never_recorded(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The policy both engines share (ADR-0015)."""

        memory = MemoryService(factory)
        readiness = ReadinessService(factory)
        readiness.install_template()
        proj = memory.create_project("Conflicts", key="unified-conflict")
        run = memory.start_run(proj.id, AgentRole.REQUIREMENTS, "seed-conflict")
        items = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="rule", content="A submitter can approve their own report.", source="s"
                ),
                WriteKnowledgeRequest(
                    kind="rule", content="A submitter cannot approve their own report.", source="s"
                ),
            ],
        )
        for item in items:
            memory.confirm_knowledge(item.id)

        executed = _review(factory, proj.id, DeterministicReviewAdapter())

        assert (executed.output_summary or {})["proposed_contradictions"] == 1
        assert readiness.calculate(proj.id).unresolved_contradiction_count == 0


class TestResilience:
    def test_a_reviewer_failure_falls_back_rather_than_failing_the_run(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """Losing the ambiguous cases costs coverage a human can still supply.

        Losing the run would cost the unambiguous ones too, and take the lease
        and checkpoint with it.
        """

        _, readiness, project_id = project

        def fabricating(request: ReviewRequest) -> object:
            return {
                "findings": [
                    {
                        "kind": "area_classification",
                        "statement_quote": "A statement nobody recorded.",
                        "area_key": "functional_requirements",
                    }
                ]
            }

        executed = _review(factory, project_id, DeterministicReviewAdapter(fabricating))

        assert executed.status is RunStatus.SUCCEEDED
        assert (executed.output_summary or {})[
            "classification"
        ] == "offline_by_kind_after_reviewer_error"
        assert (executed.output_summary or {})[
            "reviewer_error"
        ] == UnverifiableReviewError.error_code
        assert [link.area_key for link in readiness.area_links(project_id)] == [
            "users_and_stakeholders"
        ]

    def test_an_impossible_pairing_is_dropped_not_fatal(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        _, readiness, project_id = project

        def misfiles(request: ReviewRequest) -> object:
            goal = next(s for s in request.statements if s.kind == "actor")
            return {
                "findings": [
                    {
                        "kind": "area_classification",
                        "statement_quote": goal.text,
                        "area_key": "quality_attributes",
                    }
                ]
            }

        executed = _review(factory, project_id, DeterministicReviewAdapter(misfiles))

        assert executed.status is RunStatus.SUCCEEDED
        assert len((executed.output_summary or {})["rejected_assignments"]) == 1
        assert readiness.area_links(project_id) == ()


class TestConfiguration:
    def test_the_engine_is_selected_by_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAE_REVIEW", "off")
        assert default_reviewer() is None

        monkeypatch.setenv("KAE_REVIEW", "deterministic")
        assert isinstance(default_reviewer(), DeterministicReviewAdapter)

    def test_review_is_on_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A cloned repository walks the whole chain with no configuration."""

        monkeypatch.delenv("KAE_REVIEW", raising=False)
        assert default_reviewer() is not None
