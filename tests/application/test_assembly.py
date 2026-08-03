"""Purpose-bounded assembly, and the manifest that lets it be invalidated.

A package is only trustworthy if it can say what it read, when, and how much of
it a human had approved. These cover the bound (a purpose reads less than the
whole project), the lineage (a pinned revision that goes stale), and the two
integrity rules that must never be silent.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import (
    AssemblyPurpose,
    AssemblyService,
    MemoryService,
    ReadinessService,
    WriteKnowledgeRequest,
)
from kae_memory.application.assembly_service import GENERATOR_VERSION, PACKAGE_SCHEMA
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId

SEED = [
    ("goal", "Every published report has an identifiable approver.", "problem_and_value"),
    ("actor", "Ministry leaders submit monthly reports.", "users_and_stakeholders"),
    (
        "requirement",
        "Only an authorised approver may approve a report.",
        "functional_requirements",
    ),
    ("rule", "A submitter cannot approve their own report.", "acceptance_criteria"),
    (
        "constraint",
        "Identity must come from the existing organisational directory.",
        "constraints_and_assumptions",
    ),
]


@pytest.fixture
def project(
    factory: sessionmaker[Session],
) -> tuple[AssemblyService, MemoryService, ReadinessService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="assembly")
    run = memory.start_run(proj.id, AgentRole.REQUIREMENTS, "seed")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content, _ in SEED
        ],
    )
    for item, (_, _, area) in zip(items, SEED, strict=True):
        memory.confirm_knowledge(item.id)
        readiness.assign_area(proj.id, item.id, area)
    return AssemblyService(factory), memory, readiness, proj.id


class TestThePurposeBounds:
    def test_an_assembly_reads_less_than_the_whole_project(self, project: tuple) -> None:
        """The point of a package: smaller than everything, by a stated rule."""

        assembly, _, _, project_id = project

        implementation = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        areas = {section.area_key for section in implementation.sections}
        assert "functional_requirements" in areas
        assert "users_and_stakeholders" not in areas, "actors do not serve implementation"

    def test_different_purposes_read_differently(self, project: tuple) -> None:
        assembly, _, _, project_id = project

        discovery = assembly.assemble(project_id, AssemblyPurpose.DISCOVERY)
        implementation = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        discovery_areas = {s.area_key for s in discovery.sections}
        implementation_areas = {s.area_key for s in implementation.sections}
        assert discovery_areas != implementation_areas
        assert "constraints_and_assumptions" in discovery_areas & implementation_areas

    def test_an_uncovered_area_is_reported_not_hidden(self, project: tuple) -> None:
        """Silence about what a package omits is the failure being designed out."""

        assembly, _, _, project_id = project

        architecture = assembly.assemble(project_id, AssemblyPurpose.ARCHITECTURE)

        assert architecture.manifest.warnings
        assert "does not cover" in architecture.manifest.warnings[0]


class TestLineage:
    def test_the_manifest_pins_the_revision_it_read(self, project: tuple) -> None:
        assembly, _, readiness, project_id = project

        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert result.manifest.knowledge_revision == readiness.knowledge_revision(project_id)
        assert result.manifest.generator_version == GENERATOR_VERSION
        assert result.manifest.package_schema == PACKAGE_SCHEMA
        assert result.manifest.scope == "project"

    def test_an_assembly_goes_stale_when_knowledge_changes(self, project: tuple) -> None:
        """The reason the revision is pinned at all."""

        assembly, memory, _, project_id = project
        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)
        assert assembly.is_stale(project_id, result.manifest) is False

        run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "later")
        memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(kind="requirement", content="A new rule.", source="s")],
        )

        assert assembly.is_stale(project_id, result.manifest) is True

    def test_identical_knowledge_hashes_identically(self, project: tuple) -> None:
        """Staleness must not fire on every regeneration."""

        assembly, _, _, project_id = project

        first = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)
        second = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert first.manifest.content_hash == second.manifest.content_hash
        assert first.manifest.package_id != second.manifest.package_id


class TestIntegrityIsNeverSilent:
    def test_source_knowledge_names_every_statement_rendered(self, project: tuple) -> None:
        """An artifact that cannot name what it read cannot be invalidated."""

        assembly, _, _, project_id = project

        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert len(result.manifest.source_knowledge) == result.manifest.statement_count
        assert set(result.manifest.source_knowledge) == {s.knowledge_id for s in result.statements}
        assert result.manifest.traced_statements == result.manifest.statement_count

    def test_confirmation_state_is_present_even_when_all_confirmed(self, project: tuple) -> None:
        """Never empty-by-omission: a reader must not infer from an absent field."""

        assembly, _, _, project_id = project

        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert result.manifest.confirmation_state.proposed == 0
        assert result.manifest.confirmation_state.confirmed == result.manifest.statement_count

    def test_unconfirmed_statements_are_counted_and_flagged(self, project: tuple) -> None:
        assembly, memory, readiness, project_id = project
        run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "candidate")
        item = memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(kind="requirement", content="An unreviewed rule.", source="s")],
        )[0]
        readiness.assign_area(project_id, item.id, "functional_requirements")

        result = assembly.assemble(
            project_id, AssemblyPurpose.IMPLEMENTATION, include_proposed=True
        )

        assert result.manifest.confirmation_state.proposed == 1
        assert any("unconfirmed" in warning for warning in result.manifest.warnings)

    def test_unconfirmed_statements_are_excluded_by_default(self, project: tuple) -> None:
        assembly, memory, readiness, project_id = project
        run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "candidate")
        item = memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(kind="requirement", content="An unreviewed rule.", source="s")],
        )[0]
        readiness.assign_area(project_id, item.id, "functional_requirements")

        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert result.manifest.confirmation_state.proposed == 0
        assert "An unreviewed rule." not in [s.text for s in result.statements]

    def test_critical_gaps_travel_with_the_package(self, project: tuple) -> None:
        """An incomplete package may generate; it may not hide why."""

        assembly, _, _, project_id = project

        result = assembly.assemble(project_id, AssemblyPurpose.ARCHITECTURE)

        assert result.manifest.unresolved_critical_gaps
        assert all(gap.summary for gap in result.manifest.unresolved_critical_gaps)

    def test_an_empty_assembly_says_so(self, factory: sessionmaker[Session]) -> None:
        assembly = AssemblyService(factory)
        memory = MemoryService(factory)
        ReadinessService(factory).install_template()
        empty = memory.create_project("Empty", key="assembly-empty")

        result = assembly.assemble(empty.id, AssemblyPurpose.IMPLEMENTATION)

        assert result.statements == ()
        assert any("Nothing was assembled" in w for w in result.manifest.warnings)


class TestTraceability:
    def test_every_statement_keeps_its_identifier_and_label(self, project: tuple) -> None:
        assembly, _, _, project_id = project

        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert result.statements
        assert all(s.knowledge_id for s in result.statements)
        assert all(s.label in {"grounded", "derived", "assumption"} for s in result.statements)
        assert all(s.area_key for s in result.statements)


class TestScopeBoundary:
    def test_only_project_scope_exists(self, project: tuple) -> None:
        """Module scope is specified but not implemented, and does not pretend to be.

        Building it on absent modules, relationships, and traversal would invent
        the boundary it claims to respect.
        """

        assembly, _, _, project_id = project

        result = assembly.assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert result.manifest.scope == "project"
        assert not hasattr(result.manifest, "module_key")
