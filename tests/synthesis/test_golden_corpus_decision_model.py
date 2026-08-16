"""Golden corpus: four decision rows stop being *proposed* and *to decide* at once.

`SYN-5f`, doc 08, `D-123`/`D-125`. The domain layer is tested in
`tests/domain/test_decision_synthesis.py`; this is what the run persists.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, SynthesisService, WriteKnowledgeRequest
from kae_memory.application.decision_synthesis_service import DecisionSynthesisService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.synthesis import AttentionKind, Authority, SynthesizedLifecycle
from kae_memory.domain.synthesizers.decisions import DecisionClass, EffectiveScope
from tests.synthesis.corpus import AREA_SUFFICIENT_TEXT, count_by_kind
from tests.synthesis.load import load_golden_corpus


def _services(
    factory: sessionmaker[Session],
) -> tuple[MemoryService, DecisionSynthesisService, SynthesisService, Project]:
    memory = MemoryService(factory)
    project = memory.create_project("KAE synthesis corpus", key="golden-decisions")
    return memory, DecisionSynthesisService(factory), SynthesisService(factory), project


class TestOneObjectCarriesOneState:
    def test_every_decision_observation_becomes_exactly_one_object(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, decisions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = decisions.synthesize(project.id)

        expected = count_by_kind()[KnowledgeKind.DECISION.value]
        assert report.considered == expected
        assert len(report.decisions) == expected
        stored = synthesis.list_objects(project.id, KnowledgeKind.DECISION.value)
        assert len(stored) == expected

    def test_the_stored_state_is_the_object_s_own_lifecycle(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-125`: there is no decision table, so the object's lifecycle and
        authority *are* the decision's state and cannot disagree with it."""

        memory, decisions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = decisions.synthesize(project.id)

        settled = {decision.statement for decision in report.decisions if decision.settled}
        for obj in synthesis.list_objects(project.id, KnowledgeKind.DECISION.value):
            if obj.statement in settled:
                assert obj.lifecycle is SynthesizedLifecycle.AUTHORITATIVE
                assert obj.authority is Authority.HUMAN
            else:
                assert obj.lifecycle is SynthesizedLifecycle.WORKING
                assert obj.authority is Authority.WORKING_MODEL

    def test_only_the_confirmed_row_is_authoritative(self, factory: sessionmaker[Session]) -> None:
        """Wording never promotes (`D-123`). Three of the four corpus decisions
        are worded as choices already made, and one carries a confirmation."""

        memory, decisions, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = decisions.synthesize(project.id)

        assert report.settled == (AREA_SUFFICIENT_TEXT,)


