"""`SYN-5d` — a project belief, an interpretation of a transcript, and the gap between.

Doc 05's subject is what an assumption *costs if it is wrong*. These assert that
interpretation scaffolding is separated rather than filtered, that materiality is
read from a statable consequence and never from confident wording, that nothing
becomes an interruption, and that doc 05's seven lifecycle states are not
reintroduced as a seventh vocabulary.
"""

from __future__ import annotations

import itertools

import pytest
from tests.synthesis.corpus import COLLABORATION_MVP, OBSERVATIONS, PARSER_SCAFFOLDING

from kae_memory.domain.epistemics import EpistemicClass, EpistemicSubject, classify
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, KnowledgeSourceType
from kae_memory.domain.synthesis import Authority, EvidenceRole, SynthesizedLifecycle
from kae_memory.domain.synthesizers.assumptions import (
    AssumptionCandidate,
    ConsequenceDomain,
    consequence_of,
    is_about_the_project,
    plan_assumption_model,
)
from kae_memory.domain.synthesizers.constraints import subject_terms

SINGLE_USER = "The project has a single user for MVP."
KAE_NAMES_THE_SYSTEM = "KAE is the name of the system under discussion."
ENGLISH_IS_THE_LANGUAGE = "English is the working language of the project."
LOCAL_DISK = "Local disk is an acceptable source of repositories."


def _candidate(statement: str, *, confirmed: bool = False) -> AssumptionCandidate:
    return AssumptionCandidate(
        members=(statement,),
        canonical_key=statement,
        statement=statement,
        confirmed_by_person=confirmed,
    )


def _corpus_assumptions() -> tuple[str, ...]:
    return tuple(
        observation.content
        for observation in OBSERVATIONS
        if observation.kind is KnowledgeKind.ASSUMPTION
    )


class TestScaffoldingIsSeparatedNotFiltered:
    """Doc 05: conversation-parsing assumptions *"should not become durable
    project review work."* Separated, named, and given no object."""

    @pytest.mark.parametrize(
        "statement",
        [
            KAE_NAMES_THE_SYSTEM,
            "Prior conversation context still applies in this session.",
            "The speaker is referring to this product rather than a different KAE.",
        ],
    )
    def test_doc_05s_three_named_examples_are_not_about_the_project(self, statement: str) -> None:
        assert is_about_the_project(statement) is False

    def test_it_is_reported_by_name_rather_than_dropped(self) -> None:
        """A silent drop is indistinguishable from an extractor that never
        produced the row, which is the state doc 05 is complaining about."""

        plan = plan_assumption_model([_candidate(KAE_NAMES_THE_SYSTEM), _candidate(SINGLE_USER)])

        assert [item.statement for item in plan.scaffolding] == [KAE_NAMES_THE_SYSTEM]
        assert plan.scaffolding[0].reason
        assert [planned.candidate.statement for planned in plan.assumptions] == [SINGLE_USER]

    def test_its_role_is_noise_which_already_exists(self) -> None:
        """`D-134` put noise on the participates-in-reasoning axis. Naming it
        here rather than inventing a status keeps the two axes from disagreeing."""

        plan = plan_assumption_model([_candidate(KAE_NAMES_THE_SYSTEM)])

        assert plan.scaffolding[0].role is EvidenceRole.NOISE

    def test_epi_1_still_calls_it_assumed_and_the_two_do_not_conflict(self) -> None:
        """The axes answer different questions (`D-135`). `EPI-1` says how KAE
        came to know the row; this says whether it is about the project at all."""

        assert (
            classify(
                EpistemicSubject(
                    kind=KnowledgeKind.ASSUMPTION,
                    lifecycle=LifecycleState.PROPOSED,
                    source_types=frozenset({KnowledgeSourceType.USER_STATEMENT}),
                )
            )
            is EpistemicClass.ASSUMED
        )
        assert is_about_the_project(KAE_NAMES_THE_SYSTEM) is False


