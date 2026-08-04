"""Purpose-bounded context assembly, with a manifest that can invalidate it.

The blueprint renders a whole project in one shape. An assembly renders the part
of it that serves one purpose, pinned to the exact knowledge revision it read, so
that what was generated can be traced, checked, and later found stale.

**Scope is `project` only.** `KAE_PACKAGE_MODEL.md` also specifies module-scoped
packages, and this deliberately does not implement them: modules are not a
knowledge kind, no relationship write path exists, and nothing traverses a
dependency graph. A module assembly built on top of those absences would be
inventing the boundary it claims to respect. Purpose is the axis available
today, and it is a real one.

Two manifest rules from that document are non-negotiable and are enforced here:

* ``source_knowledge`` is complete. An artifact that cannot name the knowledge it
  rendered cannot be invalidated when that knowledge changes.
* ``confirmation_state`` and ``unresolved_critical_gaps`` are always present,
  never empty-by-omission. An assembly may be incomplete; it may never be silent
  about being incomplete.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE, ReadinessTemplate
from kae_memory.persistence.transactions import RetryPolicy

from .blueprint_service import BlueprintService, StatementLabel
from .memory_service import MemoryService
from .readiness_service import ReadinessService
from .review_service import ReviewService, Severity

GENERATOR_VERSION = "1.0.0"
"""The assembler's own version.

Part of lineage: the same knowledge rendered by a different assembler is a
different artifact, and a reader comparing two packages needs to know which.
"""

PACKAGE_SCHEMA = "kae.package.v1"
"""The manifest contract, from KAE_PACKAGE_MODEL.md §1."""


class AssemblyPurpose(StrEnum):
    """What an assembly is for.

    The bound that makes a package smaller than the project. Each purpose names
    the discovery areas that serve it, so "everything needed to start
    implementing" is a different document from "everything needed to review the
    architecture" — assembled from one body of knowledge, without either
    carrying the other's noise.
    """

    DISCOVERY = "discovery"
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"


PURPOSE_AREAS: dict[AssemblyPurpose, tuple[str, ...]] = {
    AssemblyPurpose.DISCOVERY: (
        "problem_and_value",
        "users_and_stakeholders",
        "scope_and_boundaries",
        "constraints_and_assumptions",
    ),
    AssemblyPurpose.ARCHITECTURE: (
        "problem_and_value",
        "scope_and_boundaries",
        "quality_attributes",
        "domain_model_and_data",
        "interfaces_and_integrations",
        "constraints_and_assumptions",
    ),
    AssemblyPurpose.IMPLEMENTATION: (
        "functional_requirements",
        "domain_model_and_data",
        "interfaces_and_integrations",
        "acceptance_criteria",
        "constraints_and_assumptions",
    ),
}
"""Which areas each purpose reads.

Overlapping on purpose: constraints bind every audience, and a requirement
without its acceptance criteria is not implementable. What differs is what each
excludes.
"""


@dataclass(frozen=True, slots=True)
class AssembledStatement:
    """One statement, carrying everything needed to trace it."""

    knowledge_id: str
    kind: str
    text: str
    label: str
    area_key: str
    version: int
    lifecycle: str


@dataclass(frozen=True, slots=True)
class AssemblySection:
    """One area's contribution to an assembly."""

    area_key: str
    name: str
    statements: tuple[AssembledStatement, ...]


@dataclass(frozen=True, slots=True)
class ConfirmationState:
    """How much of an assembly a human has actually approved.

    Always rendered, including when everything is confirmed. A reader must never
    have to infer from an absent field that nothing was proposed.
    """

    confirmed: int
    proposed: int
    contested: int

    @property
    def total(self) -> int:
        return self.confirmed + self.proposed


@dataclass(frozen=True, slots=True)
class CriticalGap:
    """Something unresolved that the assembly is carrying anyway."""

    summary: str
    kind: str
    area_key: str | None = None