class TestWhatTheRunRefuses:
    def test_an_unaccepted_decision_is_reported_and_never_queued(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`D-125`: one attention item per unaccepted decision would be the
        review queue `ADR-0007` exists to remove, under a new name."""

        memory, decisions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = decisions.synthesize(project.id)

        assert len(report.awaiting) == 2
        assert synthesis.list_attention(project.id) == ()

    def test_a_session_decision_is_refused_permanence_and_asks_nothing(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Doc 08's own invariant: a temporary workflow decision must not
        silently become permanent governance — and it is not somebody's task
        either, so it appears in neither the awaiting list nor the queue."""

        memory, decisions, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = decisions.synthesize(project.id)

        assert len(report.session_scoped) == 1
        statement, _ = report.session_scoped[0]
        assert statement.startswith("In this session")
        assert all(awaited != statement for awaited, _ in report.awaiting)
        session_scoped = [
            decision for decision in report.decisions if decision.scope is EffectiveScope.SESSION
        ]
        assert [decision.settled for decision in session_scoped] == [False]


class TestWhatTheRunPersists:
    def test_evidence_is_bound_and_no_extracted_row_is_touched(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, decisions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)
        before = memory.retrieve_knowledge(project.id, lifecycle=None)

        report = decisions.synthesize(project.id)

        after = memory.retrieve_knowledge(project.id, lifecycle=None)
        assert len(after) == len(before)
        for decision in report.decisions:
            assert synthesis.list_bindings(project.id, decision.object_id)

    def test_rerunning_writes_nothing_new(self, factory: sessionmaker[Session]) -> None:
        """A settled decision is already authoritative on the second pass, so
        the promotion has to be idempotent rather than merely legal."""

        memory, decisions, synthesis, project = _services(factory)
        load_golden_corpus(memory, project.id)

        first = decisions.synthesize(project.id)
        second = decisions.synthesize(project.id)

        assert second.replayed is True
        assert second.settled == first.settled
        assert second.awaiting == first.awaiting
        assert [decision.object_id for decision in second.decisions] == [
            decision.object_id for decision in first.decisions
        ]
        stored = synthesis.list_objects(project.id, KnowledgeKind.DECISION.value)
        assert len(stored) == len(first.decisions)
        assert [obj.revision for obj in stored if obj.authority is Authority.HUMAN] == [2]


class TestTheCorpusOutcomeIsPinned:
    """`EPI-0`'s habit: the numbers are the evidence, so a change to them is
    visible rather than absorbed."""

    def test_the_four_split_by_class_and_scope(self, factory: sessionmaker[Session]) -> None:
        memory, decisions, _, project = _services(factory)
        load_golden_corpus(memory, project.id)

        report = decisions.synthesize(project.id)

        assert report.by_class == {
            DecisionClass.PLANNING: 1,
            DecisionClass.WORKFLOW: 2,
            DecisionClass.ARCHITECTURE: 1,
        }
        assert (
            sum(1 for decision in report.decisions if decision.scope is EffectiveScope.SESSION) == 1
        )


class TestTheConflictReachesTheQueue:
    """The corpus writes no area links, so the sufficiency conflict cannot fire
    there. It is exercised on evidence written for it — the same shape as
    `SYN-5a`'s invariants, which the corpus also does not trigger."""

    def _sufficiency_against_an_open_candidate(
        self, memory: MemoryService, readiness: ReadinessService, project: Project
    ) -> None:
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "decision-conflict")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.DECISION.value,
                    content=AREA_SUFFICIENT_TEXT,
                    source="fixture",
                ),
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.GOAL.value,
                    content="The product must make the problem visible to a newcomer.",
                    source="fixture",
                ),
            ],
            output_summary={"fixture": "decision-conflict"},
        )
        decision, candidate = written
        memory.confirm_knowledge(decision.id)
        readiness.assign_area(project.id, candidate.id, "problem_and_value")

    def test_an_area_declared_sufficient_over_open_candidates_is_attention(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, decisions, synthesis, project = _services(factory)
        self._sufficiency_against_an_open_candidate(memory, ReadinessService(factory), project)

        report = decisions.synthesize(project.id)

        assert len(report.conflicts) == 1
        statement, reason = report.conflicts[0]
        assert statement == AREA_SUFFICIENT_TEXT
        assert "problem_and_value" in reason
        queue = synthesis.list_attention(project.id)
        assert len(queue) == 1
        assert queue[0].kind is AttentionKind.CONFLICT

    def test_the_conflict_does_not_re_interrupt_on_a_rerun(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory, decisions, synthesis, project = _services(factory)
        self._sufficiency_against_an_open_candidate(memory, ReadinessService(factory), project)

        decisions.synthesize(project.id)
        decisions.synthesize(project.id)

        assert len(synthesis.list_attention(project.id)) == 1

    def test_an_unaccepted_sufficiency_claim_conflicts_with_nothing(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The conflict is between the project's state and a decision somebody
        made. An unaccepted claim is KAE's reading, and reading something is
        not contradicting it."""

        memory, decisions, synthesis, project = _services(factory)
        run = memory.start_run(project.id, AgentRole.REQUIREMENTS, "decision-unaccepted")
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.DECISION.value,
                    content=AREA_SUFFICIENT_TEXT,
                    source="fixture",
                ),
                WriteKnowledgeRequest(
                    kind=KnowledgeKind.GOAL.value,
                    content="The product must make the problem visible to a newcomer.",
                    source="fixture",
                ),
            ],
            output_summary={"fixture": "decision-unaccepted"},
        )
        ReadinessService(factory).assign_area(project.id, written[1].id, "problem_and_value")

        report = decisions.synthesize(project.id)

        assert report.conflicts == ()
        assert len(report.awaiting) == 1
        assert synthesis.list_attention(project.id) == ()
