"""The five classes that say how a row is known, and the three that are not here.

`EPI-1`, doc 17, `D-134`. What the rule does to real corpora is
`tests/synthesis/test_corpus_epistemics.py`; this is the rule itself, and what
it refuses to become.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.epistemics import (
    ACQUIRABLE,
    GROUNDED,
    EpistemicClass,
    EpistemicSubject,
    classify,
    classify_all,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, KnowledgeSourceType
from kae_memory.domain.synthesis import EvidenceRole


def _subject(
    kind: KnowledgeKind = KnowledgeKind.REQUIREMENT,
    lifecycle: LifecycleState = LifecycleState.PROPOSED,
    *source_types: KnowledgeSourceType,
) -> EpistemicSubject:
    return EpistemicSubject(kind, lifecycle, frozenset(source_types))


class TestTheClassIsReadFromOriginAndAcceptance:
    def test_a_row_a_source_demonstrates_is_observed(self) -> None:
        for source in (
            KnowledgeSourceType.REPOSITORY,
            KnowledgeSourceType.USER_STATEMENT,
            KnowledgeSourceType.IMPORTED_DOCUMENT,
        ):
            subject = _subject(KnowledgeKind.REQUIREMENT, LifecycleState.PROPOSED, source)
            assert classify(subject) is EpistemicClass.OBSERVED

    def test_a_row_kae_reasoned_its_way_to_is_derived(self) -> None:
        subject = _subject(
            KnowledgeKind.REQUIREMENT, LifecycleState.PROPOSED, KnowledgeSourceType.KAE_INFERENCE
        )

        assert classify(subject) is EpistemicClass.DERIVED

    def test_grounding_beats_inference_where_a_row_carries_both(self) -> None:
        """`KnowledgeSourceType` already rules that collapsing the two would make
        every extraction a proposal. A row with a repository link has evidence,
        whatever else it also has."""

        both = _subject(
            KnowledgeKind.REQUIREMENT,
            LifecycleState.PROPOSED,
            KnowledgeSourceType.KAE_INFERENCE,
            KnowledgeSourceType.REPOSITORY,
        )

        assert classify(both) is EpistemicClass.OBSERVED

    def test_a_validated_row_is_accepted_wherever_it_came_from(self) -> None:
        """Acceptance is an act, so it outranks the origin — `D-129` again."""

        for source in KnowledgeSourceType:
            subject = _subject(KnowledgeKind.DECISION, LifecycleState.VALIDATED, source)
            assert classify(subject) is EpistemicClass.ACCEPTED

    def test_an_assumption_is_provisional_whoever_first_wrote_it(self) -> None:
        """Doc 17's *PostgreSQL is intended for production* is a KAE inference
        that is an assumption, and a repository stating one does not settle it."""

        for source in KnowledgeSourceType:
            subject = _subject(KnowledgeKind.ASSUMPTION, LifecycleState.PROPOSED, source)
            assert classify(subject) is EpistemicClass.ASSUMED

    def test_a_row_whose_provenance_says_nothing_is_undetermined_not_observed(self) -> None:
        """`EPI-5b`'s ruling, in the epistemic axis: 4,136 links in the live
        database carry no source type, and a default of observed promotes every
        one of them by omission."""

        assert classify(_subject()) is EpistemicClass.UNDETERMINED

    def test_rejection_and_supersession_are_not_read_here(self) -> None:
        """Both are the confirmation axis, and supersession is additionally
        `EvidenceRole`'s. Neither changes how the row came to be known."""

        for lifecycle in (LifecycleState.REJECTED, LifecycleState.SUPERSEDED):
            subject = _subject(KnowledgeKind.RULE, lifecycle, KnowledgeSourceType.REPOSITORY)
            assert classify(subject) is EpistemicClass.OBSERVED


class TestNothingHereReadsAStatement:
    def test_a_subject_carries_no_text_to_read(self) -> None:
        """The signature is the guard. `D-129`, `D-131` and `D-132` each had to
        assert this with a test because the function took a statement; this one
        cannot be given one."""

        assert not hasattr(_subject(), "statement")
        assert set(EpistemicSubject.__dataclass_fields__) == {"kind", "lifecycle", "source_types"}

    def test_two_rows_alike_in_origin_classify_alike(self) -> None:
        first = _subject(
            KnowledgeKind.RULE, LifecycleState.PROPOSED, KnowledgeSourceType.REPOSITORY
        )
        second = _subject(
            KnowledgeKind.CONSTRAINT, LifecycleState.PROPOSED, KnowledgeSourceType.REPOSITORY
        )

        assert classify(first) is classify(second)


class TestTheOverlapIsReconciledRatherThanDuplicated:
    def test_no_member_collides_with_an_evidence_role(self) -> None:
        """`D-134`, and the reason this file exists. Conflicting, superseded and
        noise are `EvidenceRole`'s, derived by reconciliation and recomputed on
        every rerun; a second copy here would be free to disagree with the first
        (`D-125`)."""

        roles = {role.value for role in EvidenceRole}
        classes = {one.value for one in EpistemicClass}

        assert classes & roles == set()

    def test_the_three_participation_words_are_absent_by_name(self) -> None:
        classes = {one.value for one in EpistemicClass}

        assert not classes & {"conflicting", "superseded", "historical", "noise", "archived"}

    def test_the_five_doc_seventeen_calls_origin_are_all_present(self) -> None:
        classes = {one.value for one in EpistemicClass}

        assert {"observed", "derived", "proposed", "assumed", "accepted"} <= classes


class TestProposedIsUnreachableFromAcquisition:
    @pytest.mark.parametrize("kind", list(KnowledgeKind))
    @pytest.mark.parametrize("lifecycle", list(LifecycleState))
    def test_nothing_acquired_is_ever_a_proposal(
        self, kind: KnowledgeKind, lifecycle: LifecycleState
    ) -> None:
        """Every subject the type allows, against the one class the rule may not
        produce. A proposal is what synthesis writes, and what synthesis writes
        is an object rather than an observation — so if acquisition ever starts
        recommending something, this fails instead of the class quietly
        appearing in a distribution."""

        subjects = [_subject(kind, lifecycle)]
        subjects += [_subject(kind, lifecycle, source) for source in KnowledgeSourceType]
        subjects.append(_subject(kind, lifecycle, *KnowledgeSourceType))

        assert EpistemicClass.PROPOSED not in classify_all(subjects)
        assert set(classify_all(subjects)) <= ACQUIRABLE

    def test_acquirable_is_every_class_but_that_one(self) -> None:
        assert set(EpistemicClass) - {EpistemicClass.PROPOSED} == ACQUIRABLE


class TestGroundedNamesWhatRestsOnSomethingOutsideKae:
    def test_only_observed_and_accepted_are_grounded(self) -> None:
        """Derived and assumed rest on KAE's own reasoning; undetermined rests on
        nothing recorded. `ADR-0008` is why the distinction is named rather than
        re-derived at each call site."""

        assert {EpistemicClass.OBSERVED, EpistemicClass.ACCEPTED} == GROUNDED
        assert EpistemicClass.DERIVED not in GROUNDED
        assert EpistemicClass.UNDETERMINED not in GROUNDED
