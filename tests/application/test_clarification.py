"""The clarification loop: gap → question → answer → candidate knowledge.

The loop must close without ever letting an answer become a project fact on its
own. An answer is evidence: it is stored verbatim, extracted like any other
input, and what comes out is a candidate a human confirms.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicExtractionAdapter
from kae_memory.application import (
    ClarificationService,
    MemoryService,
    ReadinessService,
    WriteKnowledgeRequest,
)
from kae_memory.application.clarification_service import ANSWERS, ASKS_ABOUT
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.workspace import ActorType, Message, MessageType
from kae_memory.worker.execution import AgentStepExecutor
from kae_memory.worker.runner import Worker, WorkerConfig

ANSWER_TEXT = (
    "The finance director approves ministry reports. We want approval recorded "
    "against a named person so an audit can follow it."
)


@pytest.fixture
def project(
    factory: sessionmaker[Session],
) -> tuple[ClarificationService, MemoryService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="clarify")
    return ClarificationService(factory, memory), memory, proj.id


class TestDerivingQuestions:
    def test_gaps_become_questions(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project

        pending = clarify.pending(project_id)

        assert pending
        assert all(c.question for c in pending)
        assert any(c.finding_kind == "missing_area" for c in pending)

    def test_the_most_severe_comes_first(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project

        pending = clarify.pending(project_id)

        assert pending[0].severity == "critical"

    def test_work_queues_are_not_asked_as_questions(self, project: tuple[Any, ...]) -> None:
        """ "Confirm each candidate" is work, not something a person can answer.

        Asking it spends the one resource this loop exists to spend carefully.
        """

        clarify, memory, project_id = project
        run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "seed")
        memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(kind="requirement", content="A claim.", source="seed")],
        )

        kinds = {c.finding_kind for c in clarify.pending(project_id)}

        assert "unconfirmed_knowledge" not in kinds
        assert "unclassified_knowledge" not in kinds


class TestAsking:
    def test_a_question_records_what_it_is_about(self, project: tuple[Any, ...]) -> None:
        """Findings have no identity, so the question records its subject."""

        clarify, _, project_id = project
        clarification = clarify.pending(project_id)[0]

        question = clarify.ask(project_id, clarification)

        assert question.message_type is MessageType.QUESTION
        assert question.metadata[ASKS_ABOUT]["finding_kind"] == clarification.finding_kind
        assert question.metadata[ASKS_ABOUT]["area_key"] == clarification.area_key

    def test_the_subject_stays_out_of_the_content(self, project: tuple[Any, ...]) -> None:
        """Content is what a person reads and answers, and nothing else."""

        clarify, _, project_id = project
        clarification = clarify.pending(project_id)[0]

        question = clarify.ask(project_id, clarification)

        assert question.content == clarification.question
        assert "finding_kind" not in question.content

    def test_a_question_is_not_attributed_to_an_agent(self, project: tuple[Any, ...]) -> None:
        """It was derived by deterministic logic; no run produced it."""

        clarify, _, project_id = project

        question = clarify.ask(project_id, clarify.pending(project_id)[0])

        assert question.actor_type is ActorType.SYSTEM
        assert question.agent_run_id is None

    def test_the_same_gap_is_not_asked_twice(self, project: tuple[Any, ...]) -> None:
        """Keyed on subject, not wording: rephrasing must not re-ask."""

        clarify, _, project_id = project
        clarification = clarify.pending(project_id)[0]

        first = clarify.ask(project_id, clarification)
        second = clarify.ask(project_id, clarification, session_id=first.session_id)

        assert second.id == first.id


class TestAnswering:
    def _ask(self, clarify: ClarificationService, project_id: ProjectId) -> Message:
        return clarify.ask(project_id, clarify.pending(project_id)[0])

    def test_an_answer_links_back_to_its_question(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project
        question = self._ask(clarify, project_id)

        answered = clarify.answer(project_id, question.id, ANSWER_TEXT)

        assert answered.answer.message_type is MessageType.ANSWER
        assert answered.answer.metadata[ANSWERS] == str(question.id)

    def test_the_answer_is_stored_verbatim(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project
        question = self._ask(clarify, project_id)

        answered = clarify.answer(project_id, question.id, ANSWER_TEXT)

        assert answered.answer.content == ANSWER_TEXT

    def test_the_subject_survives_onto_the_answer(self, project: tuple[Any, ...]) -> None:
        """The finding that prompted it may be resolved away by the answer."""

        clarify, _, project_id = project
        question = self._ask(clarify, project_id)

        answered = clarify.answer(project_id, question.id, ANSWER_TEXT)

        assert answered.answer.metadata[ASKS_ABOUT] == question.metadata[ASKS_ABOUT]

    def test_answering_writes_no_knowledge_directly(self, project: tuple[Any, ...]) -> None:
        """The load-bearing rule. An answer is evidence, not a project fact."""

        clarify, memory, project_id = project
        question = self._ask(clarify, project_id)

        clarify.answer(project_id, question.id, ANSWER_TEXT)

        assert memory.retrieve_knowledge(project_id, lifecycle=None) == ()

    def test_an_empty_answer_is_rejected(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project
        question = self._ask(clarify, project_id)

        with pytest.raises(ValueError):
            clarify.answer(project_id, question.id, "   ")

    def test_answering_something_that_is_not_a_question_is_rejected(
        self, project: tuple[Any, ...]
    ) -> None:
        clarify, memory, project_id = project
        question = self._ask(clarify, project_id)
        note = memory.record_message(
            project_id, question.session_id, content="A stray note.", idempotency_key="note-1"
        )

        with pytest.raises(ValueError):
            clarify.answer(project_id, note.message.id, ANSWER_TEXT)

    def test_answering_twice_is_a_replay(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project
        question = self._ask(clarify, project_id)

        first = clarify.answer(project_id, question.id, ANSWER_TEXT)
        second = clarify.answer(project_id, question.id, ANSWER_TEXT)

        assert second.answer.id == first.answer.id
        assert second.run_id == first.run_id


class TestTheLoopCloses:
    def test_an_answer_becomes_candidate_knowledge(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """Gap → question → answer → extraction → candidate awaiting a human."""

        clarify, memory, project_id = project
        question = clarify.ask(project_id, clarify.pending(project_id)[0])
        clarify.answer(project_id, question.id, ANSWER_TEXT)

        worker = Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter(), None),
            WorkerConfig(worker_id="clarify"),
        )
        while worker.run_once() is not None:
            pass

        candidates = memory.retrieve_knowledge(project_id, lifecycle=LifecycleState.PROPOSED)
        assert candidates, "the answer produced candidates"
        assert memory.retrieve_knowledge(project_id, lifecycle=LifecycleState.VALIDATED) == ()

    def test_the_candidate_traces_back_to_the_answer(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """Provenance must reach the person's own words, not a paraphrase."""

        clarify, memory, project_id = project
        question = clarify.ask(project_id, clarify.pending(project_id)[0])
        answered = clarify.answer(project_id, question.id, ANSWER_TEXT)

        worker = Worker(
            factory,
            AgentStepExecutor(factory, DeterministicExtractionAdapter(), None),
            WorkerConfig(worker_id="clarify"),
        )
        while worker.run_once() is not None:
            pass

        candidate = memory.retrieve_knowledge(project_id, lifecycle=LifecycleState.PROPOSED)[0]
        links = memory.provenance_for_item(candidate.id)
        sources = {str(link.message_id) for link in links if link.message_id}
        assert str(answered.answer.id) in sources

    def test_unanswered_questions_are_reportable(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project
        pending = clarify.pending(project_id)
        first = clarify.ask(project_id, pending[0])
        clarify.ask(project_id, pending[1], session_id=first.session_id)

        outstanding = clarify.unanswered(project_id, first.session_id)
        assert len(outstanding) == 2

        clarify.answer(project_id, first.id, ANSWER_TEXT)

        assert len(clarify.unanswered(project_id, first.session_id)) == 1
