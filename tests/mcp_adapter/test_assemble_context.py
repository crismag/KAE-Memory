"""The context assembly surface (T21).

Assembly is the product: the point where durable knowledge becomes something an
AI coding assistant can act on. Two properties make it usable rather than
merely present.

**Bounded.** A purpose names the areas that serve it, so an implementation
package does not carry the architecture review's noise. A package the size of
the project is a database dump with extra steps.

**Honest.** The manifest always states the confirmation split and every
unresolved gap the package carries. Generation may be incomplete; it may never
be silent — a reader who cannot tell a confirmed requirement from a candidate
will implement the candidate.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.ingestion_service import IngestionService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.workspace import SessionType
from kae_memory.mcp import tools
from kae_memory.mcp.errors import CapabilityUnavailableError, InvalidArgumentError
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

CONFIRMED = "Only an authorised approver may approve a report."
PROPOSED = "Approval authority should sit with the finance team."


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    memory = MemoryService(factory)
    return tools.ToolContext(
        memory=memory,
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        ingestion=IngestionService(factory, memory),
        assembly=AssemblyService(factory),
        embedder_name="deterministic",
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    """A project with one confirmed requirement, one candidate, one unknown."""

    project = context.memory.create_project("Ministry Reporting", key="ministry")
    session = context.memory.open_session(project.id, SessionType.DISCOVERY)
    message = context.memory.record_message(
        project.id, session.id, "Reports need approval before publication."
    ).message
    run = context.memory.start_run(project.id, AgentRole.REQUIREMENTS, "seed-1", session.id)
    written = context.memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(KnowledgeKind.REQUIREMENT.value, CONFIRMED, "seed", message.id),
            WriteKnowledgeRequest(KnowledgeKind.REQUIREMENT.value, PROPOSED, "seed", message.id),
            WriteKnowledgeRequest(
                KnowledgeKind.UNKNOWN.value,
                "Which role holds approval authority?",
                "seed",
                message.id,
            ),
        ],
    )
    confirmed = next(item for item in written if item.current_version.content == CONFIRMED)
    context.memory.confirm_knowledge(confirmed.id)
    context.readiness.assign_area(project.id, confirmed.id, "functional_requirements")

    # The candidate is classified too. An area link is how knowledge reaches a
    # section at all, so an unclassified candidate would be invisible to every
    # purpose and `include_proposed` would appear to do nothing.
    candidate = next(item for item in written if item.current_version.content == PROPOSED)
    context.readiness.assign_area(project.id, candidate.id, "functional_requirements")
    return str(project.id)


def _assemble(context: tools.ToolContext, project_id: str, **overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {"project_id": project_id}
    arguments.update(overrides)
    return dispatch(context, "kae_assemble_context", arguments)


class TestTheManifestIsAlwaysHonest:
    def test_confirmation_state_is_always_present(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Absent means "nothing proposed" to a reader, so it is never absent."""

        manifest = _assemble(context, project_id)["manifest"]

        assert set(manifest["confirmation_state"]) == {
            "confirmed",
            "proposed",
            "contested",
            "total",
        }

    def test_the_package_is_pinned_to_a_revision(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        manifest = _assemble(context, project_id)["manifest"]
        current = context.readiness.knowledge_revision(ProjectId(project_id))

        assert manifest["knowledge_revision"] == current

    def test_lineage_names_what_was_read(self, context: tools.ToolContext, project_id: str) -> None:
        """Without source_knowledge the package cannot be invalidated later."""

        manifest = _assemble(context, project_id)["manifest"]

        assert manifest["source_knowledge"]
        assert manifest["statement_count"] >= 1
        assert manifest["content_hash"].startswith("sha256:")

    def test_unresolved_gaps_travel_with_the_package(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The open question is the thing an implementer must not answer alone."""

        payload = _assemble(context, project_id)

        assert "unresolved_critical_gaps" in payload["manifest"]
        joined = " ".join(payload["guidance"]).lower()
        assert "do not choose an answer" in joined


class TestDeterminism:
    def test_the_same_revision_yields_the_same_hash(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A caller must be able to tell "same package" from "project moved"."""

        first = _assemble(context, project_id)["manifest"]
        second = _assemble(context, project_id)["manifest"]

        assert first["content_hash"] == second["content_hash"]
        assert first["knowledge_revision"] == second["knowledge_revision"]

    def test_new_knowledge_changes_the_package(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        before = _assemble(context, project_id)["manifest"]

        session = context.memory.sessions_for_project(ProjectId(project_id))[0]
        message = context.memory.record_message(
            ProjectId(project_id), session.id, "Rejected reports return to the submitter."
        ).message
        run = context.memory.start_run(
            ProjectId(project_id), AgentRole.REQUIREMENTS, "seed-2", session.id
        )
        written = context.memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    KnowledgeKind.REQUIREMENT.value,
                    "A rejected report returns to its submitter.",
                    "seed",
                    message.id,
                )
            ],
        )
        context.memory.confirm_knowledge(written[0].id)
        context.readiness.assign_area(
            ProjectId(project_id), written[0].id, "functional_requirements"
        )

        after = _assemble(context, project_id)["manifest"]

        assert after["knowledge_revision"] != before["knowledge_revision"]
        assert after["content_hash"] != before["content_hash"]


