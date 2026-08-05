"""Generation modes and inclusion classes (N37).

A mode says what the output is *for*. It widens what is included and qualifies
the result — and it never refuses. That is the whole design, and it is the part
most at risk, because the opposite reads as prudence: "build mode requires
confirmed requirements" would reintroduce the readiness gate N34 removed,
wearing different words, and nothing else in the codebase would notice.

The second thing here is a conflation being undone. `StatementLabel` says where
authority comes from — grounded, derived, assumed — computed from provenance.
Assembly was using `assumption` to mean "nobody has confirmed this", which made
a statement KAE inferred and a statement awaiting review the same word. They
answer different questions and now have different fields.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyPurpose, AssemblyService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.generation import (
    DEFAULT_INCLUSIONS,
    HISTORICAL,
    GenerationMode,
    InclusionClass,
    inclusions_for,
    mode_never_blocks,
    qualifications,
)
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind


class TestAModeNeverGates:
    @pytest.mark.parametrize("mode", list(GenerationMode))
    def test_every_mode_includes_something(self, mode: GenerationMode) -> None:
        """A mode that includes nothing is a mode that cannot generate."""

        mode_never_blocks(mode)
        assert DEFAULT_INCLUSIONS[mode]

    @pytest.mark.parametrize("mode", list(GenerationMode))
    def test_every_mode_admits_confirmed_knowledge(self, mode: GenerationMode) -> None:
        assert InclusionClass.CONFIRMED in DEFAULT_INCLUSIONS[mode]

    def test_build_admits_unconfirmed_statements(self) -> None:
        """The assertion that stops the gate returning in new words.

        "Build requires confirmed requirements" reads as prudence and is the
        readiness gate again. A caller asking for a build package from an idea
        gets one, qualified rather than withheld.
        """

        assert InclusionClass.PROPOSED in DEFAULT_INCLUSIONS[GenerationMode.BUILD]

    def test_a_mode_only_ever_widens(self) -> None:
        """A caller cannot ask for less than the mode implies.

        Narrowing is the shape a gate would need, so the function does not
        offer it.
        """

        widened = inclusions_for(GenerationMode.VALIDATE, frozenset({InclusionClass.PROPOSED}))

        assert DEFAULT_INCLUSIONS[GenerationMode.VALIDATE] <= widened
        assert InclusionClass.PROPOSED in widened

    def test_validation_narrows_toward_disagreement_not_away_from_doubt(self) -> None:
        """The one mode that includes less includes *assumptions and
        contradictions*, which is what a reviewer most needs to see."""

        validate = DEFAULT_INCLUSIONS[GenerationMode.VALIDATE]

        assert InclusionClass.DISPUTED in validate
        assert InclusionClass.ASSUMED in validate

    def test_history_is_excluded_from_every_default(self) -> None:
        """Rejected and superseded are history, not active recommendations.

        Asking for them is a different request, and allowed.
        """

        for classes in DEFAULT_INCLUSIONS.values():
            assert not (classes & HISTORICAL)

    def test_a_mode_configured_to_include_nothing_raises(self) -> None:
        original = DEFAULT_INCLUSIONS[GenerationMode.BUILD]
        DEFAULT_INCLUSIONS[GenerationMode.BUILD] = frozenset()
        try:
            with pytest.raises(DomainInvariantError, match="does not gate it"):
                mode_never_blocks(GenerationMode.BUILD)
        finally:
            DEFAULT_INCLUSIONS[GenerationMode.BUILD] = original


class TestQualificationReplacesRefusal:
    def test_proposed_content_is_disclosed(self) -> None:
        lines = qualifications(GenerationMode.BUILD, frozenset({InclusionClass.PROPOSED}))

        assert any("nobody has confirmed" in line for line in lines)
        assert any("candidates rather than decisions" in line for line in lines)

    def test_a_build_package_with_nothing_confirmed_says_so(self) -> None:
        """Useful, and not a production commitment. Saying so is the difference."""

        lines = qualifications(GenerationMode.BUILD, frozenset({InclusionClass.PROPOSED}))

        assert any("not evidence of production readiness" in line for line in lines)

    def test_a_contradiction_is_preserved_rather_than_resolved(self) -> None:
        lines = qualifications(GenerationMode.EXPLORE, frozenset({InclusionClass.DISPUTED}))

        assert any("do not choose between them" in line for line in lines)

    def test_assumptions_are_disclosed_with_their_cost(self) -> None:
        lines = qualifications(GenerationMode.PLAN, frozenset({InclusionClass.ASSUMED}))

        assert any("what it would cost if wrong" in line for line in lines)

    def test_a_fully_confirmed_package_needs_no_apology(self) -> None:
        assert qualifications(GenerationMode.BUILD, frozenset({InclusionClass.CONFIRMED})) == ()


class TestInclusionClassIsNotAuthority:
    """The conflation N37 undoes."""

    @pytest.fixture
    def project_id(self, factory: sessionmaker[Session]) -> ProjectId:
        readiness = ReadinessService(factory)
        readiness.install_template()
        memory = MemoryService(factory)
        project = memory.create_project("Modes", key="n37-modes")
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "n37-seed")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    KnowledgeKind.CONSTRAINT.value, "Reports are retained.", "seed"
                )
            ],
        )
        readiness.assign_area(project.id, written[0].id, "constraints_and_assumptions")
        return project.id

    def test_a_proposed_statement_is_no_longer_labelled_an_assumption(
        self, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        """It came from extraction over real evidence.

        Whether a person has ruled on it is a different question from where its
        authority comes from, and they used to share one word.
        """

        assembled = AssemblyService(factory).assemble(
            project_id, AssemblyPurpose.IMPLEMENTATION, include_proposed=True
        )

        statements = assembled.statements
        assert statements
        assert all(s.label != "assumption" for s in statements)
        assert all(s.inclusion_class == InclusionClass.PROPOSED.value for s in statements)

    def test_the_two_fields_answer_different_questions(
        self, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        assembled = AssemblyService(factory).assemble(
            project_id, AssemblyPurpose.IMPLEMENTATION, include_proposed=True
        )

        statement = assembled.statements[0]
        assert statement.label in {"grounded", "derived", "assumption"}
        assert statement.inclusion_class in {c.value for c in InclusionClass}
        assert statement.lifecycle == "proposed"


class TestModeIsOptIn:
    """An unnamed mode changes nothing, so no default moves under a caller."""

    @pytest.fixture
    def project_id(self, factory: sessionmaker[Session]) -> ProjectId:
        readiness = ReadinessService(factory)
        readiness.install_template()
        memory = MemoryService(factory)
        project = memory.create_project("OptIn", key="n37-optin")
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "n37-optin-seed")
        written = memory.write_knowledge(
            run.id,
            [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, "Retained.", "seed")],
        )
        readiness.assign_area(project.id, written[0].id, "constraints_and_assumptions")
        return project.id

    def test_without_a_mode_unconfirmed_content_is_still_excluded_by_default(
        self, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        """The pre-N37 contract, preserved.

        Changing what an existing caller receives without them asking is the
        same failure as an override silently becoming a default.
        """

        assembled = AssemblyService(factory).assemble(project_id, AssemblyPurpose.IMPLEMENTATION)

        assert assembled.manifest.confirmation_state.proposed == 0

    def test_naming_a_mode_widens_it(
        self, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        assembled = AssemblyService(factory).assemble(
            project_id, AssemblyPurpose.IMPLEMENTATION, mode=GenerationMode.EXPLORE
        )

        assert assembled.manifest.confirmation_state.proposed > 0

    def test_every_mode_produces_a_package_from_a_sparse_project(
        self, factory: sessionmaker[Session], project_id: ProjectId
    ) -> None:
        """The end-to-end form of "a mode never gates"."""

        service = AssemblyService(factory)

        for mode in GenerationMode:
            assembled = service.assemble(project_id, AssemblyPurpose.IMPLEMENTATION, mode=mode)
            assert assembled.manifest.content_hash, mode.value
