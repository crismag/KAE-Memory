"""Reviewed confirmation: ownership, staleness, replay, and the audit record.

The failure these exist to prevent is not a crash. It is a system that reports
knowledge as human-confirmed when nobody confirmed it, confirmed the previous
wording, or was not entitled to confirm it at all.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.errors import (
    InvalidLifecycleTransitionError,
    KnowledgeNotFoundError,
    StaleVersionError,
)
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
from kae_memory.domain.knowledge_review import ReviewAction
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.workspace import ActorType

STATEMENT = "Only an authorised approver may approve a report."
OTHER_STATEMENT = "Every important state change is recorded."


def _write(memory: MemoryService, project_id: ProjectId, key: str, content: str) -> KnowledgeItem:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content=content, source="interview")]
    )
    return written[0]


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, ProjectId]:
    memory = MemoryService(factory)
    return memory, memory.create_project("Ministry Reporting", key="review").id


class TestOwnership:
    """A project is the boundary that owns what was derived in it."""

    def test_an_item_from_another_project_cannot_be_confirmed(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        other = memory.create_project("Other", key="review-other")
        theirs = _write(memory, other.id, "o1", OTHER_STATEMENT)

        with pytest.raises(KnowledgeNotFoundError):
            memory.review_confirm(project_id, theirs.id, expected_version=1)

    def test_a_refused_cross_project_call_changes_nothing(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        other = memory.create_project("Other", key="review-other-2")
        theirs = _write(memory, other.id, "o2", OTHER_STATEMENT)

        with pytest.raises(KnowledgeNotFoundError):
            memory.review_confirm(project_id, theirs.id, expected_version=1)

        untouched = memory.retrieve_knowledge(other.id, lifecycle=None)
        assert untouched[0].lifecycle is LifecycleState.PROPOSED
        assert memory.review_history(other.id, theirs.id) == ()

    def test_an_unknown_item_reports_the_same_error_as_a_foreign_one(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        """Distinguishing them would confirm that an unreachable item exists."""

        memory, project_id = project

        with pytest.raises(KnowledgeNotFoundError):
            memory.review_confirm(project_id, KnowledgeItemId("does-not-exist"), expected_version=1)


class TestVersionGuard:
    def test_a_stale_version_is_refused(self, project: tuple[MemoryService, ProjectId]) -> None:
        """The reviewer decided about wording that is no longer current."""

        memory, project_id = project
        item = _write(memory, project_id, "v1", STATEMENT)
        memory.correct_knowledge(item.id, "Corrected wording.", source="interview")

        with pytest.raises(StaleVersionError):
            memory.review_confirm(project_id, item.id, expected_version=1)

    def test_a_stale_decision_records_no_event(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "v2", STATEMENT)
        memory.correct_knowledge(item.id, "Corrected wording.", source="interview")

        with pytest.raises(StaleVersionError):
            memory.review_confirm(project_id, item.id, expected_version=1)

        assert memory.review_history(project_id, item.id) == ()
        current = memory.retrieve_knowledge(project_id, lifecycle=None)
        assert current[0].lifecycle is LifecycleState.PROPOSED

    def test_the_current_version_is_accepted(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "v3", STATEMENT)
        memory.correct_knowledge(item.id, "Corrected wording.", source="interview")

        outcome = memory.review_confirm(project_id, item.id, expected_version=2)

        assert outcome.item.lifecycle is LifecycleState.VALIDATED


class TestConfirmation:
    def test_proposed_knowledge_becomes_authoritative(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "c1", STATEMENT)

        outcome = memory.review_confirm(project_id, item.id, expected_version=1)

        assert outcome.item.lifecycle is LifecycleState.VALIDATED
        assert not outcome.replayed

    def test_confirmation_does_not_alter_the_wording(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        """Accepting a statement is not editing it."""

        memory, project_id = project
        item = _write(memory, project_id, "c2", STATEMENT)

        outcome = memory.review_confirm(project_id, item.id, expected_version=1)

        assert outcome.item.current_version.content == STATEMENT
        assert len(outcome.item.versions) == 1

    def test_rejected_knowledge_cannot_be_confirmed(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        """Reopening is a different act with different consequences."""

        memory, project_id = project
        item = _write(memory, project_id, "c3", STATEMENT)
        memory.reject_knowledge(item.id)

        with pytest.raises(InvalidLifecycleTransitionError):
            memory.review_confirm(project_id, item.id, expected_version=1)


class TestAuditRecord:
    def test_a_confirmation_records_who_decided_and_when(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "a1", STATEMENT)

        outcome = memory.review_confirm(
            project_id,
            item.id,
            expected_version=1,
            actor_id="cris",
            note="Matches the approval policy.",
        )

        event = outcome.event
        assert event is not None
        assert event.action is ReviewAction.VALIDATED
        assert event.from_lifecycle is LifecycleState.PROPOSED
        assert event.to_lifecycle is LifecycleState.VALIDATED
        assert event.actor_type is ActorType.USER
        assert event.actor_id == "cris"
        assert event.note == "Matches the approval policy."
        assert event.created_at.tzinfo is not None

    def test_the_event_names_the_version_that_was_reviewed(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        """Otherwise a later correction erases what was actually agreed to."""

        memory, project_id = project
        item = _write(memory, project_id, "a2", STATEMENT)
        memory.correct_knowledge(item.id, "Corrected wording.", source="interview")

        outcome = memory.review_confirm(project_id, item.id, expected_version=2)

        assert outcome.event is not None
        assert outcome.event.version_number == 2

    def test_history_is_scoped_to_the_project(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "a3", STATEMENT)
        memory.review_confirm(project_id, item.id, expected_version=1)
        other = memory.create_project("Other", key="review-other-3")

        with pytest.raises(KnowledgeNotFoundError):
            memory.review_history(other.id, item.id)


class TestIdempotency:
    def test_a_replayed_confirmation_records_one_decision(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        """A retry after a timeout must not look like a second reviewer."""

        memory, project_id = project
        item = _write(memory, project_id, "i1", STATEMENT)

        first = memory.review_confirm(
            project_id, item.id, expected_version=1, idempotency_key="k-1"
        )
        second = memory.review_confirm(
            project_id, item.id, expected_version=1, idempotency_key="k-1"
        )

        assert not first.replayed
        assert second.replayed
        assert len(memory.review_history(project_id, item.id)) == 1

    def test_a_replay_returns_the_original_decision(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "i2", STATEMENT)
        first = memory.review_confirm(
            project_id, item.id, expected_version=1, idempotency_key="k-2", actor_id="cris"
        )

        second = memory.review_confirm(
            project_id, item.id, expected_version=1, idempotency_key="k-2"
        )

        assert first.event is not None
        assert second.event is not None
        assert second.event.id == first.event.id
        assert second.event.actor_id == "cris"

    def test_confirming_an_already_confirmed_item_is_stable(
        self, project: tuple[MemoryService, ProjectId]
    ) -> None:
        """No key supplied, so this is not recognisable as a replay.

        The caller's intent already holds; a second event would be a decision
        nobody made.
        """

        memory, project_id = project
        item = _write(memory, project_id, "i3", STATEMENT)
        memory.review_confirm(project_id, item.id, expected_version=1)

        again = memory.review_confirm(project_id, item.id, expected_version=1)

        assert again.item.lifecycle is LifecycleState.VALIDATED
        assert again.replayed
        assert len(memory.review_history(project_id, item.id)) == 1
