"""Golden corpus: twelve requirements, and not one of them ready.

`SYN-5b`, doc 06, `D-129`/`D-131`. The domain layer is tested in
`tests/domain/test_requirement_synthesis.py`; this is what the run persists, and
what it refuses to persist.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.application.requirement_synthesis_service import RequirementSynthesisService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.synthesis import SynthesizedLifecycle
from kae_memory.domain.synthesizers.requirements import Verifiability
from tests.synthesis.corpus import count_by_kind
from tests.synthesis.load import load_golden_corpus

NOTES_PRESERVED = "Original source notes must be preserved."
RETRIEVABLE_AFTER_UPDATE = "A source note is retrievable after the item it backs is updated."


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, RequirementSynthesisService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-requirements")
    return memory, RequirementSynthesisService(factory), SynthesisService(factory), project


def _accepted_requirement(memory: MemoryService, project: Project, statement: str) -> None:
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "requirement-criteria")
    written = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind=KnowledgeKind.REQUIREMENT.value, content=statement, source="fixture"
            )
        ],
        output_summary={"fixture": "requirement-criteria"},
    )
    memory.confirm_knowledge(written[0].id)


class TestEveryRequirementBecomesAnObject:
    def test_each_requirement_observation_becomes_exactly_one_object(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, requirements, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = requirements.synthesize(project.id)

        expected = count_by_kind()[KnowledgeKind.REQUIREMENT.value]
        assert report.considered == expected
        assert len(report.requirements) == expected
        stored = synthesis.list_objects(project.id, KnowledgeKind.REQUIREMENT.value)
        assert len(stored) == expected
        assert {obj.lifecycle for obj in stored} == {SynthesizedLifecycle.WORKING}

    def test_the_corpus_reading_is_pinned(self, factory: sessionmaker[Session]) -> None:
        """`D-129`'s measurement, so a change to the patterns has to be argued.

        Eleven observable and one compound — doc 06's own *web and mobile*.
        """

        memory, requirements, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = requirements.synthesize(project.id)

        assert report.by_verifiability == {
            Verifiability.OBSERVABLE: 11,
            Verifiability.COMPOUND: 1,
        }
        assert len(report.splits) == 1
        assert report.reclassified == ()

    def test_a_compound_is_split_and_nothing_is_applied(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 06 says in those words that this must not be forced into a
        binary Confirm/Reject, so the split names halves and decides nothing."""

        memory, requirements, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = requirements.synthesize(project.id)

        split = report.splits[0]
        assert split.first and split.second and split.basis
        statements = {obj.statement for obj in synthesis.list_objects(project.id)}
        assert split.statement in statements
        assert split.first not in statements
        assert split.second not in statements


class TestKaeWritesNoAcceptanceCriteria:
    def test_the_run_stores_not_one_criterion(self, factory: sessionmaker[Session]) -> None:
        """`D-131`, and the guard the row exists for: a criterion KAE wrote
        would make its requirement ready by the act of synthesising it."""

        memory, requirements, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = requirements.synthesize(project.id)

        assert requirements.list_criteria(project.id) == ()
        assert all(one.criteria == () for one in report.requirements)

    def test_so_nothing_is_implementation_ready(self, factory: sessionmaker[Session]) -> None:
        """Doc 06's *candidate review dump*, measured rather than disguised."""

        memory, requirements, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = requirements.synthesize(project.id)

        assert report.implementation_ready == 0

    def test_nothing_reaches_the_attention_queue(self, factory: sessionmaker[Session]) -> None:
        """An unready requirement is a state of the model, not an interruption."""

        memory, requirements, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        requirements.synthesize(project.id)

        assert synthesis.list_attention(project.id) == ()


class TestOnlyAPersonMakesARequirementReady:
    def test_a_criterion_plus_acceptance_is_what_flips_it(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, requirements, _, project = _services(factory)
        _accepted_requirement(memory, project, NOTES_PRESERVED)

        before = requirements.synthesize(project.id)
        assert before.implementation_ready == 0

        requirements.record_criterion(
            project.id, before.requirements[0].object_id, RETRIEVABLE_AFTER_UPDATE
        )
        after = requirements.synthesize(project.id, idempotency_key="second")

        assert after.requirements[0].criteria == (RETRIEVABLE_AFTER_UPDATE,)
        assert after.implementation_ready == 1

    def test_an_unaccepted_requirement_stays_unready_however_it_is_worded(
        self, factory: sessionmaker[Session]
    ) -> None:
        """*Must* is the grammar of the sentence somebody wrote down (`D-129`)."""

        memory, requirements, _, project = _services(factory)
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "unaccepted")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.REQUIREMENT.value,
                    content=NOTES_PRESERVED,
                    source="fixture",
                )
            ],
            output_summary={"fixture": "unaccepted"},
        )

        first = requirements.synthesize(project.id)
        requirements.record_criterion(
            project.id, first.requirements[0].object_id, RETRIEVABLE_AFTER_UPDATE
        )
        report = requirements.synthesize(project.id, idempotency_key="second")

        assert report.requirements[0].accepted is False
        assert report.requirements[0].criteria == (RETRIEVABLE_AFTER_UPDATE,)
        assert report.implementation_ready == 0

    def test_re_adding_the_same_criterion_updates_rather_than_stacks(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, requirements, _, project = _services(factory)
        _accepted_requirement(memory, project, NOTES_PRESERVED)
        report = requirements.synthesize(project.id)
        object_id = report.requirements[0].object_id

        first = requirements.record_criterion(project.id, object_id, RETRIEVABLE_AFTER_UPDATE)
        second = requirements.record_criterion(
            project.id, object_id, RETRIEVABLE_AFTER_UPDATE.upper()
        )

        assert str(second.id) == str(first.id)
        stored = requirements.list_criteria(project.id, object_id)
        assert len(stored) == 1
        assert stored[0].statement == RETRIEVABLE_AFTER_UPDATE.upper()

    def test_rerunning_writes_nothing_new(self, factory: sessionmaker[Session]) -> None:
        memory, requirements, synthesis, project = _services(factory)
        _accepted_requirement(memory, project, NOTES_PRESERVED)

        first = requirements.synthesize(project.id)
        second = requirements.synthesize(project.id)

        assert second.replayed is True
        assert [one.object_id for one in second.requirements] == [
            one.object_id for one in first.requirements
        ]
        assert len(synthesis.list_objects(project.id, KnowledgeKind.REQUIREMENT.value)) == 1

    def test_no_extracted_row_is_touched(self, factory: sessionmaker[Session]) -> None:
        memory, requirements, synthesis, project = _services(factory)
        _accepted_requirement(memory, project, NOTES_PRESERVED)
        before = memory.retrieve_knowledge(project.id, lifecycle=None)

        report = requirements.synthesize(project.id)

        after = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(after) == len(before)
        for requirement in report.requirements:
            assert synthesis.list_bindings(project.id, requirement.object_id)