class TestBounding:
    def test_a_purpose_selects_its_areas(self, context: tools.ToolContext, project_id: str) -> None:
        """Implementation and discovery must not return the same document."""

        implementation = {section["area"] for section in _assemble(context, project_id)["sections"]}
        discovery = {
            section["area"]
            for section in _assemble(context, project_id, purpose="discovery")["sections"]
        }

        assert implementation != discovery

    def test_every_purpose_assembles(self, context: tools.ToolContext, project_id: str) -> None:
        for purpose in ("discovery", "architecture", "implementation"):
            payload = _assemble(context, project_id, purpose=purpose)
            assert payload["manifest"]["purpose"] == purpose

    def test_an_unknown_purpose_lists_the_valid_ones(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        with pytest.raises(InvalidArgumentError) as raised:
            tools.kae_assemble_context(context, project_id, purpose="everything")

        assert "implementation" in str(raised.value)


class TestProposedKnowledge:
    def test_candidates_are_excluded_by_default(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The default package is what a person has actually approved."""

        payload = _assemble(context, project_id)
        texts = [
            statement["text"]
            for section in payload["sections"]
            for statement in section["statements"]
        ]

        assert PROPOSED not in texts

    def test_including_candidates_is_declared_in_the_manifest(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Carrying unconfirmed content is allowed; hiding that it is unconfirmed is not."""

        payload = _assemble(context, project_id, include_proposed=True)

        assert payload["manifest"]["confirmation_state"]["proposed"] >= 1

    def test_every_statement_carries_its_lifecycle(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _assemble(context, project_id, include_proposed=True)

        for section in payload["sections"]:
            for statement in section["statements"]:
                assert statement["lifecycle"]
                assert statement["knowledge_id"]


class TestArgumentValidation:
    def test_an_unknown_project_is_structured(self, context: tools.ToolContext) -> None:
        payload = _assemble(context, "00000000-0000-0000-0000-000000000000")

        assert payload["error"] == "project_not_found"

    def test_the_capability_gap_is_reported_when_unwired(
        self, factory: sessionmaker[Session]
    ) -> None:
        readiness = ReadinessService(factory)
        readiness.install_template()
        bare = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
        )
        project = bare.memory.create_project("Unwired", key="unwired-assembly")

        with pytest.raises(CapabilityUnavailableError):
            tools.kae_assemble_context(bare, str(project.id))


class TestRegistration:
    def test_the_tool_is_declared(self) -> None:
        assert "kae_assemble_context" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_the_schema_is_strict_and_bounded(self) -> None:
        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_assemble_context")
        schema = definition["inputSchema"]

        assert schema["additionalProperties"] is False
        # `project_id` is no longer schema-required (T25.2): a project may be
        # named by key instead, and a call naming neither is answered by an
        # `invalid_argument` listing the keys this environment holds, which is
        # more use than a schema violation.
        assert "required" not in schema
        assert "project_key" in schema["properties"]
        assert set(schema["properties"]["purpose"]["enum"]) == {
            "discovery",
            "architecture",
            "implementation",
        }


class TestPackageDescription:
    """T22 — the artifacts a package would contain, described not produced.

    Nothing is written and nothing is stored. A description is what lets a
    caller decide whether to render at all, and rendering belongs to whoever
    owns the destination.
    """

    def test_a_package_is_described(self, context: tools.ToolContext, project_id: str) -> None:
        package = _assemble(context, project_id)["package"]

        assert package["artifact_count"] >= 1
        assert package["total_statements"] >= 1
        assert package["content_hash"].startswith("sha256:")

    def test_every_artifact_carries_a_path_and_its_own_hash(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Per-artifact hashes are what make partial staleness detectable."""

        for artifact in _assemble(context, project_id)["package"]["artifacts"]:
            assert artifact["path"].endswith(".md")
            assert artifact["content_hash"].startswith("sha256:")
            assert artifact["statements"] >= 1

    def test_the_description_is_deterministic(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Content is deterministic; identity is not, and the two are different things.

        ``package_id`` is a fresh identity per generation — it names this act of
        assembling. Everything describing *what was assembled* must be stable,
        or a caller could not tell "the package I already have" from "the
        project moved".
        """

        first = _assemble(context, project_id)["package"]
        second = _assemble(context, project_id)["package"]

        assert first["package_id"] != second["package_id"]
        assert first["content_hash"] == second["content_hash"]
        assert first["artifacts"] == second["artifacts"]
        assert first["total_statements"] == second["total_statements"]

    def test_empty_areas_produce_no_artifact(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A consumer counting artifacts should be counting things worth reading."""

        package = _assemble(context, project_id)["package"]

        assert all(artifact["statements"] > 0 for artifact in package["artifacts"])

    def test_candidates_get_their_own_artifact(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Unconfirmed content is a separate file, not mixed into a confirmed area.

        Mixing them would leave a reader deciding statement by statement what
        has been approved. A separate artifact makes the boundary a file
        boundary, which is much harder to read past by accident.
        """

        package = _assemble(context, project_id, include_proposed=True)["package"]
        paths = {artifact["area"]: artifact for artifact in package["artifacts"]}

        assert "unconfirmed" in paths, "candidates must be visible as their own artifact"
        assert paths["unconfirmed"]["confirmed"] == 0
        assert paths["functional_requirements"]["confirmed"] >= 1

    def test_a_purpose_change_changes_the_paths(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        implementation = {a["path"] for a in _assemble(context, project_id)["package"]["artifacts"]}
        discovery = {
            a["path"]
            for a in _assemble(context, project_id, purpose="discovery")["package"]["artifacts"]
        }

        assert implementation.isdisjoint(discovery) or implementation != discovery
