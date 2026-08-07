"""What happened to a question, distinct from whether something was said (N36).

The gap this closes was found in a manual test. KAE asked what the inbox should
do with a captured thought; the answer was "I don't know yet — recommend
something reasonable for a prototype, but don't make it a permanent project
decision." The system had two options and both were wrong. Record it as an
answer, and a choice nobody made becomes a project decision. Record nothing, and
the recommendation is lost along with the fact that anyone was ever asked.

The distinction these tests defend is that a response and a settlement are
different events. Only some dispositions settle.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.dispositions import (
    BLOCKING_PRIORITIES,
    NEEDS_ASSUMPTION,
    SETTLES,
    Disposition,
    DispositionError,
    QuestionPriority,
    blocks,
    ensure_disposition,
    settles,
)


class TestOnlySomeDispositionsSettle:
    def test_an_answer_settles_the_question(self) -> None:
        assert settles(Disposition.ANSWERED) is True

    @pytest.mark.parametrize(
        "disposition",
        [
            Disposition.DEFERRED,
            Disposition.UNKNOWN_BY_USER,
            Disposition.DELEGATED,
            Disposition.ASSUMED_FOR_GENERATION,
        ],
    )
    def test_uncertainty_does_not(self, disposition: Disposition) -> None:
        """The whole target. "I don't know yet" is a real response to a real
        question and it decides nothing; a lifecycle that closes on it is
        recording a decision nobody made."""

        assert settles(disposition) is False

    def test_a_question_that_stopped_mattering_settles(self) -> None:
        """Not answered, but not still owed either. Leaving it open would keep
        asking for something the project no longer needs."""

        assert settles(Disposition.NO_LONGER_RELEVANT) is True
        assert settles(Disposition.SUPERSEDED) is True

    def test_the_settling_set_is_stated_rather_than_derived(self) -> None:
        """Adding a disposition must be a decision about whether it closes a
        question, not a default inherited from where it was declared."""

        assert {
            Disposition.ANSWERED,
            Disposition.NO_LONGER_RELEVANT,
            Disposition.SUPERSEDED,
        } == SETTLES


class TestARecordedDispositionMustBeUsable:
    def test_an_answer_needs_the_answer_text(self) -> None:
        with pytest.raises(DispositionError):
            ensure_disposition(Disposition.ANSWERED, answer="   ")

    @pytest.mark.parametrize("disposition", sorted(NEEDS_ASSUMPTION))
    def test_standing_in_for_an_answer_needs_the_assumption(self, disposition: Disposition) -> None:
        """A recommendation nobody recorded is one nobody can revisit, which is
        precisely what the person asked not to happen."""

        with pytest.raises(DispositionError):
            ensure_disposition(disposition, answer="you choose", assumption_id=None)

    def test_with_the_assumption_it_is_accepted(self) -> None:
        ensure_disposition(Disposition.DELEGATED, answer="you choose for now", assumption_id="a-1")

    def test_open_is_refused_as_an_outcome(self) -> None:
        """`open` is where a question starts, not somewhere it is put. Allowing
        it would let a caller "record" that nothing happened, which is
        indistinguishable from not calling at all and harder to read."""

        with pytest.raises(DispositionError):
            ensure_disposition(Disposition.OPEN, answer="anything")

    def test_deferral_needs_no_assumption(self) -> None:
        """Deferring is declining to decide *and* declining to guess."""

        ensure_disposition(Disposition.DEFERRED, answer="not now")


class TestPriorityIsAboutBlocking:
    def test_helpful_and_important_never_block(self) -> None:
        """Readiness is advisory. A question that would be nice to answer must
        not stop generation — that is the gate this system deliberately does
        not have."""

        assert blocks(QuestionPriority.HELPFUL) is False
        assert blocks(QuestionPriority.IMPORTANT) is False
        assert blocks(QuestionPriority.DEFERRED) is False

    @pytest.mark.parametrize("priority", sorted(BLOCKING_PRIORITIES))
    def test_only_choice_authorization_and_integrity_block(
        self, priority: QuestionPriority
    ) -> None:
        assert blocks(priority) is True

    def test_the_blocking_set_is_exactly_three(self) -> None:
        """Stated out loud so that broadening it is a decision. Every addition
        here is a new way for the system to refuse to generate."""

        assert {
            QuestionPriority.CAPABILITY_BLOCKING,
            QuestionPriority.AUTHORIZATION_BLOCKING,
            QuestionPriority.INTEGRITY_BLOCKING,
        } == BLOCKING_PRIORITIES
