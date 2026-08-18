"""A source that read 412 files names them (`D-259`).

`material` (`D-170`) answers *how much* text stands under a source, and that is
not the question somebody deciding whether the include paths caught what they
meant is asking. The run already recorded the coordinate it read (`D-164`); the
only query that touched it grouped on it and threw it away.

Nothing here follows a document to the statements it produced. That is a further
join and a further row, and the boundary is asserted rather than left implied.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import IngestionService, MemoryService
from kae_memory.application.source_service import (
    MAX_DOCUMENT_LIMIT,
    SourceNotFoundError,
    SourceService,
)
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.models import KnowledgeSourceType

TEXT = "Staff submit monthly reports for their ministry. " * 20
LONGER = "Every ministry files a budget request each quarter. " * 200

Wiring = tuple[IngestionService, MemoryService, SourceService]


@pytest.fixture
def wiring(factory: sessionmaker[Session]) -> Wiring:
    memory = MemoryService(factory)
    return IngestionService(factory, memory), memory, SourceService(factory)


class TestASourceNamesWhatItRead:
    def test_each_ingested_document_is_named_with_its_own_coordinate(self, wiring: Wiring) -> None:
        """The paths themselves, which a count cannot give.

        A person checking whether the include paths caught what they meant needs
        `src/api.py`, not the number 2.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-named")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        for path in ("README.md", "src/api.py"):
            ingestion.ingest_document(
                project.id,
                f"crismag/reports@abc1234:{path}",
                TEXT,
                source_type=KnowledgeSourceType.REPOSITORY,
                source_id=source.source_id,
            )

        listing = sources.documents(project.id, source.source_id)

        assert [entry.document for entry in listing.documents] == [
            "crismag/reports@abc1234:README.md",
            "crismag/reports@abc1234:src/api.py",
        ]
        assert listing.total_documents == 2
        assert listing.truncated is False

    def test_a_long_file_is_one_document_and_several_bodies(self, wiring: Wiring) -> None:
        """The distinction `material` draws, held per document.

        A file that chunked into thirty bodies is still one thing somebody
        chose to read, and a listing that showed it thirty times would report
        the chunker's behaviour as the reader's decision.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-bodies")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        result = ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:src/api.py",
            LONGER,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )

        listing = sources.documents(project.id, source.source_id)

        assert listing.total_documents == 1
        assert listing.documents[0].stored_bodies == len(result.chunks)
        assert listing.documents[0].stored_bodies > 1

    def test_a_document_says_when_it_was_last_read(self, wiring: Wiring) -> None:
        """Re-reading a file updates when, and does not add a second row."""

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-last-read")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        coordinate = "crismag/reports@abc1234:README.md"
        ingestion.ingest_document(
            project.id,
            coordinate,
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        first = sources.documents(project.id, source.source_id).documents[0]

        ingestion.ingest_document(
            project.id,
            coordinate,
            TEXT + " Amended.",
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        again = sources.documents(project.id, source.source_id)

        assert again.total_documents == 1
        assert again.documents[0].last_read_at is not None
        assert first.last_read_at is not None
        assert again.documents[0].last_read_at >= first.last_read_at

    def test_a_source_nobody_ingested_names_nothing(self, wiring: Wiring) -> None:
        """Empty is an answer, and a different one from a missing source."""

        _, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-empty")
        source = sources.register(project.id, "github", "crismag/specs", "connected")

        listing = sources.documents(project.id, source.source_id)

        assert listing.documents == ()
        assert listing.total_documents == 0
        assert listing.truncated is False


class TestOnlyThisSourcesDocumentsAreNamed:
    def test_a_paste_belongs_to_no_source_and_is_not_listed(self, wiring: Wiring) -> None:
        """A pasted document has no source, so no source may claim it."""

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-paste")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        ingestion.ingest_document(project.id, "pasted-spec.md", TEXT)

        listing = sources.documents(project.id, source.source_id)

        assert [entry.document for entry in listing.documents] == [
            "crismag/reports@abc1234:README.md"
        ]

    def test_a_sibling_sources_documents_stay_with_it(self, wiring: Wiring) -> None:
        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-siblings")
        reports = sources.register(project.id, "github", "crismag/reports", "pinned")
        specs = sources.register(project.id, "github", "crismag/specs", "pinned")
        ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=reports.source_id,
        )
        ingestion.ingest_document(
            project.id,
            "crismag/specs@def5678:SPEC.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=specs.source_id,
        )

        assert [
            entry.document for entry in sources.documents(project.id, specs.source_id).documents
        ] == ["crismag/specs@def5678:SPEC.md"]

    def test_a_source_from_another_project_is_not_found_here(self, wiring: Wiring) -> None:
        _, memory, sources = wiring
        mine = memory.create_project("Ministry reporting", key="docs-mine")
        theirs = memory.create_project("Somebody else", key="docs-theirs")
        elsewhere = sources.register(theirs.id, "github", "other/repo", "pinned")

        with pytest.raises(SourceNotFoundError):
            sources.documents(mine.id, elsewhere.source_id)


class TestATruncatedListingSaysSo:
    def test_the_ceiling_applies_to_documents_and_the_total_is_still_reported(
        self, wiring: Wiring
    ) -> None:
        """The guard against a list that passes for the whole set.

        A repository ingested whole is one document per file. A page told only
        the length of what it received would say *3 documents* about a source
        that read five, which is the failure `AUD-009` names: a surface
        describing something the system did not do.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-ceiling")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        for index in range(5):
            ingestion.ingest_document(
                project.id,
                f"crismag/reports@abc1234:file{index}.md",
                TEXT,
                source_type=KnowledgeSourceType.REPOSITORY,
                source_id=source.source_id,
            )

        listing = sources.documents(project.id, source.source_id, limit=3)

        assert len(listing.documents) == 3
        assert listing.total_documents == 5
        assert listing.truncated is True

    def test_the_visible_prefix_is_the_same_one_every_time(self, wiring: Wiring) -> None:
        """Ordered by coordinate, so re-ingesting does not shuffle the window.

        Under a recency order, reading `file4.md` again would silently change
        which three files a truncated list shows without anything new having
        been read.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-stable")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        for index in range(5):
            ingestion.ingest_document(
                project.id,
                f"crismag/reports@abc1234:file{index}.md",
                TEXT,
                source_type=KnowledgeSourceType.REPOSITORY,
                source_id=source.source_id,
            )
        before = sources.documents(project.id, source.source_id, limit=3)

        ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:file4.md",
            TEXT + " Amended.",
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        after = sources.documents(project.id, source.source_id, limit=3)

        assert [entry.document for entry in before.documents] == [
            f"crismag/reports@abc1234:file{index}.md" for index in range(3)
        ]
        assert [entry.document for entry in after.documents] == [
            entry.document for entry in before.documents
        ]

    def test_a_limit_past_the_cap_is_refused_rather_than_quietly_shrunk(
        self, wiring: Wiring
    ) -> None:
        """Clamping would make `truncated` mean two different things.

        *There are more documents* and *you may not have them all at once* are
        different answers, and a caller handed the second while reading the
        first would present a capped list as the repository's full extent.
        """

        _, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-cap")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")

        with pytest.raises(DomainInvariantError):
            sources.documents(project.id, source.source_id, limit=MAX_DOCUMENT_LIMIT + 1)
        with pytest.raises(DomainInvariantError):
            sources.documents(project.id, source.source_id, limit=0)


class TestStoppingASourceDoesNotHideWhatItTaught:
    def test_a_retired_source_still_names_its_documents(self, wiring: Wiring) -> None:
        """`D-230`: stopping is not deleting, so the list cannot go with it.

        Somebody who stopped a source is the reader most likely to want to know
        what it already put into KAE.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="docs-retired")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")
        ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:README.md",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )
        sources.stop_reading(project.id, source.source_id)

        listing = sources.documents(project.id, source.source_id)

        assert [entry.document for entry in listing.documents] == [
            "crismag/reports@abc1234:README.md"
        ]
