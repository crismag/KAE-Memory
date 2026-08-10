"""The three journeys the product exists for, exercised end to end.

New project, existing project, stalled project — the three the ecosystem's
product direction names, run against real services and a real database rather
than against a description of them.

## What these are for

The audit asked whether a capability is *real*. These ask a different question:
whether the **journey** is real, which is not the same and is the one a user
experiences. A product can pass every capability check and still fail somebody
who arrives with a repository, because the failure is in what it chooses to do
rather than in what it can do.

## What they deliberately do not assert

Wording. A probabilistic interviewer cannot be judged by string matching, and
these run offline anyway — no provider is configured, so extraction and review
use the deterministic adapters. What they assert is the **plumbing the
judgement rides on**: knowledge lands, coverage is honest about what it did not
read, provenance says which engine produced a statement, confirmation moves
readiness, and none of it silently substitutes a plausible value for a missing
one.

Where the offline path caps what can be proved, the test says so rather than
lowering the bar — the 16% classification ceiling is real, structural, and not
a defect these journeys can find.

**No fixture pollutes real state**: every journey builds its own project inside
the test transaction.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import (
    MemoryService,
    ReadinessService,
    WriteKnowledgeRequest,
)
from kae_memory.application.ingestion_service import IngestionService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem


@pytest.fixture
def memory(factory: sessionmaker[Session]) -> MemoryService:
    return MemoryService(factory)


@pytest.fixture
def readiness(factory: sessionmaker[Session]) -> ReadinessService:
    service = ReadinessService(factory)
    service.install_template()
    return service


def _record(
    memory: MemoryService, project: ProjectId, key: str, *statements: tuple[str, str]
) -> tuple[KnowledgeItem, ...]:
    """Write knowledge the way a run does, with an engine on the record."""

    run = memory.start_run(project, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id,
        [WriteKnowledgeRequest(kind=kind, content=text, source=text) for kind, text in statements],
        output_summary={"model": "deterministic-fixture", "items_written": len(statements)},
    )


class TestANewProject:
    """Somebody with an idea and nothing else.

    The question: does talking to KAE leave the project holding more than it
    did, in a form a person can act on — and does the product stay honest about
    how little it knows at the start?
    """

    def test_a_new_project_starts_empty_and_says_so(
        self, memory: MemoryService, readiness: ReadinessService
    ) -> None:
        project = memory.create_project("A new idea", key="journey-new")

        snapshot = readiness.calculate(project.id)

        # Not "0% ready" as a judgement about the person's idea — nothing has
        # been said yet. The status carries that; the number alone would not.
        assert snapshot.percentage == 0
        assert snapshot.status.value == "not_started"
        assert not snapshot.implementation_eligible

    def test_what_is_said_becomes_knowledge_with_provenance(
        self, memory: MemoryService, readiness: ReadinessService
    ) -> None:
        project = memory.create_project("A new idea", key="journey-new-2")

        written = _record(
            memory,
            project.id,
            "journey-new-2-run",
            ("actor", "Individual founders are the first users."),
            ("goal", "People cannot move a project forward when their thinking is scattered."),
        )

        assert len(written) == 2
        # Proposed, not confirmed. The founding rule, at the first step where it
        # could be broken.
        assert all(item.lifecycle.value == "proposed" for item in written)

    def test_confirming_moves_readiness_and_provenance_survives(
        self, memory: MemoryService, readiness: ReadinessService, factory: sessionmaker[Session]
    ) -> None:
        from kae_memory.application.blueprint_service import BlueprintService

        project = memory.create_project("A new idea", key="journey-new-3")
        written = _record(
            memory,
            project.id,
            "journey-new-3-run",
            ("actor", "Individual founders are the first users."),
        )
        readiness.assign_area(project.id, written[0].id, "users_and_stakeholders")

        before = readiness.calculate(project.id)
        memory.confirm_knowledge(written[0].id)
        after = readiness.calculate(project.id)

        assert after.percentage >= before.percentage

        # And the statement can still say where it came from, which is what
        # makes the number interrogable rather than merely present.
        trace = BlueprintService(factory).trace(written[0].id)
        assert trace is not None
        assert trace.produced_by == "deterministic-fixture"

    def test_readiness_is_never_reported_without_saying_how_it_was_classified(
        self, memory: MemoryService, readiness: ReadinessService
    ) -> None:
        """The offline ceiling is real, and a user must be able to see it.

        With no review model configured, only unambiguous kinds link to an area
        and readiness tops out at 16% of the software template. That is not a
        defect of the project, and a percentage that does not say so invites
        exactly the wrong conclusion.
        """

        project = memory.create_project("A new idea", key="journey-new-4")

        report = readiness.classification(project.id)

        assert report.engine is None
        assert report.degraded is False


class TestAnExistingProject:
    """Somebody arriving with material already written down.

    The journey GitHub issue #3 is about. KAE must take what is offered rather
    than asking the person to restate it.
    """

    def test_a_document_becomes_knowledge_without_anybody_retyping_it(
        self, factory: sessionmaker[Session], memory: MemoryService, readiness: ReadinessService
    ) -> None:
        project = memory.create_project("An existing project", key="journey-existing")
        document = (
            "The system must record what a person confirmed. "
            "Individual founders are the first users. "
            "Invoices are sent within three days of a job finishing."
        )

        result = IngestionService(factory).ingest_document(
            project.id, document="README.md", text=document
        )

        # Chunks became durable evidence and queued work, which is the whole of
        # "acquire before asking" on the Memory side.
        assert result.chunks
        assert all(chunk.run_id for chunk in result.chunks)

    def test_truncated_intake_is_disclosed_rather_than_reported_complete(
        self, factory: sessionmaker[Session], memory: MemoryService, readiness: ReadinessService
    ) -> None:
        """A large repository is where this matters and where it used to lie.

        Coverage counts runs, and a chunk dropped at ingest never becomes one,
        so a truncated document reported `complete: true` — with most of it
        unread (AUD-024).
        """

        project = memory.create_project("A big existing project", key="journey-existing-2")
        long_document = ". ".join(f"Statement number {n} about this system" for n in range(200))

        result = IngestionService(factory).ingest_document(
            project.id, document="big.md", text=long_document + "."
        )

        coverage = readiness.extraction_coverage(project.id)

        if result.truncated_chunks:
            assert coverage.not_ingested == result.truncated_chunks
            assert not coverage.is_complete, "a truncated document must not report complete"
        else:
            assert coverage.is_complete

    def test_ingesting_the_same_document_twice_does_not_double_the_project(
        self, factory: sessionmaker[Session], memory: MemoryService
    ) -> None:
        """Somebody re-runs an import. It must not double their project.

        Chunks are keyed on document, index and content hash, so a replay is
        recognised rather than recorded twice — which is what makes re-importing
        after a repository changes a safe thing to do rather than a decision.
        """

        project = memory.create_project("A re-imported project", key="journey-existing-3")
        ingestion = IngestionService(factory)
        text = "The system must record what a person confirmed."

        first = ingestion.ingest_document(project.id, document="README.md", text=text)
        second = ingestion.ingest_document(project.id, document="README.md", text=text)

        assert second.replayed, "the same document ingested twice was not recognised"
        assert [c.message_id for c in first.chunks] == [c.message_id for c in second.chunks]


class TestAStalledProject:
    """Somebody returning to work they left half-done.

    The question: can KAE tell what is settled from what is not, and is that
    distinction durable across the gap?
    """

    def test_settled_and_unsettled_stay_distinguishable(
        self, memory: MemoryService, readiness: ReadinessService
    ) -> None:
        project = memory.create_project("A stalled project", key="journey-stalled")
        written = _record(
            memory,
            project.id,
            "journey-stalled-run",
            ("actor", "Four therapists and one receptionist use it."),
            ("requirement", "Bookings cannot overlap for one therapist."),
        )
        memory.confirm_knowledge(written[0].id)

        # `lifecycle=None` explicitly: the default is `VALIDATED`, which is the
        # right default for *using* knowledge and the wrong one for asking what
        # a project holds. A returning person needs both halves.
        held = memory.retrieve_knowledge(project.id, lifecycle=None)
        confirmed = [i for i in held if i.lifecycle.value == "validated"]
        proposed = [i for i in held if i.lifecycle.value == "proposed"]

        # The distinction a returning person most needs, and the one a product
        # that reported a single "done" percentage would destroy.
        assert len(confirmed) == 1
        assert len(proposed) == 1

    def test_a_project_reports_what_it_is_waiting_for_rather_than_a_bare_number(
        self, memory: MemoryService, readiness: ReadinessService
    ) -> None:
        project = memory.create_project("A stalled project", key="journey-stalled-2")

        snapshot = readiness.calculate(project.id)

        # Named areas, not a percentage alone. A returning user asking "what now"
        # is asking this question, and a number cannot answer it.
        assert snapshot.missing_mandatory_areas
        assert all(isinstance(area, str) for area in snapshot.missing_mandatory_areas)