class TestMaterialityIsAStatableConsequence:
    """Doc 05: an assumption is one *"whose falsity could change project scope,
    architecture, requirements, cost, workflow, or outcome."*"""

    @pytest.mark.parametrize(
        ("statement", "expected"),
        [
            (SINGLE_USER, ConsequenceDomain.SCOPE),
            (LOCAL_DISK, ConsequenceDomain.ARCHITECTURE),
            (
                "The same person both defines the product and confirms decisions.",
                ConsequenceDomain.WORKFLOW,
            ),
            ("The hosted model is billed per token above the free tier.", ConsequenceDomain.COST),
            (ENGLISH_IS_THE_LANGUAGE, ConsequenceDomain.UNDETERMINED),
        ],
    )
    def test_the_consequence_is_read_from_the_statement(
        self, statement: str, expected: ConsequenceDomain
    ) -> None:
        assert consequence_of(statement) is expected

    def test_outcome_is_read_last_so_it_does_not_swallow_the_others(self) -> None:
        """Every one of the five also changes the outcome, so an early read
        would collapse doc 05's list to one member."""

        assert (
            consequence_of("A successful outcome depends on the deployment architecture.")
            is ConsequenceDomain.ARCHITECTURE
        )
        assert consequence_of("Adoption depends on trust.") is ConsequenceDomain.OUTCOME

    def test_an_unstatable_consequence_stays_working_knowledge(self) -> None:
        """Doc 05's fifth hygiene question, answered in the direction that asks
        a person for less."""

        plan = plan_assumption_model([_candidate(ENGLISH_IS_THE_LANGUAGE)])

        planned = plan.assumptions[0]
        assert planned.consequence is ConsequenceDomain.UNDETERMINED
        assert planned.needs_validation is False
        assert plan.needing_validation == ()

    def test_confident_wording_does_not_settle_anything(self) -> None:
        """`D-123`/`D-129`/`D-132` a fourth time: only the act promotes."""

        worded = plan_assumption_model([_candidate("It is certain that the project has one user.")])
        acted = plan_assumption_model([_candidate(SINGLE_USER, confirmed=True)])

        assert worded.assumptions[0].lifecycle is SynthesizedLifecycle.WORKING
        assert worded.assumptions[0].authority is Authority.WORKING_MODEL
        assert acted.assumptions[0].lifecycle is SynthesizedLifecycle.AUTHORITATIVE
        assert acted.assumptions[0].authority is Authority.HUMAN
        assert acted.assumptions[0].needs_validation is False


class TestAlreadyEstablishedKnowledgeIsRetired:
    """Doc 05's third hygiene question, and its *resolved into established
    knowledge* state."""

    def test_an_assumption_the_project_already_answers_is_resolved(self) -> None:
        plan = plan_assumption_model(
            [_candidate(SINGLE_USER)],
            established=["The project has a single confirmed user for the MVP release."],
        )

        assert plan.assumptions == ()
        assert len(plan.resolved) == 1
        assert plan.resolved[0].role is EvidenceRole.RESOLVED
        assert "single confirmed user" in plan.resolved[0].reason

    def test_a_partial_overlap_retires_nothing(self) -> None:
        """Containment and not overlap: a looser rule quietly retires an
        assumption the project still holds (`D-124` measured what overlap does)."""

        plan = plan_assumption_model(
            [_candidate(SINGLE_USER)],
            established=["The project is an MVP."],
        )

        assert plan.resolved == ()
        assert len(plan.assumptions) == 1

    def test_passing_no_established_knowledge_retires_nothing(self) -> None:
        plan = plan_assumption_model([_candidate(SINGLE_USER)])

        assert plan.resolved == ()


