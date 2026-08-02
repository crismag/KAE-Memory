"""Deduplication, in the two shapes duplicates actually take.

Splitting a document into chunks makes the same sentence reach two runs. Without
collapse, each becomes a knowledge item, both get classified into the same area,
and the credit-weighted calculation counts one fact twice — readiness rises for
work nobody did.

Identical statements collapse on write, because that needs no judgement.
Collapse targets exclude rejected and superseded items so a new candidate
cannot revive a decision someone made; that path has no test yet because
nothing can reject or supersede knowledge until the correction write path
exists.
Near-duplicates are reported and left alone, because deciding that two
differently-worded statements mean the same thing is a judgement, and getting it
wrong destroys something a person confirmed.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.review_service import FindingKind, ReviewService, Severity
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lexical import is_near_duplicate, similarity
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import Project

STATEMENT = "A report cannot be published before it is approved."


def _write(
    memory: MemoryService, project_id: ProjectId, key: str, *texts: str, kind: str = "requirement"
) -> tuple:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind=kind, content=text, source="seed") for text in texts],
    )


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, Project]:
    memory = MemoryService(factory)
    return memory, memory.create_project("Ministry Reporting", key="dedupe")


class TestIdenticalStatementsCollapse:
    def test_the_same_sentence_from_two_runs_is_one_item(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        """The fan-out case: one fact, two chunks, two runs."""

        memory, proj = project
        first = _write(memory, proj.id, "chunk-1", STATEMENT)[0]
        second = _write(memory, proj.id, "chunk-2", STATEMENT)[0]

        assert second.id == first.id
        assert len(memory.retrieve_knowledge(proj.id, lifecycle=None)) == 1

    def test_whitespace_and_case_are_not_meaning(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        first = _write(memory, proj.id, "chunk-1", STATEMENT)[0]
        second = _write(
            memory, proj.id, "chunk-2", "a report cannot   be published\nbefore it is approved."
        )[0]

        assert second.id == first.id

    def test_the_same_words_under_a_different_kind_stay_apart(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        """A rule and a requirement saying the same thing are different claims."""

        memory, proj = project
        first = _write(memory, proj.id, "as-req", STATEMENT, kind="requirement")[0]
        second = _write(memory, proj.id, "as-rule", STATEMENT, kind="rule")[0]

        assert second.id != first.id

    def test_the_second_run_keeps_its_provenance(
        self, project: tuple[MemoryService, Project]
    ) -> None:
        """Collapsing must not lose the fact that a second run also found it.

        One fact with two sources is stronger evidence than one fact with one,
        and dropping the second source would understate the record.
        """

        memory, proj = project
        item = _write(memory, proj.id, "chunk-1", STATEMENT)[0]
        _write(memory, proj.id, "chunk-2", STATEMENT)

        links = memory.provenance_for_item(item.id)
        producing = [link for link in links if link.link_type.value == "produced_by"]
        assert len(producing) == 2

    def test_collapsing_alone_does_not_invalidate_a_snapshot(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        """A run that recorded no new statement changed nothing to recalculate."""

        memory, proj = project
        readiness = ReadinessService(factory)
        readiness.install_template()
        _write(memory, proj.id, "chunk-1", STATEMENT)
        before = readiness.knowledge_revision(proj.id)

        _write(memory, proj.id, "chunk-2", STATEMENT)

        assert readiness.knowledge_revision(proj.id) == before

    def test_readiness_counts_one_fact_once(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        """The reason this exists at all."""

        memory, proj = project
        readiness = ReadinessService(factory)
        readiness.install_template()
        item = _write(memory, proj.id, "chunk-1", STATEMENT)[0]
        memory.confirm_knowledge(item.id)
        readiness.assign_area(proj.id, item.id, "functional_requirements")
        before = readiness.calculate(proj.id).percentage

        _write(memory, proj.id, "chunk-2", STATEMENT)

        assert readiness.calculate(proj.id).percentage == before


class TestNearDuplicatesAreReportedNotMerged:
    def _seed_near_pair(
        self, memory: MemoryService, readiness: ReadinessService, proj: Project
    ) -> None:
        items = _write(
            memory,
            proj.id,
            "near",
            "A report cannot be published before it is approved.",
            "A report cannot be published before it has been approved.",
        )
        for item in items:
            memory.confirm_knowledge(item.id)

    def test_a_near_duplicate_pair_is_reported(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        readiness = ReadinessService(factory)
        self._seed_near_pair(memory, readiness, proj)

        findings = ReviewService(factory).findings(proj.id)
        duplicates = [f for f in findings if f.kind is FindingKind.DUPLICATE_KNOWLEDGE]

        assert len(duplicates) == 1
        assert duplicates[0].severity is Severity.MAJOR
        assert len(duplicates[0].knowledge_item_ids) == 2

    def test_both_statements_survive(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        """Reporting is not merging. Nothing a human confirmed is discarded."""

        memory, proj = project
        readiness = ReadinessService(factory)
        self._seed_near_pair(memory, readiness, proj)

        assert len(memory.retrieve_knowledge(proj.id, lifecycle=LifecycleState.VALIDATED)) == 2

    def test_the_action_says_a_human_must_choose(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        readiness = ReadinessService(factory)
        self._seed_near_pair(memory, readiness, proj)

        finding = next(
            f
            for f in ReviewService(factory).findings(proj.id)
            if f.kind is FindingKind.DUPLICATE_KNOWLEDGE
        )

        assert "judgement about meaning" in finding.recommended_action

    def test_unconfirmed_candidates_are_not_reported(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        """Overlapping candidates are the extractor working, not a defect.

        A duplicate starts costing something when it is confirmed, because that
        is when it begins counting toward an area.
        """

        memory, proj = project
        _write(
            memory,
            proj.id,
            "near",
            "A report cannot be published before it is approved.",
            "A report cannot be published before it has been approved.",
        )

        findings = ReviewService(factory).findings(proj.id)

        assert not [f for f in findings if f.kind is FindingKind.DUPLICATE_KNOWLEDGE]

    def test_unrelated_statements_are_not_reported(
        self, factory: sessionmaker[Session], project: tuple[MemoryService, Project]
    ) -> None:
        memory, proj = project
        items = _write(
            memory,
            proj.id,
            "distinct",
            "A report cannot be published before it is approved.",
            "Identity must come from the existing organisational directory.",
        )
        for item in items:
            memory.confirm_knowledge(item.id)

        findings = ReviewService(factory).findings(proj.id)

        assert not [f for f in findings if f.kind is FindingKind.DUPLICATE_KNOWLEDGE]


class TestSimilarity:
    def test_a_statement_and_its_negation_are_not_duplicates(self) -> None:
        """The load-bearing case. These are a contradiction, not housekeeping."""

        positive = "A submitter can approve their own report."
        negative = "A submitter cannot approve their own report."

        assert similarity(positive, negative) > 0.85
        assert is_near_duplicate(positive, negative) is False

    def test_word_order_does_not_create_a_second_fact(self) -> None:
        assert is_near_duplicate(
            "Only an authorised approver may approve a report.",
            "A report may be approved only by an authorised approver.",
        )

    def test_different_statements_score_low(self) -> None:
        assert (
            similarity(
                "A report cannot be published before it is approved.",
                "Ministry leaders submit monthly reports.",
            )
            < 0.5
        )
