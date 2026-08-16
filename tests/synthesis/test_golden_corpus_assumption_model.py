"""Golden corpus: thirteen assumption rows become ten beliefs and three separations.

`SYN-5d`, doc 05, `D-135`/`D-136`. The domain layer is tested in
`tests/domain/test_assumption_synthesis.py`; this is what the run persists — and,
more to the point, what it deliberately does not.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.application.assumption_synthesis_service import AssumptionSynthesisService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.synthesis import Authority, EvidenceRole, SynthesizedLifecycle
from kae_memory.domain.synthesizers.assumptions import ConsequenceDomain
from tests.synthesis.corpus import OBSERVATIONS, PARSER_SCAFFOLDING, count_by_kind
from tests.synthesis.load import load_golden_corpus


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, AssumptionSynthesisService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-assumptions")
    return memory, AssumptionSynthesisService(factory), SynthesisService(factory), project


def _scaffolding_statements() -> set[str]:
    return {
        observation.content
        for observation in OBSERVATIONS
        if PARSER_SCAFFOLDING in observation.cases
    }


class TestOnlyProjectBeliefsBecomeObjects:
    def test_the_scaffolding_rows_get_no_object_and_are_named_instead(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, assumptions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = assumptions.synthesize(project.id)

        considered = count_by_kind()[KnowledgeKind.ASSUMPTION.value]
        assert report.considered == considered
        assert len(report.assumptions) == considered - 3
        assert {statement for statement, _ in report.scaffolding} == _scaffolding_statements()
        stored = synthesis.list_objects(project.id, KnowledgeKind.ASSUMPTION.value)
        assert len(stored) == len(report.assumptions)
        assert _scaffolding_statements().isdisjoint({obj.statement for obj in stored})

    def test_the_stored_state_is_the_object_s_own_lifecycle(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-136`: there is no assumption table, so the object's lifecycle and
        authority *are* the assumption's state and cannot disagree with it."""

        memory, assumptions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        assumptions.synthesize(project.id)

        for obj in synthesis.list_objects(project.id, KnowledgeKind.ASSUMPTION.value):
            assert obj.lifecycle is SynthesizedLifecycle.WORKING
            assert obj.authority is Authority.WORKING_MODEL


class TestTheRunWritesNoEvidenceRole:
    """`D-136`. The store exists and the domain already names the role, so this
    is a refusal rather than an absence — `noise` is sticky against
    reconciliation and the record names no author, so a run could never correct
    its own write."""

    def test_every_considered_row_still_reads_active_after_a_run(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, assumptions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        assumptions.synthesize(project.id)

        items = memory.retrieve_knowledge(project.id, lifecycle=None)
        assumption_items = [item for item in items if item.kind == KnowledgeKind.ASSUMPTION.value]
        assert assumption_items
        for item in assumption_items:
            assert synthesis.evidence_role(item.id) is EvidenceRole.ACTIVE


class TestNothingBecomesAnInterruption:
    def test_the_attention_queue_is_empty_and_the_material_few_are_reported(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 05: *"Do not preserve stale assumptions as permanent review
        items."* Six of the ten are material and none of them interrupts."""

        memory, assumptions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = assumptions.synthesize(project.id)

        assert len(report.needing_validation) == 6
        assert synthesis.list_attention(project.id) == ()


class TestWhatTheRunPersists:
    def test_evidence_is_bound_and_no_extracted_row_is_touched(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, assumptions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)
        before = memory.retrieve_knowledge(project.id, lifecycle=None)

        report = assumptions.synthesize(project.id)

        after = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(after) == len(before)
        for assumption in report.assumptions:
            assert synthesis.list_bindings(project.id, assumption.object_id)

    def test_rerunning_writes_nothing_new(self, factory: sessionmaker[Session]) -> None:
        memory, assumptions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        first = assumptions.synthesize(project.id)
        second = assumptions.synthesize(project.id)

        assert second.replayed is True
        assert second.needing_validation == first.needing_validation
        assert [item.object_id for item in second.assumptions] == [
            item.object_id for item in first.assumptions
        ]
        stored = synthesis.list_objects(project.id, KnowledgeKind.ASSUMPTION.value)
        assert len(stored) == len(first.assumptions)
        assert {obj.revision for obj in stored} == {1}


class TestTheCorpusOutcomeIsPinned:
    """`EPI-0`'s habit: the numbers are the evidence, so a change to them is
    visible rather than absorbed."""

    def test_four_of_the_ten_say_nothing_about_what_they_would_cost(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, assumptions, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = assumptions.synthesize(project.id)

        assert report.by_consequence == {
            ConsequenceDomain.SCOPE: 3,
            ConsequenceDomain.ARCHITECTURE: 2,
            ConsequenceDomain.WORKFLOW: 1,
            ConsequenceDomain.UNDETERMINED: 4,
        }


class TestPersonAndProjectStateReachTheRun:
    """The corpus confirms no assumption and establishes nothing that answers
    one, so both branches are exercised on evidence written for them — the shape
    `SYN-5e` and `SYN-5f` both needed."""

    def test_a_confirmed_assumption_is_authoritative_rather_than_needing_validation(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, assumptions, synthesis, project = _services(factory)
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "assumption-confirmed")
        statement = "The deployment runs on a single machine for the first release."
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.ASSUMPTION.value, content=statement, source="fixture"
                )
            ],
            output_summary={"fixture": "assumption-confirmed"},
        )
        memory.confirm_knowledge(written[0].id)

        report = assumptions.synthesize(project.id)

        assert [item.settled for item in report.assumptions] == [True]
        assert report.needing_validation == ()
        stored = synthesis.list_objects(project.id, KnowledgeKind.ASSUMPTION.value)
        assert [obj.authority for obj in stored] == [Authority.HUMAN]

    def test_an_assumption_the_project_already_settled_is_retired_not_restated(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 05's *resolved into established knowledge*. Established rows are
        validated knowledge of another kind, so a validated assumption becomes
        authoritative rather than retiring itself (`D-136`)."""

        memory, assumptions, synthesis, project = _services(factory)
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "assumption-resolved")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.ASSUMPTION.value,
                    content="The project has a single user for MVP.",
                    source="fixture",
                ),
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.DECISION.value,
                    content="The project has a single confirmed user for the MVP release.",
                    source="fixture",
                ),
            ],
            output_summary={"fixture": "assumption-resolved"},
        )
        memory.confirm_knowledge(written[1].id)

        report = assumptions.synthesize(project.id)

        assert report.assumptions == ()
        assert len(report.resolved) == 1
        statement, reason = report.resolved[0]
        assert statement == "The project has a single user for MVP."
        assert "single confirmed user" in reason
        assert synthesis.list_objects(project.id, KnowledgeKind.ASSUMPTION.value) == ()

    def test_an_unconfirmed_answer_retires_nothing(self, factory: sessionmaker[Session]) -> None:
        """Established means the project settled it. KAE's own unconfirmed
        reading of the same subject is not an answer (`D-123`)."""

        memory, assumptions, _, project = _services(factory)
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "assumption-unsettled")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.ASSUMPTION.value,
                    content="The project has a single user for MVP.",
                    source="fixture",
                ),
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.DECISION.value,
                    content="The project has a single confirmed user for the MVP release.",
                    source="fixture",
                ),
            ],
            output_summary={"fixture": "assumption-unsettled"},
        )

        report = assumptions.synthesize(project.id)

        assert report.resolved == ()
        assert len(report.assumptions) == 1
