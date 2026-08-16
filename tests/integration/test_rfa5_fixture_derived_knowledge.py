"""RFA-5 — fixture-derived knowledge is distinguishable from the real thing.

The acceptance journey for `AUD-008`, run against real services and a real
database:

    extract with the deterministic adapter
      → the knowledge records which adapter produced it
      → a reader can tell it apart from model-extracted knowledge
      → readiness computed over it is labelled offline

## Why this is a journey and not three unit tests

Each link was already checked somewhere. What no test asked is whether the
distinction **survives to a reader** — and it did not. The first two links held:
`ExtractionResult.model` reaches the run summary, and `BlueprintService.trace`
reads it back. The third did not, and this file is why the third now exists.

`DeterministicReviewAdapter` satisfies `ReviewPort`, so a review run against
recorded payloads reported `classification: reviewed_by_model` — the fixture's
own class docstring said so, in those words, and nothing acted on it. Readiness
then carried that word out through `GET /readiness` to somebody deciding whether
to trust a percentage. Same substitution `semantic` was fixed for on rule-based
output (`AUD-007`), one layer up: `AUD-039`.

## The shape of the guard

Every assertion here is about **what a reader is told**, not about what the code
computes. A test that inspected `adapter.model` would have passed throughout the
period the product was wrong.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.deterministic import DeterministicExtractionAdapter
from kae_memory.agents.review import ReviewRequest
from kae_memory.agents.review_adapter import DeterministicReviewAdapter
from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.workspace import SessionType
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

SEED = [
    ("actor", "Ministry leaders submit monthly reports."),
    ("requirement", "Only an authorised approver may approve a report."),
    ("rule", "A submitter cannot approve their own report."),
]


class Judging:
    """A reviewer that claims judgement, standing in for the Bedrock adapter.

    It returns the fixture's findings, because what is under test is the label
    the run publishes rather than the quality of the classification. It differs
    from `DeterministicReviewAdapter` in exactly the one respect that should
    change the label — which is the point.
    """

    judges = True
    model = "a-model-that-judges"

    def review(self, request: ReviewRequest) -> Any:
        return DeterministicReviewAdapter().review(request)


@pytest.fixture
def memory(factory: sessionmaker[Session]) -> MemoryService:
    return MemoryService(factory)


@pytest.fixture
def readiness(factory: sessionmaker[Session]) -> ReadinessService:
    service = ReadinessService(factory)
    service.install_template()
    return service


@pytest.fixture
def project(memory: MemoryService, readiness: ReadinessService) -> ProjectId:
    return memory.create_project("Ministry Reporting", key="rfa5").id


def _extract(
    factory: sessionmaker[Session], memory: MemoryService, project_id: ProjectId
) -> AgentRun:
    """Run extraction the way the worker does, through the fixture adapter."""

    working = memory.open_session(project_id, SessionType.DISCOVERY)
    message = memory.record_message(project_id, working.id, " ".join(text for _, text in SEED))
    memory.enqueue_run(
        project_id,
        AgentRole.REQUIREMENTS,
        "rfa5-extract",
        input_context={"message_id": str(message.message.id)},
    )
    executed = Worker(
        factory,
        AgentStepExecutor(factory, DeterministicExtractionAdapter()),
        WorkerConfig(worker_id="rfa5"),
    ).run_once()
    assert executed is not None, "a run was enqueued, so one must have been claimed"
    return executed


def _seed_confirmed(memory: MemoryService, project_id: ProjectId) -> None:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "rfa5-seed")
    for item in memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind=k, content=c, source="seed") for k, c in SEED],
        output_summary={"model": "deterministic-fixture", "items_written": len(SEED)},
    ):
        memory.confirm_knowledge(item.id)


def _review(factory: sessionmaker[Session], project_id: ProjectId, reviewer: object) -> AgentRun:
    MemoryService(factory).enqueue_run(project_id, AgentRole.REVIEW, "rfa5-review")
    executed = Worker(
        factory,
        AgentStepExecutor(factory, object(), reviewer),  # type: ignore[arg-type]
        WorkerConfig(worker_id="rfa5-reviewer"),
    ).run_once()
    assert executed is not None
    return executed


class TestTheKnowledgeRecordsWhatProducedIt:
    def test_extraction_writes_the_adapter_onto_the_run(
        self, factory: sessionmaker[Session], memory: MemoryService, project: ProjectId
    ) -> None:
        executed = _extract(factory, memory, project)

        assert executed.status is RunStatus.SUCCEEDED
        assert (executed.output_summary or {})["model"] == "deterministic-fixture"

    def test_a_reader_can_tell_fixture_from_model_without_knowing_the_run(
        self, factory: sessionmaker[Session], memory: MemoryService, project: ProjectId
    ) -> None:
        """The reader's route: trace the statement, not the run that made it.

        A person looking at a requirement has the statement. If telling fixture
        from model required already knowing which run produced it, the
        distinction would exist and be unreachable — which is the shape of half
        the audit's findings.
        """

        executed = _extract(factory, memory, project)
        items = memory.knowledge_produced_by(executed.id)
        assert items, "the fixture extracts from the seeded message"

        trace = BlueprintService(factory).trace(items[0].id)

        assert trace is not None
        assert trace.produced_by == "deterministic-fixture"

    def test_a_model_extracted_statement_reads_differently(
        self, factory: sessionmaker[Session], memory: MemoryService, project: ProjectId
    ) -> None:
        """The other half of a distinction: it has to distinguish.

        Asserting only the fixture case would pass against a field hardcoded to
        the fixture's name — which is the failure mode this whole file is about.
        """

        run = memory.start_run(project, AgentRole.REQUIREMENTS, "rfa5-model")
        written = memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(kind="goal", content="Reports are approved once.", source="s")],
            output_summary={"model": "global.anthropic.claude-sonnet-4-6", "items_written": 1},
        )

        trace = BlueprintService(factory).trace(written[0].id)

        assert trace is not None
        assert trace.produced_by == "global.anthropic.claude-sonnet-4-6"
        assert trace.produced_by != "deterministic-fixture"


class TestReadinessSaysHowItWasClassified:
    def test_a_fixture_reviewer_is_not_reported_as_a_model(
        self,
        factory: sessionmaker[Session],
        memory: MemoryService,
        readiness: ReadinessService,
        project: ProjectId,
    ) -> None:
        """`AUD-039`, at the surface a person reads.

        Before this, a deployment running `KAE_REVIEW=deterministic` published
        `reviewed_by_model` beside its percentage. The number was capped by the
        offline ceiling and the label said a model had produced it.
        """

        _seed_confirmed(memory, project)
        _review(factory, project, DeterministicReviewAdapter())

        report = readiness.classification(project)

        assert report.engine == "reviewed_by_fixture"
        assert report.by_model is False
        assert report.by_fixture is True
        assert report.degraded is True, "the number did not come from a model"

    def test_a_model_reviewer_still_gets_the_word(
        self,
        factory: sessionmaker[Session],
        memory: MemoryService,
        readiness: ReadinessService,
        project: ProjectId,
    ) -> None:
        """Honesty has to cost the fixture and not the model.

        A label that said `reviewed_by_fixture` everywhere would also pass the
        test above, and would make the deployed system — which runs
        `KAE_REVIEW=bedrock` — understate what it did.
        """

        _seed_confirmed(memory, project)
        _review(factory, project, Judging())

        report = readiness.classification(project)

        assert report.engine == "reviewed_by_model"
        assert report.by_model is True
        assert report.by_fixture is False
        assert report.degraded is False

    def test_no_reviewer_at_all_still_reads_differently_from_both(
        self,
        factory: sessionmaker[Session],
        memory: MemoryService,
        readiness: ReadinessService,
        project: ProjectId,
    ) -> None:
        """Three states, not two. *Never reviewed* is a fourth.

        `offline_by_content` is a deployment with no review engine configured;
        `None` is a project no review has run over. Collapsing them would tell
        somebody their project had been classified as far as it could be, when
        nothing had looked at it.
        """

        _seed_confirmed(memory, project)
        before = readiness.classification(project)
        assert before.engine is None

        _review(factory, project, None)

        report = readiness.classification(project)

        assert report.engine == "offline_by_content"
        assert report.by_model is False
        assert report.by_fixture is False
        assert report.degraded is True

    def test_the_label_reaches_the_readiness_response(
        self,
        factory: sessionmaker[Session],
        memory: MemoryService,
        readiness: ReadinessService,
        project: ProjectId,
    ) -> None:
        """The conservation check. Computed carefully and read by nothing was
        the estate's largest recurring finding, so the journey ends at the API
        rather than at the service that computes the label.
        """

        from kae_memory.api.schemas import ReadinessResponse

        _seed_confirmed(memory, project)
        _review(factory, project, DeterministicReviewAdapter())

        snapshot = readiness.calculate(project)
        body = ReadinessResponse.of(
            snapshot,
            current_revision=snapshot.knowledge_revision,
            classification=readiness.classification(project),
        ).model_dump()

        assert body["classification"]["engine"] == "reviewed_by_fixture"
        assert body["classification"]["degraded"] is True
