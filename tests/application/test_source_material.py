"""What a retention decision would apply to, before anything is removed (`D-170`).

`D-164` put the source on every ingestion run and `D-168` made the disposition
decidable, and the two were still two queries with nothing joining them — so no
reader could answer *what would a decision about this repository apply to*.

Nothing here enforces a disposition. A source classified `ephemeral` is counted
exactly like one classified `memory`, which is the state of the estate and is
asserted rather than left to be inferred from the absence of a deletion.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import IngestionService, MemoryService
from kae_memory.application.source_service import SourceService
from kae_memory.domain.models import KnowledgeSourceType

TEXT = "Staff submit monthly reports for their ministry. " * 20
LONGER = "Every ministry files a budget request each quarter. " * 200


@pytest.fixture
def wiring(
    factory: sessionmaker[Session],
) -> tuple[IngestionService, MemoryService, SourceService]:
    memory = MemoryService(factory)
    return IngestionService(factory, memory), memory, SourceService(factory)


class TestMaterialIsAttributedToTheSourceItWasReadFrom:
    def test_documents_and_bodies_are_counted_separately(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """Two numbers, because they answer different questions.

        `documents` is what a person chose; `stored_bodies` is how many copies
        of text that choice produced. A long file is one document and many
        bodies, and reporting only the first understates the decision.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="material-counts")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")

        small = ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        large = ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:src/api.py",
            LONGER,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )

        report = sources.material(project.id)

        assert len(report.sources) == 1
        entry = report.sources[0]
        assert entry.source_id == source.source_id
        assert entry.location == "crismag/reports"
        assert entry.documents == 2
        assert entry.stored_bodies == len(small.chunks) + len(large.chunks)
        assert entry.stored_bodies > entry.documents

    def test_a_registered_source_nobody_ingested_is_listed_at_zero(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """Zero is an answer. Omission is a query that failed to see the row."""

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="material-zero")
        read = sources.register(project.id, "github", "crismag/reports", "pinned")
        untouched = sources.register(project.id, "github", "crismag/specs", "connected")

        ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=read.source_id,
        )

        report = sources.material(project.id)

        by_id = {entry.source_id: entry for entry in report.sources}
        assert set(by_id) == {read.source_id, untouched.source_id}
        assert by_id[untouched.source_id].documents == 0
        assert by_id[untouched.source_id].stored_bodies == 0

    def test_another_projects_material_is_not_counted_here(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        ingestion, memory, sources = wiring
        mine = memory.create_project("Ministry reporting", key="material-mine")
        theirs = memory.create_project("Somebody else", key="material-theirs")
        elsewhere = sources.register(theirs.id, "github", "other/repo", "pinned")

        ingestion.ingest_document(
            theirs.id,
            "other/repo@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=elsewhere.source_id,
        )

        assert sources.material(mine.id) == sources.material(mine.id)
        report = sources.material(mine.id)
        assert report.sources == ()
        assert report.unattributed_bodies == 0


class TestMaterialNoDispositionCanReachIsSaidSeparately:
    def test_a_paste_is_unattributed_and_not_folded_into_a_source(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """The number a person most needs told.

        A pasted document has no source and no disposition can govern it, so
        adding it to a source's count would report a decision as reaching text
        it does not reach.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="material-paste")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")

        from_repository = ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        pasted = ingestion.ingest_document(project.id, "spec.md", TEXT)

        report = sources.material(project.id)

        assert report.sources[0].stored_bodies == len(from_repository.chunks)
        assert report.unattributed_documents == 1
        assert report.unattributed_bodies == len(pasted.chunks)


class TestNothingHereEnforcesADisposition:
    def test_ephemeral_material_is_counted_and_not_discarded(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """`D-169` is the owner's, so this reports the decision and acts on none.

        The claim the surface makes — *recorded, acted on by nothing* — is
        checked here rather than trusted to a docstring (`D-32`).
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="material-ephemeral")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        result = ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        sources.classify(project.id, source.source_id, "ephemeral")

        report = sources.material(project.id)

        entry = report.sources[0]
        assert entry.disposition == "ephemeral"
        assert entry.stored_bodies == len(result.chunks)

    def test_an_undecided_source_reports_no_disposition(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """Undecided stays `None` here as it does everywhere else (`D-168`)."""

        _, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="material-undecided")
        sources.register(project.id, "github", "crismag/reports", "pinned")

        assert sources.material(project.id).sources[0].disposition is None
