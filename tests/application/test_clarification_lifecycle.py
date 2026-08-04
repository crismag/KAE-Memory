"""The clarification loop, end to end, through the real worker (T18).

The pipeline this proves is asynchronous, and the test keeps it that way. It
enqueues work and then runs an actual Worker over the queue rather than calling
the extractor directly, because a test that collapsed the stages would prove a
workflow the product does not have — and the distance between "answered" and
"known" is the thing the product is most careful about.

Each stage is asserted in the order it really occurs:

    answer accepted -> extraction queued -> worker claims -> knowledge proposed
    -> provenance linked -> a person confirms -> readiness moves

Nothing later is allowed to be true before its stage has run.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicExtractionAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.clarification_service import (
    ANSWERS,
    ClarificationService,
    ClarificationState,
)
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.errors import AlreadyAnsweredError
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import MessageId, ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import ProvenanceLinkType
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

ANSWER = (
    "Roughly 25 ministries file monthly reports. The finance team reviews them, "
    "and the director approves before publication."
)

Services = tuple[MemoryService, ClarificationService, ReadinessService, ProjectId]


@pytest.fixture
def services(factory: sessionmaker[Session]) -> Services:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    clarify = ClarificationService(factory, memory)

    project = memory.create_project("Ministry Reporting", key="lifecycle-t18")
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "seed")
    memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind="goal", content="Ministries file monthly reports.", source="interview"
            )
        ],
    )
    return memory, clarify, readiness, project.id


def _work(factory: sessionmaker[Session]) -> int:
    """Run a real worker over the queue until it is idle.

    The production runner, not a stand-in. Faking it would leave claiming,
    status transitions, and provenance writes untested — which is most of what
    this target is about.
    """

    worker = Worker(
        factory,
        AgentStepExecutor(factory, DeterministicExtractionAdapter()),
        WorkerConfig(worker_id="t18", idle_poll_seconds=0.01),
    )
    return worker.run_until_idle(max_runs=20)


def _open_question(clarify: ClarificationService, project_id: ProjectId) -> MessageId:
    questions = clarify.open_questions(project_id, limit=1)
    assert questions, "the project's gaps should justify at least one question"
    return questions[0].id


class TestTheLoopCloses:
    """One pass through every stage, asserted in order."""

    def test_the_full_lifecycle(self, factory: sessionmaker[Session], services: Services) -> None:
        memory, clarify, _, project_id = services

        question_id = _open_question(clarify, project_id)
        assert (
            clarify.progress(project_id, question_id).state
            is ClarificationState.WAITING_FOR_ANSWER
        )

        answered = clarify.answer(project_id, question_id, ANSWER, actor_id="cris")
        queued = clarify.progress(project_id, question_id)
        assert queued.state is ClarificationState.WAITING_FOR_EXTRACTION
        assert not queued.proposed_knowledge_ids

        pending = memory.get_run(answered.run_id)
        assert pending is not None and pending.status is RunStatus.PENDING

        assert _work(factory) >= 1
        executed = memory.get_run(answered.run_id)
        assert executed is not None and executed.status is RunStatus.SUCCEEDED

        reviewed = clarify.progress(project_id, question_id)
        assert reviewed.state is ClarificationState.AWAITING_REVIEW
        assert reviewed.proposed_knowledge_ids
        assert not reviewed.validated_knowledge_ids

        produced = memory.knowledge_produced_by(answered.run_id)
        assert all(item.lifecycle is LifecycleState.PROPOSED for item in produced)

        confirmed = produced[0]
        memory.review_confirm(
            project_id,
            confirmed.id,
            expected_version=confirmed.current_version.number,
            actor_id="cris",
        )

        closed = clarify.progress(project_id, question_id)
        assert str(confirmed.id) in closed.validated_knowledge_ids
        assert closed.knowledge_changed


class TestNothingIsTrueBeforeItsStage:
    """The guarantees T16 and T17 established, held through T18."""

    def test_answering_creates_no_knowledge(self, services: Services) -> None:
        memory, clarify, _, project_id = services
        before = len(memory.retrieve_knowledge(project_id, lifecycle=None))

        clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)

        assert len(memory.retrieve_knowledge(project_id, lifecycle=None)) == before

    def test_answering_does_not_move_the_knowledge_revision(self, services: Services) -> None:
        _, clarify, readiness, project_id = services
        before = readiness.knowledge_revision(project_id)

        clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)

        assert readiness.knowledge_revision(project_id) == before

    def test_extraction_does_not_validate_what_it_proposes(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        """The whole reason the loop routes through review at all (FR-005)."""

        memory, clarify, _, project_id = services
        answered = clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)

        _work(factory)

        produced = memory.knowledge_produced_by(answered.run_id)
        assert produced
        assert all(item.lifecycle is LifecycleState.PROPOSED for item in produced)

    def test_proposed_knowledge_does_not_make_an_area_sufficient(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        """Readiness counts confirmed knowledge, and nothing here is confirmed."""

        _, clarify, readiness, project_id = services
        clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)
        _work(factory)

        snapshot = readiness.calculate(project_id)

        assert all(area.confirmed_count == 0 for area in snapshot.areas)

    def test_confirming_is_what_moves_readiness(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        memory, clarify, readiness, project_id = services
        answered = clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)
        _work(factory)
        before = readiness.knowledge_revision(project_id)

        item = memory.knowledge_produced_by(answered.run_id)[0]
        memory.review_confirm(project_id, item.id, expected_version=item.current_version.number)

        assert readiness.knowledge_revision(project_id) > before


class TestProvenance:
    """Why the system believes a thing, reconstructable after the fact."""

    def test_proposed_knowledge_traces_back_to_the_answer(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        memory, clarify, _, project_id = services
        answered = clarify.answer(
            project_id, _open_question(clarify, project_id), ANSWER, actor_id="cris"
        )

        _work(factory)

        item = memory.knowledge_produced_by(answered.run_id)[0]
        links = memory.provenance_for_item(item.id)
        from_message = [
            link for link in links if link.link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE
        ]
        assert from_message, "extracted knowledge must name the evidence it came from"
        assert any(link.message_id == answered.answer.id for link in from_message)

    def test_the_producing_run_is_recorded(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        memory, clarify, _, project_id = services
        answered = clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)

        _work(factory)

        assert memory.knowledge_produced_by(answered.run_id)

    def test_the_answer_still_names_its_question(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        """The chain survives the finding that prompted it disappearing."""

        memory, clarify, _, project_id = services
        question_id = _open_question(clarify, project_id)
        answered = clarify.answer(project_id, question_id, ANSWER)

        _work(factory)

        stored = memory.get_message(answered.answer.id)
        assert stored is not None
        assert str(stored.metadata[ANSWERS]) == str(question_id)


class TestIdempotency:
    def test_a_replayed_answer_queues_one_extraction(self, services: Services) -> None:
        _, clarify, _, project_id = services
        question_id = _open_question(clarify, project_id)

        first = clarify.answer(project_id, question_id, ANSWER, idempotency_key="k")
        second = clarify.answer(project_id, question_id, ANSWER, idempotency_key="k")

        assert second.replayed
        assert second.run_id == first.run_id

    def test_running_the_worker_twice_proposes_one_set(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        """A completed run replays its output rather than extracting again."""

        memory, clarify, _, project_id = services
        answered = clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)

        _work(factory)
        first = len(memory.knowledge_produced_by(answered.run_id))
        _work(factory)

        assert len(memory.knowledge_produced_by(answered.run_id)) == first

    def test_a_conflicting_answer_is_still_refused_after_extraction(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        _, clarify, _, project_id = services
        question_id = _open_question(clarify, project_id)
        clarify.answer(project_id, question_id, ANSWER)
        _work(factory)

        with pytest.raises(AlreadyAnsweredError):
            clarify.answer(project_id, question_id, "A different answer.", idempotency_key="x")


class TestOwnership:
    def test_progress_is_refused_across_projects(self, services: Services) -> None:
        memory, clarify, _, project_id = services
        question_id = _open_question(clarify, project_id)
        other = memory.create_project("Other", key="lifecycle-other")

        with pytest.raises(LookupError):
            clarify.progress(other.id, question_id)

    def test_extraction_output_stays_in_its_project(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        memory, clarify, _, project_id = services
        other = memory.create_project("Other", key="lifecycle-other-2")
        clarify.answer(project_id, _open_question(clarify, project_id), ANSWER)

        _work(factory)

        assert memory.retrieve_knowledge(other.id, lifecycle=None) == ()


class TestWorkflowState:
    """A caller should read where they are, not deduce it."""

    def test_every_stage_has_a_name(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        _, clarify, _, project_id = services
        question_id = _open_question(clarify, project_id)

        seen = [clarify.progress(project_id, question_id).state]
        clarify.answer(project_id, question_id, ANSWER)
        seen.append(clarify.progress(project_id, question_id).state)
        _work(factory)
        seen.append(clarify.progress(project_id, question_id).state)

        assert seen == [
            ClarificationState.WAITING_FOR_ANSWER,
            ClarificationState.WAITING_FOR_EXTRACTION,
            ClarificationState.AWAITING_REVIEW,
        ]

    def test_state_is_derived_rather_than_stored(
        self, factory: sessionmaker[Session], services: Services
    ) -> None:
        """Asking twice cannot disagree, because nothing caches it."""

        _, clarify, _, project_id = services
        question_id = _open_question(clarify, project_id)
        clarify.answer(project_id, question_id, ANSWER)
        _work(factory)

        first = clarify.progress(project_id, question_id)
        second = clarify.progress(project_id, question_id)

        assert first.state is second.state
        assert first.proposed_knowledge_ids == second.proposed_knowledge_ids
