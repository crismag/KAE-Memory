"""Readiness per capability, and the gate that must never appear (N34).

The inspection that preceded this target found that **nothing currently blocks
generation on the readiness percentage**. That is the correct behaviour and it
is also undefended: a future check that refused to assemble below some threshold
would look reasonable in review, pass every existing test, and break the
product's central promise.

So the assertions here are mostly about what must *not* happen:

    sparse knowledge blocks nothing;
    a blocker does not spread beyond its own capability;
    "unavailable" always says why and what to do next.

The percentage stays. What it may mean is what changed: an indicator of how
well understood a project is, never a permission to act.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.capability_readiness_service import (
    SPARSE_KNOWLEDGE_THRESHOLD,
    CapabilityReadinessService,
)
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.acquisition import (
    BLOCKING,
    GENERATION_CAPABILITIES,
    PERMITTED,
    AcquisitionState,
    CapabilityReadiness,
    CapabilityState,
    ReadinessReport,
    quality_never_blocks,
)
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind


def _report(*capabilities: CapabilityReadiness, percentage: int = 12) -> ReadinessReport:
    return ReadinessReport(
        project_id="p1",
        acquisition_state=AcquisitionState.RECEIVING,
        percentage=percentage,
        capabilities=capabilities,
    )


class TestQualityIsNeverABlock:
    def test_no_blocking_state_is_about_knowledge_quality(self) -> None:
        """Every blocking state is a technical, authorisation, or integrity fact.

        None of them is "the knowledge is thin", and that split is the whole
        model.
        """

        assert {
            CapabilityState.NEEDS_CHOICE,
            CapabilityState.NEEDS_AUTHORIZATION,
            CapabilityState.BLOCKED_BY_INTEGRITY,
            CapabilityState.BLOCKED_BY_PROVIDER,
            CapabilityState.UNSUPPORTED,
        } == BLOCKING

    def test_degraded_still_permits(self) -> None:
        """A poorer result the user asked for is still the result they asked for."""

        assert CapabilityState.DEGRADED in PERMITTED

    def test_blocking_generation_for_quality_raises(self) -> None:
        """The regression guard, asserted directly.

        A future check that refused to assemble below a threshold would look
        reasonable in review and pass every other test.
        """

        with pytest.raises(DomainInvariantError, match="qualifies the output"):
            quality_never_blocks(
                _report(
                    CapabilityReadiness(
                        capability="knowledge.assemble",
                        state=CapabilityState.NEEDS_CHOICE,
                        reason="readiness is below 40%",
                        next_action="answer more questions",
                    )
                )
            )

    def test_authorisation_may_block_a_generation_capability(self) -> None:
        """Authorisation is a fact about an operation, not a judgement on knowledge."""

        quality_never_blocks(
            _report(
                CapabilityReadiness(
                    capability="deliverable.render",
                    state=CapabilityState.NEEDS_AUTHORIZATION,
                    reason="the renderer is not authorised in this deployment",
                    next_action="enable rendering",
                )
            )
        )

    def test_the_generation_capabilities_are_named(self) -> None:
        """Listed so the guard has something to check rather than a convention."""

        assert set(GENERATION_CAPABILITIES) == {
            "acquisition.continue",
            "knowledge.assemble",
            "deliverable.record",
            "deliverable.render",
        }


class TestAnUnavailableStateMustBeActionable:
    def test_a_blocked_capability_must_say_why(self) -> None:
        with pytest.raises(DomainInvariantError, match="must say why"):
            CapabilityReadiness(
                capability="deliverable.publish",
                state=CapabilityState.NEEDS_AUTHORIZATION,
                next_action="authorise the repository",
            )

    def test_a_blocked_capability_must_name_the_next_action(self) -> None:
        """Otherwise it is a dead end rather than a state."""

        with pytest.raises(DomainInvariantError, match="next useful action"):
            CapabilityReadiness(
                capability="deliverable.publish",
                state=CapabilityState.NEEDS_AUTHORIZATION,
                reason="the repository is not authorised",
            )

    def test_available_with_assumptions_must_name_them(self) -> None:
        """A caller cannot accept assumptions they were not shown."""

        with pytest.raises(DomainInvariantError, match="name the"):
            CapabilityReadiness(
                capability="knowledge.assemble",
                state=CapabilityState.AVAILABLE_WITH_ASSUMPTIONS,
            )

    def test_an_available_capability_needs_no_apology(self) -> None:
        entry = CapabilityReadiness(
            capability="knowledge.assemble", state=CapabilityState.AVAILABLE
        )

        assert entry.permitted is True


class TestABlockerDoesNotSpread:
    def test_one_blocked_capability_leaves_the_others_alone(self) -> None:
        report = _report(
            CapabilityReadiness("knowledge.assemble", CapabilityState.AVAILABLE),
            CapabilityReadiness("deliverable.record", CapabilityState.AVAILABLE),
            CapabilityReadiness(
                "deliverable.publish",
                CapabilityState.NEEDS_AUTHORIZATION,
                reason="GitHub is not authorised for this project",
                next_action="authorise the repository connection",
            ),
        )

        assert report.permits("knowledge.assemble") is True
        assert report.permits("deliverable.record") is True
        assert report.permits("deliverable.publish") is False
        assert [entry.capability for entry in report.blocked] == ["deliverable.publish"]

    def test_an_unknown_capability_is_permitted_rather_than_refused(self) -> None:
        """A gap in the report must not become a gate.

        Treating an unrecorded name as blocked would make every capability the
        report has not learned about yet unavailable by default.
        """

        assert _report().permits("something.new") is True

    def test_a_report_with_only_warnings_is_advisory(self) -> None:
        report = _report(
            CapabilityReadiness(
                "knowledge.assemble",
                CapabilityState.AVAILABLE_WITH_WARNINGS,
                reason="readiness is 12%",
            )
        )

        assert report.advisory_only is True


class TestAgainstARealProject:
    @pytest.fixture
    def service(self, factory: sessionmaker[Session]) -> CapabilityReadinessService:
        readiness = ReadinessService(factory)
        readiness.install_template()
        return CapabilityReadinessService(factory)

    @pytest.fixture
    def project_id(self, factory: sessionmaker[Session]) -> ProjectId:
        return MemoryService(factory).create_project("Sparse", key="n34-sparse").id

    def test_an_empty_project_can_still_do_everything_that_matters(
        self, service: CapabilityReadinessService, project_id: ProjectId
    ) -> None:
        """The scenario the whole target exists for: a one-sentence idea."""

        report = service.report(project_id)

        assert report.percentage < SPARSE_KNOWLEDGE_THRESHOLD
        for capability in GENERATION_CAPABILITIES:
            assert report.permits(capability), capability

    def test_sparse_knowledge_warns_rather_than_refuses(
        self, service: CapabilityReadinessService, project_id: ProjectId
    ) -> None:
        entry = service.report(project_id).for_capability("knowledge.assemble")

        assert entry is not None
        assert entry.permitted is True
        assert entry.state is CapabilityState.AVAILABLE_WITH_WARNINGS
        assert "generate now" in entry.next_action

    def test_the_percentage_travels_but_decides_nothing(
        self, service: CapabilityReadinessService, project_id: ProjectId
    ) -> None:
        """Kept because it is a useful indicator; removing it would push
        callers toward inventing a worse one."""

        report = service.report(project_id)

        assert isinstance(report.percentage, int)
        assert report.permits("knowledge.assemble") is True

    def test_knowledge_improves_the_wording_not_the_permission(
        self, factory: sessionmaker[Session], service: CapabilityReadinessService
    ) -> None:
        memory = MemoryService(factory)
        readiness = ReadinessService(factory)
        project = memory.create_project("Growing", key="n34-growing")
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "n34-seed")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    KnowledgeKind.CONSTRAINT.value, f"Constraint {index}.", "seed"
                )
                for index in range(6)
            ],
        )
        for item in written:
            readiness.assign_area(project.id, item.id, "constraints_and_assumptions")
            memory.confirm_knowledge(item.id)

        before_and_after = service.report(project.id)

        assert before_and_after.permits("knowledge.assemble") is True

    def test_publication_is_unsupported_and_says_what_that_means(
        self, service: CapabilityReadinessService, project_id: ProjectId
    ) -> None:
        """Unsupported rather than blocked: the caller cannot fix it yet."""

        entry = service.report(project_id).for_capability("deliverable.publish")

        assert entry is not None
        assert entry.state is CapabilityState.UNSUPPORTED
        assert "N27" in entry.reason
        assert "record and render" in entry.next_action

    def test_publication_being_unsupported_blocks_nothing_else(
        self, service: CapabilityReadinessService, project_id: ProjectId
    ) -> None:
        report = service.report(project_id)

        assert report.permits("deliverable.record") is True
        assert report.permits("deliverable.render") is True