class TestNothingBecomesAnInterruption:
    """Doc 05: *"Do not preserve stale assumptions as permanent review items."*"""

    def test_needing_validation_is_a_projection_and_not_a_second_source(self) -> None:
        plan = plan_assumption_model([_candidate(text) for text in _corpus_assumptions()])

        assert [statement for statement, _ in plan.needing_validation] == [
            planned.candidate.statement for planned in plan.assumptions if planned.needs_validation
        ]
        for _, reason in plan.needing_validation:
            assert reason

    def test_the_plan_offers_no_attention_field_at_all(self) -> None:
        """One interrupt per unvalidated assumption is the review queue
        `ADR-0007` removes, under a new name (`D-125`)."""

        plan = plan_assumption_model([_candidate(SINGLE_USER)])

        assert not hasattr(plan, "attention")


class TestDoc05sLifecycleIsNotASeventhVocabulary:
    def test_the_module_defines_no_lifecycle_enum(self) -> None:
        """Five of doc 05's seven states already exist. A copy of them would be
        free to disagree after a rerun (`D-125`, `D-123`, `D-134`)."""

        from kae_memory.domain.synthesizers import assumptions

        assert not hasattr(assumptions, "AssumptionLifecycle")
        assert not hasattr(assumptions, "AssumptionStatus")

    def test_each_state_it_does_use_comes_from_an_existing_vocabulary(self) -> None:
        assert SynthesizedLifecycle.WORKING and SynthesizedLifecycle.AUTHORITATIVE
        assert SynthesizedLifecycle.SUPERSEDED and SynthesizedLifecycle.RESOLVED
        assert EvidenceRole.HISTORICAL and EvidenceRole.NOISE and EvidenceRole.RESOLVED


class TestTheGoldenCorpusPinsTheMeasurement:
    """The row's real content is what the corpus says, not what the rules say."""

    def test_thirteen_rows_become_ten_project_assumptions_and_three_are_scaffolding(
        self,
    ) -> None:
        statements = _corpus_assumptions()
        plan = plan_assumption_model([_candidate(text) for text in statements])

        assert len(statements) == 13
        assert len(plan.assumptions) == 10
        assert len(plan.scaffolding) == 3

    def test_the_three_separated_rows_are_exactly_the_tagged_ones(self) -> None:
        """Graded against the fixture's own labels rather than against a count,
        which is what stops a lexicon being widened until the number looks right
        (`D-16`, and `EPI-3b`'s answer to it)."""

        tagged = {
            observation.content
            for observation in OBSERVATIONS
            if PARSER_SCAFFOLDING in observation.cases
        }
        plan = plan_assumption_model([_candidate(text) for text in _corpus_assumptions()])

        assert {item.statement for item in plan.scaffolding} == tagged

    def test_four_of_the_ten_carry_no_statable_consequence(self) -> None:
        """Doc 05's complaint measured. Not a gap to fill by guessing — a rule
        that named a domain for every sentence would make every assumption
        material by the act of synthesising it."""

        plan = plan_assumption_model([_candidate(text) for text in _corpus_assumptions()])

        undetermined = [
            planned
            for planned in plan.assumptions
            if planned.consequence is ConsequenceDomain.UNDETERMINED
        ]
        assert len(undetermined) == 4
        assert len(plan.needing_validation) == 6

    def test_doc_05s_own_consolidation_example_is_not_reachable_lexically(self) -> None:
        """The four collaboration rows share at most one content word between
        any pair, so a word-overlap grouper would return four singletons and
        read like a working consolidation. That is `SYN-3a`'s neighbourhood, and
        it is why this module has no grouper (`D-135`)."""

        collaboration = [
            observation.content
            for observation in OBSERVATIONS
            if COLLABORATION_MVP in observation.cases
            and observation.kind is KnowledgeKind.ASSUMPTION
        ]
        assert len(collaboration) == 4

        shared = [
            subject_terms(left) & subject_terms(right)
            for left, right in itertools.combinations(collaboration, 2)
        ]
        assert [len(terms) for terms in shared] == [0, 1, 0, 0, 0, 0]
