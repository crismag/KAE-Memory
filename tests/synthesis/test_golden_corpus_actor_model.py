"""Golden corpus: 22 peer actor rows become a role model that says who owns what.

`SYN-5a`, doc 03, `D-120`/`D-121`. The domain layer is tested in
`tests/domain/test_actor_synthesis.py`; this is what the run persists.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.application.actor_synthesis_service import ActorSynthesisService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.synthesis import AttentionKind
from kae_memory.domain.synthesizers.actors import RoleKind
from tests.synthesis.corpus import HEADLINE_COUNTS
from tests.synthesis.load import load_golden_corpus


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, ActorSynthesisService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-actors")
    return memory, ActorSynthesisService(factory), SynthesisService(factory), project


class TestTheRoleModelIsTheRelation:
    def test_every_actor_observation_becomes_exactly_one_role(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, actors, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)

        expected = HEADLINE_COUNTS[KnowledgeKind.ACTOR.value]
        assert report.considered == expected
        assert len(report.roles) == expected
        stored = synthesis.list_objects(project.id, KnowledgeKind.ACTOR.value)
        assert len(stored) == expected

    def test_the_cast_list_does_not_shrink_and_the_run_says_so(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-121`: nothing is clustered, and an uncompacted model must not read
        like a compacted one."""

        memory, actors, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)

        assert report.clustered is False
        assert len(report.roles) == report.considered

    def test_a_role_holding_nothing_anywhere_is_a_persona(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 03 line 10, decided by the relation rather than a word list."""

        memory, actors, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)

        holders = {statement for statement, _, _ in report.assignments}
        for _, statement, kind in report.roles:
            if kind is RoleKind.PERSONA:
                assert statement not in holders
        assert report.personas

    def test_a_role_that_holds_something_is_never_rendered_a_persona(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, actors, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)

        holders = {statement for statement, _, _ in report.assignments}
        rendered = {statement: kind for _, statement, kind in report.roles}
        for statement in holders:
            assert rendered[statement] is not RoleKind.PERSONA


class TestWhatTheRunPersists:
    def test_each_assignment_is_a_stored_cell_with_its_basis(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, actors, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)
        stored = synthesis.list_assignments(project.id)

        assert len(stored) == len(report.assignments)
        for record in stored:
            assert record.basis.strip()
            assert record.subject_key.strip()

    def test_evidence_is_bound_and_no_extracted_row_is_touched(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, actors, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)
        before = memory.retrieve_knowledge(project.id, lifecycle=None)

        report = actors.synthesize(project.id)

        after = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(after) == len(before)
        for object_id, _, _ in report.roles:
            assert synthesis.list_bindings(project.id, object_id)

    def test_rerunning_writes_nothing_new(self, factory: sessionmaker[Session]) -> None:
        memory, actors, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        first = actors.synthesize(project.id)
        second = actors.synthesize(project.id)

        assert second.replayed is True
        assert len(second.roles) == len(first.roles)
        assert second.assignments == first.assignments
        assert len(synthesis.list_objects(project.id, KnowledgeKind.ACTOR.value)) == len(
            first.roles
        )
        assert len(synthesis.list_assignments(project.id)) == len(first.assignments)

    def test_a_downgrade_is_reported_and_never_becomes_somebody_s_queue_item(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Invariant 1 is a rule KAE holds by itself. A rule that fired
        correctly is not an interruption (`D-121`)."""

        memory, actors, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)
        queue = synthesis.list_attention(project.id)

        assert len(queue) == len(report.conflicts)
        for statement, _ in report.downgraded:
            assert all(statement not in item.explanation for item in queue)


class TestTheCorpusOutcomeIsPinned:
    """`EPI-0`'s habit: the numbers are the evidence, so a change to them is
    visible rather than absorbed."""

    def test_the_twenty_two_split_by_kind(self, factory: sessionmaker[Session]) -> None:
        memory, actors, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)

        counts = Counter(kind for _, _, kind in report.roles)
        assert counts[RoleKind.PROJECT_ROLE] == 8
        assert counts[RoleKind.PERSONA] == 8
        assert counts[RoleKind.AI_ROLE] == 4
        assert counts[RoleKind.SYSTEM] == 1
        assert counts[RoleKind.UNCLASSIFIED] == 1

    def test_the_subject_axis_is_sparse_and_that_is_recorded_not_hidden(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-120`: the area signals classify sentences, and an actor
        description is a noun phrase. Two of twenty-two name an area outright.
        Widening it is a graded question, so the sparsity is pinned here rather
        than tuned away."""

        memory, actors, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = actors.synthesize(project.id)

        assert report.assignments == (
            ("Operator of the local deployment", "delivery_and_operations", "responsible"),
            ("Tester who validates acceptance criteria", "acceptance_criteria", "responsible"),
        )


class TestTheInvariantsReachStorage:
    """The golden corpus produces neither a conflict nor a downgrade, so the
    two branches that matter most are exercised on evidence written for them."""

    def _actors(self, memory: MemoryService, project: Project, *statements: str) -> None:
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "actor-invariants")
        memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.ACTOR.value, content=statement, source="fixture"
                )
                for statement in statements
            ],
            output_summary={"fixture": "actor-invariants"},
        )

    def test_a_second_accountable_claimant_becomes_attention_not_a_second_row(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 03 invariant 2, in its own words: *a conflict for the
        human-attention model, not a second row*."""

        memory, actors, synthesis, project = _services(factory)
        self._actors(
            memory,
            project,
            "Owner who approves how the local deployment is operated and released",
            "Decision authority who signs off on deployment and operations releases",
        )

        report = actors.synthesize(project.id)

        held = [
            assignment
            for assignment in report.assignments
            if assignment[1] == "delivery_and_operations" and assignment[2] == "accountable"
        ]
        assert len(held) == 1
        assert len(report.conflicts) == 1
        queue = synthesis.list_attention(project.id)
        assert len(queue) == 1
        assert queue[0].kind is AttentionKind.CONFLICT

    def test_the_conflict_does_not_re_interrupt_on_a_rerun(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, actors, synthesis, project = _services(factory)
        self._actors(
            memory,
            project,
            "Owner who approves how the local deployment is operated and released",
            "Decision authority who signs off on deployment and operations releases",
        )

        actors.synthesize(project.id)
        actors.synthesize(project.id)

        assert len(synthesis.list_attention(project.id)) == 1

    def test_an_ai_claiming_authority_is_downgraded_and_left_out_of_the_queue(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 03 invariant 1. The claim is kept as Responsible rather than
        dropped, because dropping it would hide that the evidence made it."""

        memory, actors, synthesis, project = _services(factory)
        self._actors(memory, project, "The release agent that approves deployment and operations")

        report = actors.synthesize(project.id)

        assert len(report.downgraded) == 1
        assert report.assignments == (
            (
                "The release agent that approves deployment and operations",
                "delivery_and_operations",
                "responsible",
            ),
        )
        assert synthesis.list_attention(project.id) == ()
