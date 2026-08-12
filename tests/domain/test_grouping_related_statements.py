"""Grouping statements that say adjacent things — `PPA-15`, and not `EM-3`.

The complaint, verbatim from the findings register: *"'I don't know how to
organise my project' becomes 'KAE generated 70 things I don't know how to
organise'."* Seventy flat statements is the customer's original problem restated
in the product's own words.

## Why this can ship while `EM-3` stays open

`EM-3` asks a question nobody has answered: **may Memory merge statements it
judges to mean the same thing, unattended?** That is a real ruling and it is not
mine.

Grouping is not merging. Every statement stays whole, stays visible, stays
separately confirmable, and the grouping is computed at read time and stored
nowhere. If the answer to `EM-3` turns out to be *no*, nothing here has to be
undone — which is the test for whether a decision was safe to take.

These assert that line as behaviour rather than as intent.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.lexical import GROUPING_SIMILARITY, group_related


def statements(*pairs: tuple[str, str]) -> list[tuple[str, str]]:
    return list(pairs)


class TestItGroupsWhatBelongsTogether:
    def test_two_statements_about_the_same_thing_group(self) -> None:
        groups = group_related(
            statements(
                ("a", "An invoice must be sent within three days of a job finishing."),
                ("b", "Invoices are sent within three working days after a job finishes."),
                ("c", "Only an authorised approver may approve a report."),
            )
        )

        assert groups == (("a", "b"),)

    def test_a_statement_belonging_to_nothing_is_absent(self) -> None:
        """Not a group of one.

        A caller rendering "groups" should not have to filter singletons out to
        find the ones that mean something — and a group of one on screen reads
        as a claim that KAE found something.
        """

        groups = group_related(
            statements(
                ("a", "Invoices are sent within three days."),
                ("b", "Only a supervisor may sign off a completed job."),
            )
        )

        assert groups == ()

    def test_it_follows_a_chain(self) -> None:
        """A groups with C when both are close to B.

        Single-link clustering, deliberately. *"Read these together"* is
        transitive in a way *"these are the same"* is not — which is the other
        reason this is not a duplicate check.
        """

        groups = group_related(
            statements(
                # Measured: a-b 0.50, b-c 0.89, a-c 0.45 — all above the
                # threshold, so this is a chain rather than three pairs. The
                # point stands either way: b is what links them.
                ("a", "Invoices must be sent within three days of a job finishing."),
                ("b", "Invoices must be sent within three days and carry a client reference."),
                ("c", "Every invoice must carry a client reference and be sent within three days."),
            )
        )

        assert len(groups) == 1
        assert set(groups[0]) == {"a", "b", "c"}

    def test_the_largest_group_comes_first(self) -> None:
        groups = group_related(
            statements(
                ("a", "Invoices are sent within three days of a job finishing."),
                ("b", "Invoices go out within three days once a job finishes."),
                ("c", "Invoices must be sent three days after a job is finished."),
                ("d", "A supervisor signs off completed work."),
                ("e", "Completed work is signed off by a supervisor."),
            )
        )

        assert len(groups[0]) == 3
        assert len(groups[1]) == 2


class TestItRefusesToGroupWhatConflicts:
    def test_a_rule_and_its_negation_do_not_group(self) -> None:
        """The case that makes naive similarity dangerous.

        A rule and its exact negation share almost every content word, so any
        overlap measure scores them as near-identical. Grouping them would put a
        contradiction on screen as agreement — the two statements a person most
        needs to see *apart*.
        """

        groups = group_related(
            statements(
                ("a", "A submitter may approve their own report."),
                ("b", "A submitter may not approve their own report."),
            )
        )

        assert groups == ()

    def test_polarity_does_not_break_an_unrelated_group(self) -> None:
        """The guard must not cost the ordinary case."""

        groups = group_related(
            statements(
                ("a", "Invoices are not sent before a job finishes."),
                ("b", "Invoices are not issued until the job has finished."),
            )
        )

        assert groups == (("a", "b"),)


class TestGroupingIsNotMerging:
    def test_every_statement_survives_in_the_answer(self) -> None:
        """Nothing is dropped, chosen between, or rewritten.

        The whole reason this ships while `EM-3` is unruled: it decides nothing
        on the project's behalf.
        """

        given = statements(
            ("a", "Invoices are sent within three days of a job finishing."),
            ("b", "Invoices go out three days after a job finishes."),
            ("c", "Only a supervisor may sign off completed work."),
        )

        groups = group_related(given)
        grouped = {identifier for group in groups for identifier in group}

        # Everything grouped was given, and nothing given was altered.
        assert grouped <= {identifier for identifier, _ in given}
        assert grouped == {"a", "b"}

    def test_it_returns_identifiers_rather_than_text(self) -> None:
        """A caller cannot accidentally render a group's "representative".

        Returning text would invite a surface to show one statement and hide the
        rest, which is merging performed by the reader.
        """

        groups = group_related(
            statements(
                ("a", "Invoices are sent within three days of a job finishing."),
                ("b", "Invoices go out three days after a job finishes."),
            )
        )

        assert all(isinstance(member, str) for group in groups for member in group)
        assert groups == (("a", "b"),)

    def test_the_same_input_gives_the_same_answer(self) -> None:
        """Read-time and deterministic. A grouping that moved between reads
        would be a stored decision pretending not to be one."""

        given = statements(
            ("a", "Invoices are sent within three days of a job finishing."),
            ("b", "Invoices go out three days after a job finishes."),
            ("c", "Only a supervisor may sign off completed work."),
            ("d", "Completed work is signed off by a supervisor."),
        )

        assert group_related(given) == group_related(given)


class TestTheThreshold:
    def test_grouping_is_looser_than_duplication(self) -> None:
        """A duplicate is a claim about sameness and deserves a high bar.

        A group is a claim about adjacency, and the cost of being slightly wrong
        is that somebody reads two related statements at once — which is what
        they were going to do anyway.
        """

        from kae_memory.domain.lexical import NEAR_DUPLICATE_SIMILARITY

        assert GROUPING_SIMILARITY < NEAR_DUPLICATE_SIMILARITY

    @pytest.mark.parametrize("threshold", [0.9, 0.99])
    def test_a_stricter_threshold_groups_less(self, threshold: float) -> None:
        given = statements(
            ("a", "An invoice must be sent within three days of a job finishing."),
            ("b", "Invoices are sent within three working days after a job finishes."),
        )

        assert group_related(given) == (("a", "b"),)
        assert group_related(given, threshold=threshold) == ()

    def test_nothing_at_all_groups_into_nothing(self) -> None:
        assert group_related([]) == ()


class TestAgainstStatementsFromARealProject:
    """Calibration, pinned to text this product actually produced.

    `ES-5` shipped and grouped **nothing** on the first live project: 32
    statements, 496 pairs, maximum similarity 0.33 against a threshold of 0.42.
    A feature that never fires on real data is indistinguishable from one that
    was never wired, and the only way to tell them apart is to look.

    The threshold had been calibrated on statements written to illustrate the
    problem, which score 0.78–0.83 for genuine paraphrase. Real extracted ones
    are longer, hedged, and full of qualifying clauses, so the same meaning
    shares a smaller fraction of its words.

    These are verbatim from that project. They exist so the next change to the
    threshold has to face them.
    """

    # Two wordings of one question, from the deployed `Cris Test 2`.
    SAME_QUESTION = (
        "What is 'that repository' — which repository is being referred to, and "
        "what does it contain?",
        "What repository is being referred to, and where is it located or how would KAE access it?",
    )

    # Adjacent nouns, unrelated obligations. The pair that must stay apart.
    DIFFERENT_SUBJECTS = (
        "What is the project or system being worked on?",
        "The system must be able to read reference works.",
    )

    def test_neither_pair_groups_today(self) -> None:
        """Including the one that should.

        This is the honest state and it is asserted rather than hidden: on real
        statements the measure finds nothing, so the surface renders nothing.
        A true answer rather than a useful one.
        """

        assert group_related([("a", self.SAME_QUESTION[0]), ("b", self.SAME_QUESTION[1])]) == ()
        assert (
            group_related([("a", self.DIFFERENT_SUBJECTS[0]), ("b", self.DIFFERENT_SUBJECTS[1])])
            == ()
        )

    def test_the_measure_cannot_separate_them(self) -> None:
        """Fourteen thousandths between a true pair and a false one.

        **The reason the threshold was not simply lowered.** Any value chosen
        between 0.286 and 0.300 is fitted to two examples and wrong on the
        third — that is not a threshold to tune, it is a measure that cannot
        tell them apart.

        Pinned so the next person to reach for the constant meets the evidence
        first. The fix is `GROUP-MEASURE`.
        """

        from kae_memory.domain.lexical import similarity

        true_pair = similarity(*self.SAME_QUESTION)
        false_pair = similarity(*self.DIFFERENT_SUBJECTS)

        assert true_pair > false_pair, "the true pair does at least score higher"
        assert true_pair - false_pair < 0.02, (
            f"a true pair at {true_pair:.3f} and a false one at {false_pair:.3f} — "
            "no threshold separates these; see GROUP-MEASURE"
        )
