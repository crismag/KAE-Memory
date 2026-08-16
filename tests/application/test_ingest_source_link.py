"""The link between a stored chunk and the source it was read out of (`D-164`).

`ADR-0004` step 3 wants a repository to stop being copied into Memory in full,
and the disposition that decides whether a body may be kept lives on
`project_sources`. Nothing connected the two: an ingestion recorded what *kind*
of source the text came from and never *which* source, so no retention pass
could find the rows a decision about one repository applied to.

The field is checked where it is written rather than where it is read. An
identifier naming no source is refused at ingest, because the alternative is a
dangling link discovered later by the one caller whose job is deleting things.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import IngestionService, MemoryService
from kae_memory.application.memory_service import source_id_for_run
from kae_memory.application.source_service import SourceNotFoundError, SourceService
from kae_memory.domain.models import KnowledgeSourceType

TEXT = "Staff submit monthly reports for their ministry. " * 20


@pytest.fixture
def wiring(
    factory: sessionmaker[Session],
) -> tuple[IngestionService, MemoryService, SourceService]:
    memory = MemoryService(factory)
    return IngestionService(factory, memory), memory, SourceService(factory)


class TestAnIngestionNamesWhereItReadFrom:
    def test_every_run_carries_the_source(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """Every chunk, not the first one.

        A retention decision is about the material, and a document that split
        into thirty chunks would leave twenty-nine of them unattributable if the
        link were carried once.
        """

        ingestion, memory, sources = wiring
        project = memory.create_project("Ministry reporting", key="link-carry")
        source = sources.register(project.id, "github", "crismag/reports", "pinned")

        result = ingestion.ingest_document(
            project.id,
            "crismag/reports@abc1234:src/api.py",
            TEXT,
            source_type=KnowledgeSourceType.REPOSITORY,
            source_id=source.source_id,
        )

        runs = {run.id: run for run in memory.runs_for_project(project.id)}
        assert result.chunks
        for chunk in result.chunks:
            assert source_id_for_run(runs[chunk.run_id]) == source.source_id

    def test_a_paste_names_none_and_is_not_given_one(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """Absent, not a default.

        A run pointed at a source nobody named would be a retention decision
        taken about somebody else's material.
        """

        ingestion, memory, _ = wiring
        project = memory.create_project("Ministry reporting", key="link-paste")

        result = ingestion.ingest_document(project.id, "spec.md", TEXT)

        runs = {run.id: run for run in memory.runs_for_project(project.id)}
        assert result.chunks
        for chunk in result.chunks:
            run = runs[chunk.run_id]
            assert source_id_for_run(run) is None
            assert "source_id" not in (run.input_context or {})


class TestAnIdentifierNamingNoSourceIsRefused:
    def test_an_unknown_source_refuses_before_anything_is_written(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """The refusal is the reader that keeps the field honest.

        Stored and unchecked, it would be a string nothing verifies until the
        retention pass reads it — and that reader deletes.
        """

        ingestion, memory, _ = wiring
        project = memory.create_project("Ministry reporting", key="link-unknown")

        with pytest.raises(SourceNotFoundError):
            ingestion.ingest_document(
                project.id,
                "spec.md",
                TEXT,
                source_id="99999999-9999-9999-9999-999999999999",
            )

        assert memory.runs_for_project(project.id) == ()

    def test_another_projects_source_is_not_this_projects_source(
        self, wiring: tuple[IngestionService, MemoryService, SourceService]
    ) -> None:
        """Ownership, not existence. The identifier resolves and still refuses."""

        ingestion, memory, sources = wiring
        mine = memory.create_project("Ministry reporting", key="link-mine")
        theirs = memory.create_project("Somebody else", key="link-theirs")
        elsewhere = sources.register(theirs.id, "github", "other/repo", "pinned")

        with pytest.raises(SourceNotFoundError):
            ingestion.ingest_document(mine.id, "spec.md", TEXT, source_id=elsewhere.source_id)

        assert memory.runs_for_project(mine.id) == ()