@dataclass(frozen=True, slots=True)
class AssemblyManifest:
    """Lineage and integrity for one assembly."""

    package_id: str
    project_id: str
    scope: str
    purpose: str
    knowledge_revision: int
    generated_at: datetime
    generator_version: str
    package_schema: str
    content_hash: str
    source_knowledge: tuple[str, ...]
    statement_count: int
    traced_statements: int
    confirmation_state: ConfirmationState
    unresolved_critical_gaps: tuple[CriticalGap, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def is_stale_against(self, current_revision: int) -> bool:
        """Return whether project knowledge has moved since this was generated."""

        return current_revision != self.knowledge_revision


@dataclass(frozen=True, slots=True)
class ContextAssembly:
    """A purpose-bounded view of a project, and the manifest that dates it."""

    manifest: AssemblyManifest
    sections: tuple[AssemblySection, ...]

    @property
    def statements(self) -> tuple[AssembledStatement, ...]:
        return tuple(s for section in self.sections for s in section.statements)


class AssemblyService:
    """Assembles the knowledge one purpose needs, and records what it read."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        memory: MemoryService | None = None,
        blueprint: BlueprintService | None = None,
        readiness: ReadinessService | None = None,
        review: ReviewService | None = None,
        template: ReadinessTemplate = SOFTWARE_TEMPLATE,
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._memory = memory or MemoryService(session_factory, policy)
        self._blueprint = blueprint or BlueprintService(session_factory, policy)
        self._readiness = readiness or ReadinessService(session_factory, policy)
        self._review = review or ReviewService(session_factory, policy)
        self._template = template
        self._clock = clock

    def assemble(
        self,
        project_id: ProjectId,
        purpose: AssemblyPurpose,
        include_proposed: bool = False,
    ) -> ContextAssembly:
        """Assemble the knowledge serving ``purpose``, pinned to one revision.

        The revision is read first and reported in the manifest. Everything
        rendered came from that revision, so a later reader can ask whether the
        project has moved rather than guessing from a timestamp.

        ``include_proposed`` carries unconfirmed candidates as well. Allowed,
        because an incomplete package is often still useful, and the manifest
        says exactly how much of it is unconfirmed — generation may be
        incomplete; it may never be silent.
        """

        project = self._memory.get_project(project_id)
        if project is None:
            raise LookupError(f"unknown project: {project_id}")

        revision = self._readiness.knowledge_revision(project_id)
        snapshot = self._readiness.latest(project_id) or self._readiness.calculate(project_id)
        blueprint = self._blueprint.generate(
            project_id,
            project.name,
            snapshot.percentage,
            snapshot.draft_eligible,
            snapshot.implementation_eligible,
            snapshot.missing_mandatory_areas,
        )

        wanted = set(PURPOSE_AREAS[purpose])
        names = {area.key: area.name for area in self._template.areas}
        sections: list[AssemblySection] = []
        for section in blueprint.sections:
            if section.area_key not in wanted:
                continue
            statements = tuple(
                AssembledStatement(
                    knowledge_id=str(statement.knowledge_item_id),
                    kind=statement.kind,
                    text=statement.text,
                    label=statement.label.value,
                    area_key=section.area_key,
                    version=1,
                    lifecycle=LifecycleState.VALIDATED.value,
                )
                for statement in section.statements
            )
            if statements:
                sections.append(
                    AssemblySection(
                        area_key=section.area_key,
                        name=names.get(section.area_key, section.area_name),
                        statements=statements,
                    )
                )

        proposed: tuple[AssembledStatement, ...] = ()
        if include_proposed:
            proposed = self._proposed_for(project_id, wanted)
            if proposed:
                sections.append(
                    AssemblySection(
                        area_key="unconfirmed",
                        name="Awaiting confirmation",
                        statements=proposed,
                    )
                )

        assembled = tuple(s for section in sections for s in section.statements)
        findings = self._review.findings(project_id)
        gaps = tuple(
            CriticalGap(summary=f.summary, kind=f.kind.value, area_key=f.area_key)
            for f in findings
            if f.severity is Severity.CRITICAL and (f.area_key is None or f.area_key in wanted)
        )

        warnings: list[str] = []
        empty = sorted(wanted - {section.area_key for section in sections})
        if empty:
            warnings.append(
                "No confirmed knowledge for "
                + ", ".join(names.get(key, key) for key in empty)
                + ". This assembly does not cover them."
            )
        if proposed:
            warnings.append(
                f"{len(proposed)} statement(s) are unconfirmed and are included because "
                "include_proposed was set. They are not approved project knowledge."
            )
        if not assembled:
            warnings.append(
                "Nothing was assembled: no confirmed knowledge serves this purpose yet."
            )

        manifest = AssemblyManifest(
            package_id=str(uuid4()),
            project_id=str(project_id),
            scope="project",
            purpose=purpose.value,
            knowledge_revision=revision,
            generated_at=self._clock(),
            generator_version=GENERATOR_VERSION,
            package_schema=PACKAGE_SCHEMA,
            content_hash=_content_hash(sections),
            # Complete by construction: every statement rendered contributes its
            # identifier. An artifact that cannot name what it rendered cannot be
            # invalidated when that knowledge changes.
            source_knowledge=tuple(s.knowledge_id for s in assembled),
            statement_count=len(assembled),
            traced_statements=sum(1 for s in assembled if s.knowledge_id),
            confirmation_state=ConfirmationState(
                confirmed=len(assembled) - len(proposed),
                proposed=len(proposed),
                contested=sum(1 for f in findings if f.kind.value == "unresolved_contradiction"),
            ),
            unresolved_critical_gaps=gaps,
            warnings=tuple(warnings),
        )
        return ContextAssembly(manifest=manifest, sections=tuple(sections))

    def is_stale(self, project_id: ProjectId, manifest: AssemblyManifest) -> bool:
        """Return whether the project has changed since ``manifest`` was made."""

        return manifest.is_stale_against(self._readiness.knowledge_revision(project_id))

    def _proposed_for(
        self, project_id: ProjectId, wanted: set[str]
    ) -> tuple[AssembledStatement, ...]:
        """Return unconfirmed candidates classified into the wanted areas."""

        links = {
            str(link.knowledge_item_id): link.area_key
            for link in self._readiness.area_links(project_id)
        }
        candidates = self._memory.retrieve_knowledge(project_id, lifecycle=LifecycleState.PROPOSED)
        return tuple(
            AssembledStatement(
                knowledge_id=str(item.id),
                kind=item.kind,
                text=item.current_version.content,
                label=StatementLabel.ASSUMPTION.value,
                area_key=links[str(item.id)],
                version=item.current_version.number,
                lifecycle=item.lifecycle.value,
            )
            for item in candidates
            if links.get(str(item.id)) in wanted
        )


@dataclass(frozen=True, slots=True)
class ArtifactEntry:
    """One file a package would contain, described without producing it.

    Metadata only. What the bytes look like is a rendering concern and belongs
    with whatever writes them; what a consumer needs to plan is the shape — how
    many artifacts, covering which areas, carrying how many statements, and
    whether any of them has changed.
    """

    path: str
    area_key: str
    title: str
    statement_count: int
    confirmed_count: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class PackageDescription:
    """A deterministic description of the artifacts a package would contain.

    Derived from the assembly alone, so the same knowledge at the same revision
    always describes the same package. Nothing is written and nothing is
    stored: a description is what lets a caller decide whether to render at
    all, and rendering belongs to whoever owns the destination.
    """

    package_id: str
    artifact_count: int
    total_statements: int
    artifacts: tuple[ArtifactEntry, ...]
    content_hash: str


def describe_package(assembly: ContextAssembly) -> PackageDescription:
    """Describe the artifacts ``assembly`` would produce, without producing them.

    One artifact per area that has content. An empty area yields no file rather
    than an empty one, so a consumer counting artifacts is counting things worth
    reading.
    """

    entries = tuple(
        ArtifactEntry(
            path=f"context/{assembly.manifest.purpose}/{section.area_key}.md",
            area_key=section.area_key,
            title=section.name,
            statement_count=len(section.statements),
            confirmed_count=sum(
                1 for s in section.statements if s.lifecycle == LifecycleState.VALIDATED.value
            ),
            content_hash=_content_hash((section,)),
        )
        for section in assembly.sections
        if section.statements
    )
    return PackageDescription(
        package_id=assembly.manifest.package_id,
        artifact_count=len(entries),
        total_statements=sum(entry.statement_count for entry in entries),
        artifacts=entries,
        content_hash=assembly.manifest.content_hash,
    )


def _content_hash(sections: Sequence[AssemblySection]) -> str:
    """Return a hash of the rendered content, for change detection.

    Over the text and its identifiers, not over the manifest: two assemblies of
    identical knowledge at different times must hash the same, or staleness
    detection would fire on every regeneration.
    """

    digest = sha256()
    for section in sections:
        digest.update(section.area_key.encode("utf-8"))
        for statement in section.statements:
            digest.update(statement.knowledge_id.encode("utf-8"))
            digest.update(statement.text.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


__all__ = [
    "GENERATOR_VERSION",
    "PACKAGE_SCHEMA",
    "PURPOSE_AREAS",
    "ArtifactEntry",
    "AssembledStatement",
    "AssemblyManifest",
    "AssemblyPurpose",
    "AssemblySection",
    "AssemblyService",
    "ConfirmationState",
    "ContextAssembly",
    "CriticalGap",
    "PackageDescription",
    "describe_package",
]
