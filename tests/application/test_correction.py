"""Correction, rejection, and supersession — history that is added to, never cut.

The product promise is that a correction supersedes what came before rather than
deleting it. These cover the three shapes that takes: a candidate turned down, a
statement reworded, and a statement replaced by a different one.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import (
    MemoryService,
    ReadinessService,
    ReviewService,
    WriteKnowledgeRequest,
)
from kae_memory.application.memory_service import HUMAN_EXECUTION
from kae_memory.domain.errors import DomainInvariantError, InvalidLifecycleTransitionError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem

ORIGINAL = "A report cannot be published before it is approved."
CORRECTED = "A report cannot be published before it is approved by the finance director."


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    return memory, memory.create_project("Ministry Reporting", key="correction").id


def _write(memory: MemoryService, project_id: ProjectId, key: str, text: str) -> KnowledgeItem:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="requirement", content=text, source="seed")]
    )[0]


class TestRejection:
    def test_a_candidate_can_be_turned_down(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "r1", ORIGINAL)

        rejected = memory.reject_knowledge(item.id)

        assert rejected.lifecycle is LifecycleState.REJECTED

    def test_rejection_is_not_deletion(self, project: tuple[Any, ...]) -> None:
        """What was considered and turned down is part of the audit trail."""

        memory, project_id = project
        item = _write(memory, project_id, "r2", ORIGINAL)

        memory.reject_knowledge(item.id)

        stored = memory.retrieve_knowledge(project_id, lifecycle=None)
        assert [i.id for i in stored] == [item.id]
        assert memory.provenance_for_item(item.id)

    def test_a_confirmed_statement_cannot_be_rejected(self, project: tuple[Any, ...]) -> None:
        """Rejection is for candidates. Retiring a confirmed fact is supersession.

        The distinction matters: a rejected item was never part of the project's
        knowledge, while a superseded one was and is retained as what the
        project used to believe.
        """

        memory, project_id = project
        item = _write(memory, project_id, "r3", ORIGINAL)
        memory.confirm_knowledge(item.id)

        with pytest.raises(InvalidLifecycleTransitionError):
            memory.reject_knowledge(item.id)

    def test_a_rejected_twin_does_not_absorb_a_new_candidate(
        self, project: tuple[Any, ...]
    ) -> None:
        """The branch deduplication left untested until this existed.

        Collapsing into a rejected item would quietly revive a decision someone
        made.
        """

        memory, project_id = project
        first = _write(memory, project_id, "r4", ORIGINAL)
        memory.reject_knowledge(first.id)

        second = _write(memory, project_id, "r5", ORIGINAL)

        assert second.id != first.id
        assert second.lifecycle is LifecycleState.PROPOSED


class TestCorrection:
    def test_a_correction_appends_rather_than_edits(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "c1", ORIGINAL)

        corrected = memory.correct_knowledge(item.id, CORRECTED, source="interview")

        assert len(corrected.versions) == 2
        assert corrected.current_version.content == CORRECTED

    def test_the_prior_wording_is_retained(self, project: tuple[Any, ...]) -> None:
        """Editing in place would rewrite history other records point at."""

        memory, project_id = project
        item = _write(memory, project_id, "c2", ORIGINAL)

        corrected = memory.correct_knowledge(item.id, CORRECTED, source="interview")

        assert corrected.versions[0].content == ORIGINAL

    def test_a_corrected_statement_needs_confirming_again(self, project: tuple[Any, ...]) -> None:
        """It was confirmed on the old wording.

        Carrying that confirmation onto text nobody has read is the easiest way
        to slip an unreviewed claim into the confirmed set.
        """

        memory, project_id = project
        item = _write(memory, project_id, "c3", ORIGINAL)
        memory.confirm_knowledge(item.id)

        corrected = memory.correct_knowledge(item.id, CORRECTED, source="interview")

        assert corrected.lifecycle is LifecycleState.PROPOSED

    def test_a_human_correction_is_not_disguised_as_a_run(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "c4", ORIGINAL)

        corrected = memory.correct_knowledge(item.id, CORRECTED, source="interview")

        assert str(corrected.current_version.provenance.execution_id) == HUMAN_EXECUTION

    def test_an_empty_correction_is_rejected(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "c5", ORIGINAL)

        with pytest.raises(ValueError):
            memory.correct_knowledge(item.id, "   ", source="interview")

    def test_a_retired_statement_cannot_be_corrected(self, project: tuple[Any, ...]) -> None:
        """Reviving something already turned down should be an explicit act."""

        memory, project_id = project
        item = _write(memory, project_id, "c6", ORIGINAL)
        memory.reject_knowledge(item.id)

        with pytest.raises(DomainInvariantError):
            memory.correct_knowledge(item.id, CORRECTED, source="interview")


class TestSupersession:
    def test_one_statement_retires_in_favour_of_another(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        old = _write(memory, project_id, "s1", ORIGINAL)
        memory.confirm_knowledge(old.id)
        new = _write(memory, project_id, "s2", CORRECTED)

        retired = memory.supersede_knowledge(old.id, new.id)

        assert retired.lifecycle is LifecycleState.SUPERSEDED

    def test_both_statements_remain_readable(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        old = _write(memory, project_id, "s3", ORIGINAL)
        memory.confirm_knowledge(old.id)
        new = _write(memory, project_id, "s4", CORRECTED)

        memory.supersede_knowledge(old.id, new.id)

        stored = {i.id for i in memory.retrieve_knowledge(project_id, lifecycle=None)}
        assert {old.id, new.id} <= stored

    def test_a_statement_cannot_supersede_itself(self, project: tuple[Any, ...]) -> None:
        memory, project_id = project
        item = _write(memory, project_id, "s5", ORIGINAL)

        with pytest.raises(ValueError):
            memory.supersede_knowledge(item.id, item.id)

    def test_supersession_cannot_cross_projects(self, project: tuple[Any, ...]) -> None:
        """A project is the durable boundary that owns what is derived in it."""

        memory, project_id = project
        mine = _write(memory, project_id, "s6", ORIGINAL)
        memory.confirm_knowledge(mine.id)
        other = memory.create_project("Other", key="correction-other")
        theirs = _write(memory, other.id, "s7", CORRECTED)

        with pytest.raises(DomainInvariantError):
            memory.supersede_knowledge(mine.id, theirs.id)

    def test_a_superseded_statement_stops_counting(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        memory, project_id = project
        readiness = ReadinessService(factory)
        old = _write(memory, project_id, "s8", ORIGINAL)
        memory.confirm_knowledge(old.id)
        readiness.assign_area(project_id, old.id, "functional_requirements")
        covered = readiness.calculate(project_id).percentage
        new = _write(memory, project_id, "s9", CORRECTED)

        memory.supersede_knowledge(old.id, new.id)

        assert readiness.calculate(project_id).percentage < covered

    def test_superseding_resolves_a_duplicate_finding(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """The action the duplicate finding recommends actually resolves it."""

        memory, project_id = project
        first = _write(memory, project_id, "d1", ORIGINAL)
        second = _write(
            memory, project_id, "d2", "A report cannot be published before it has been approved."
        )
        for item in (first, second):
            memory.confirm_knowledge(item.id)
        review = ReviewService(factory)
        assert any(f.kind.value == "duplicate_knowledge" for f in review.findings(project_id))

        memory.supersede_knowledge(first.id, second.id)

        assert not any(f.kind.value == "duplicate_knowledge" for f in review.findings(project_id))
