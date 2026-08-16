"""A requirement-shaped sentence is not a requirement (`SYN-5b`, doc 06, `D-129`).

Pure domain. The corpus's own twelve requirement statements are used verbatim,
because the failure doc 06 describes is about *these* sentences and a fixture
written to pass would prove nothing.
"""

from __future__ import annotations

from tests.synthesis.corpus import OBSERVATIONS, ExtractedObservation

from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesizers.requirements import (
    AcceptanceCriterion,
    RequirementCandidate,
    StatementKind,
    Verifiability,
    kind_of,
    plan_requirement_model,
    verifiability_of,
)


def _corpus_requirements() -> tuple[ExtractedObservation, ...]:
    return tuple(one for one in OBSERVATIONS if one.kind is KnowledgeKind.REQUIREMENT)


PRESERVED = "Original source notes must be preserved and retrievable."
WEB_AND_MOBILE = "The product shall support web now and mobile later."
PASTE_NOTES = "A user can paste notes as a project source."
CONNECT_LOCAL = "A user can connect a local directory as a source."
PROPAGATE = "Accepted decisions propagate to related unknowns and assumptions."


def _candidate(statement: str, *, accepted: bool = False) -> RequirementCandidate:
    key = statement[:24]
    return RequirementCandidate(
        members=(key,), canonical_key=key, statement=statement, accepted=accepted
    )


class TestWordingConfersNoAuthority:
    def test_must_and_shall_do_not_make_a_requirement_ready(self) -> None:
        """`D-129`: *must* is the grammar of the sentence somebody wrote down."""

        plan = plan_requirement_model([_candidate(PRESERVED), _candidate(WEB_AND_MOBILE)])

        assert plan.ready == ()

    def test_acceptance_alone_does_not_make_it_ready_either(self) -> None:
        plan = plan_requirement_model([_candidate(PRESERVED, accepted=True)])

        assert plan.ready == ()
        assert plan.requirements[0].verifiability is Verifiability.OBSERVABLE

    def test_ready_needs_all_three(self) -> None:
        candidate = _candidate(PRESERVED, accepted=True)
        plan = plan_requirement_model(
            [candidate],
            [
                AcceptanceCriterion(
                    requirement_key=candidate.canonical_key,
                    statement="A stored note is retrievable by its source link after an update.",
                )
            ],
        )

        assert len(plan.ready) == 1
        assert plan.ready[0].candidate is candidate


class TestKaeWritesNoAcceptanceCriteria:
    def test_a_run_with_no_criteria_makes_nothing_ready(self) -> None:
        """The whole corpus, accepted, and still nothing is implementation-ready.

        `ADR-0008`: readiness may not derive from the quantity of records KAE
        made. Synthesising a requirement is a record KAE made.
        """

        plan = plan_requirement_model(
            [_candidate(text, accepted=True) for text in (PRESERVED, PASTE_NOTES, PROPAGATE)]
        )

        assert plan.ready == ()
        assert len(plan.without_criteria) == 3

    def test_criteria_bind_to_their_own_requirement(self) -> None:
        first, second = _candidate(PASTE_NOTES), _candidate(CONNECT_LOCAL)
        plan = plan_requirement_model(
            [first, second],
            [
                AcceptanceCriterion(
                    requirement_key=first.canonical_key,
                    statement="Pasted text appears as a source on the project.",
                )
            ],
        )

        by_key = {one.candidate.canonical_key: one for one in plan.requirements}
        assert by_key[first.canonical_key].criteria != ()
        assert by_key[second.canonical_key].criteria == ()


class TestTheMixedListIsSeparatedAndNotFiltered:
    def test_a_principle_is_reported_rather_than_dropped(self) -> None:
        plan = plan_requirement_model(
            [_candidate("We believe the project record should always outlive the conversation.")]
        )

        assert plan.requirements == ()
        assert len(plan.reclassified) == 1
        assert plan.reclassified[0].kind is StatementKind.PRINCIPLE
        assert "outlive" in plan.reclassified[0].statement

    def test_positioning_and_governance_are_named_as_themselves(self) -> None:
        plan = plan_requirement_model(
            [
                _candidate("Unlike competitor tools, KAE keeps the evidence."),
                _candidate("Every generated package needs sign-off from the project owner."),
            ]
        )

        assert [one.kind for one in plan.reclassified] == [
            StatementKind.POSITIONING,
            StatementKind.GOVERNANCE,
        ]

    def test_an_unrecognised_sentence_stays_a_requirement(self) -> None:
        """The input is already requirement-like, so the job is naming what is not."""

        assert kind_of(PASTE_NOTES) is StatementKind.REQUIREMENT
        assert kind_of("Uploaded documents become evidence after decode.") is (
            StatementKind.REQUIREMENT
        )


