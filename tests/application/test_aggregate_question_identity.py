"""One unresolved question per decision, and evidence kept underneath it.

D-11. An aggregate clarification asks about an *area* — "these unresolved items
need answers" — and its membership grows as the project does. Keying on that
membership gave every growth a new key, so the identical question was re-asked
each time one more `unknown` joined it: about ten times in a 42-message session,
which is enough to make an interviewer feel like it is not listening.

The key is now `(finding_kind, area_key)` for aggregates, so growth is the same
question. That is right where several observations are one decision, and wrong
where each finding is its own — hence `subject_key`, and hence the fourth test
below, which is what decided the key needed a third part at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.clarification_service import (
    Clarification,
    ClarificationService,
    _question_key,
)
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.readiness import BlockerSeverity


def _aggregate(*knowledge_ids: str) -> Clarification:
    return Clarification(
        question="Answer each of these.",
        finding_kind="open_question",
        severity="critical",
        area_key="scope_and_boundaries",
        knowledge_ids=knowledge_ids,
    )


def _blocker(subject_key: str) -> Clarification:
    return Clarification(
        question="Close the blocker, or accept it as an assumption.",
        finding_kind="open_blocker",
        severity="critical",
        area_key="scope_and_boundaries",
        subject_key=subject_key,
    )


class TestTheKey:
    def test_repeated_aggregation_is_idempotent(self) -> None:
        assert _question_key(_aggregate("a", "b")) == _question_key(_aggregate("a", "b"))

    def test_a_growing_aggregate_is_the_same_question(self) -> None:
        """The defect itself. One more member must not be a new question."""

        assert _question_key(_aggregate("a", "b")) == _question_key(_aggregate("a", "b", "c"))

    def test_order_is_not_identity(self) -> None:
        assert _question_key(_aggregate("b", "a")) == _question_key(_aggregate("a", "b"))

    def test_materially_different_subjects_do_not_collide(self) -> None:
        """The test that decided the key needed a third part.

        Blockers carry no knowledge ids, so two different blockers in one area
        produced the identical key and the second was treated as already asked
        — it never reached anybody. That predates the aggregate change: both
        hashed to nothing under the old membership key too.
        """

        assert _question_key(_blocker("blocker-1")) != _question_key(_blocker("blocker-2"))

    def test_identity_does_not_move_when_the_wording_does(self) -> None:
        """A key that shifted on a rephrase would re-ask what it exists to suppress."""

        rephrased = Clarification(
            question="Please close this blocker or accept it.",
            finding_kind="open_blocker",
            severity="major",
            area_key="scope_and_boundaries",
            subject_key="blocker-1",
        )

        assert _question_key(rephrased) == _question_key(_blocker("blocker-1"))

    def test_one_statement_is_not_an_aggregate(self) -> None:
        """A question about a single item is about *that item*.

        Collapsing these too would make every open question in an area one
        question, which is the opposite failure.
        """

        assert _question_key(_aggregate("a")) != _question_key(_aggregate("b"))
        assert _question_key(_aggregate("a")) != _question_key(_aggregate("a", "b"))


class TestAgainstARealProject:
    @pytest.fixture
    def project(self, factory: sessionmaker[Session]) -> ProjectId:
        readiness = ReadinessService(factory)
        readiness.install_template()
        memory = MemoryService(factory)
        created = memory.create_project("Aggregates", key="aggregate-identity")
        run = memory.start_run(created.id, AgentRole.REQUIREMENTS, "seed-aggregate")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="unknown", content="Who approves a report?", source="interview"
                )
            ],
        )
        return created.id

    def test_new_evidence_enriches_rather_than_duplicates(
        self, factory: sessionmaker[Session], project: ProjectId
    ) -> None:
        """A second unknown must join the question, not start another."""

        memory = MemoryService(factory)
        clarifications = ClarificationService(factory)
        first = clarifications.open_questions(project)
        before = len(first)

        run = memory.start_run(project, AgentRole.REQUIREMENTS, "seed-second-unknown")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="unknown", content="Who publishes it?", source="interview"
                )
            ],
        )
        after = clarifications.open_questions(project)

        aggregates = [q for q in after if len(q.knowledge_ids) > 1]
        assert len(after) == before, "a growing aggregate asked a second question"
        if aggregates:
            assert len(aggregates[0].knowledge_ids) >= 2, (
                "the question must carry the evidence that accrued to it"
            )

    def test_replay_creates_no_duplicates(
        self, factory: sessionmaker[Session], project: ProjectId
    ) -> None:
        """Listing repeatedly is what a refresh does."""

        memory = MemoryService(factory)
        clarifications = ClarificationService(factory)

        clarifications.open_questions(project)
        clarifications.open_questions(project)
        clarifications.open_questions(project)

        asked = [
            message
            for session in memory.sessions_for_project(project)
            for message in memory.messages_for_session(session.id)
            if message.message_type.value == "question"
        ]
        keys = [message.idempotency_key for message in asked]

        assert len(keys) == len(set(keys)), f"the same question was recorded twice: {keys}"

    def test_two_blockers_in_one_area_are_two_questions(
        self, factory: sessionmaker[Session], project: ProjectId
    ) -> None:
        """End to end, through the real finding path.

        The unit test above proves the keys differ; this proves the blocker id
        actually reaches the key, which is where a discriminator usually fails.
        """

        readiness = ReadinessService(factory)
        for summary in ("Nobody owns approval.", "The retention period is undecided."):
            readiness.raise_blocker(
                project,
                summary=summary,
                severity=BlockerSeverity.CRITICAL,
                area_key="scope_and_boundaries",
            )

        questions = ClarificationService(factory).open_questions(project)
        blockers = [q for q in questions if q.finding_kind == "open_blocker"]

        assert len(blockers) == 2, "one blocker's question was swallowed by the other"