class TestACompoundIsSplitAndNotRejected:
    def test_web_now_and_mobile_later_proposes_two_halves(self) -> None:
        """Doc 06's own example, and it must not become Confirm/Reject."""

        plan = plan_requirement_model([_candidate(WEB_AND_MOBILE)])

        assert len(plan.splits) == 1
        assert (plan.splits[0].first, plan.splits[0].second) == ("web", "mobile")

    def test_the_compound_survives_its_own_split(self) -> None:
        """A proposal applies nothing — `D-126`'s shape."""

        plan = plan_requirement_model([_candidate(WEB_AND_MOBILE)])

        assert len(plan.requirements) == 1
        assert plan.requirements[0].verifiability is Verifiability.COMPOUND

    def test_one_ask_about_one_thing_is_not_compound(self) -> None:
        """*preserved and retrievable* is a single ask, not two scopes."""

        assert verifiability_of(PRESERVED) is Verifiability.OBSERVABLE
        assert plan_requirement_model([_candidate(PRESERVED)]).splits == ()


class TestNothingIsInterrupted:
    def test_the_plan_offers_no_queue(self) -> None:
        """`D-125`: one interrupt per unready requirement is the 174-row queue.

        Asserted by field list rather than by counting an empty one, so adding
        an attention channel later fails here first.
        """

        plan = plan_requirement_model([_candidate(text) for text in (PRESERVED, WEB_AND_MOBILE)])

        assert set(plan.__slots__) == {"requirements", "reclassified", "splits"}


class TestTheCapabilityAxisReportsItsOwnFloor:
    def test_areas_are_read_from_the_statement_and_may_be_empty(self) -> None:
        """Doc 06 wants navigation by capability. This is how far wording gets.

        Pinned rather than tuned: a lexicon widened until the corpus groups
        neatly is `D-16`. An empty tuple is an honest *this sentence names no
        area*, and it is the majority.
        """

        plan = plan_requirement_model(
            [_candidate(text) for text in (PRESERVED, PASTE_NOTES, CONNECT_LOCAL, PROPAGATE)]
        )

        placed = [one for one in plan.requirements if one.capability_areas]
        assert len(placed) < len(plan.requirements)


class TestTheGoldenCorpusPinned:
    """The measurement, so a later change to the lexicon has to argue with it."""

    def test_twelve_requirement_rows_stay_twelve_requirements(self) -> None:
        """**Nothing is reclassified**, and that is the corpus rather than the rule.

        Its twelve requirement rows are all genuinely requirements, so doc 06's
        mixed list is exercised on evidence written for it above — the same
        shape `SYN-5e` and `SYN-5f` needed for the cases the corpus does not
        trigger.
        """

        plan = plan_requirement_model([_candidate(one.content) for one in _corpus_requirements()])

        assert len(plan.requirements) == 12
        assert plan.reclassified == ()

    def test_one_compound_and_it_is_doc_06s_own_example(self) -> None:
        plan = plan_requirement_model([_candidate(one.content) for one in _corpus_requirements()])

        assert [(one.first, one.second) for one in plan.splits] == [("web", "mobile")]
        assert sum(1 for one in plan.requirements if one.verifiability is Verifiability.VAGUE) == 0

    def test_nothing_is_implementation_ready(self) -> None:
        """Twelve requirements, twelve without criteria, zero ready.

        Doc 06's *candidate review dump* measured rather than disguised.
        """

        plan = plan_requirement_model([_candidate(one.content) for one in _corpus_requirements()])

        assert plan.ready == ()
        assert len(plan.without_criteria) == 12

    def test_the_capability_axis_reaches_four_of_twelve(self) -> None:
        """Pinned as a floor, not tuned to a fraction (`D-16`).

        `areas_named_by` scores subject matter, and a requirement often names
        its behaviour without naming its area — *"A user can paste notes as a
        project source"* is about sources and says nothing an area lexicon
        recognises.
        """

        plan = plan_requirement_model([_candidate(one.content) for one in _corpus_requirements()])

        assert sum(1 for one in plan.requirements if one.capability_areas) == 4
