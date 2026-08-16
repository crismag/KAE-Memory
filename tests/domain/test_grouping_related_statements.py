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

from itertools import combinations

import pytest

from kae_memory.domain.lexical import GROUPING_SIMILARITY, group_related, similarity


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

    def test_three_statements_all_close_to_each_other_group(self) -> None:
        """Measured: a-b 0.50, b-c 0.89, a-c 0.455 — every pair above the
        threshold, so this is a clique and not a chain.

        It was named `test_it_follows_a_chain` and its comment called it one,
        which is why `D-146` measured before editing: moving to complete linkage
        was expected to break this and does not, because there was never a link
        here doing work no other pair could do.
        """

        groups = group_related(
            statements(
                ("a", "Invoices must be sent within three days of a job finishing."),
                ("b", "Invoices must be sent within three days and carry a client reference."),
                ("c", "Every invoice must carry a client reference and be sent within three days."),
            )
        )

        assert len(groups) == 1
        assert set(groups[0]) == {"a", "b", "c"}

    def test_a_statement_joins_only_what_it_is_itself_close_to(self) -> None:
        """`D-76`'s defect, in three verbatim statements from the golden corpus.

        The goal is 0.429 from the first question and **0.333 from the second**,
        below the threshold. Single linkage grouped all three anyway, because the
        goal was close enough to *one* of them; complete linkage scores the merge
        by the furthest pair and refuses it. The two questions, which are 0.60
        apart, stay together — the refusal costs nothing true.
        """

        groups = group_related(
            statements(
                ("goal", "Transform rough project material into a development-ready plan."),
                ("q1", "When is a plan development-ready?"),
                ("q2", "How do we know the plan is development-ready?"),
            )
        )

        assert groups == (("q1", "q2"),)

    def test_every_pair_inside_a_group_meets_the_threshold(self) -> None:
        """The invariant, stated over the output rather than over the algorithm.

        A group is a claim about all of its members. Under single linkage it was
        a claim about a path through them, and a person reading one could not
        tell which.
        """

        given = statements(
            ("a", "Invoices must be sent within three days of a job finishing."),
            ("b", "Invoices must be sent within three days and carry a client reference."),
            ("c", "Every invoice must carry a client reference and be sent within three days."),
            ("d", "Transform rough project material into a development-ready plan."),
            ("e", "When is a plan development-ready?"),
            ("f", "How do we know the plan is development-ready?"),
        )
        text = dict(given)

        for group in group_related(given):
            for left, right in combinations(group, 2):
                assert similarity(text[left], text[right]) >= GROUPING_SIMILARITY

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

    def test_the_true_pair_groups_and_the_false_one_does_not(self) -> None:
        """Both used to score below the threshold, and that was the honest state.

        `D-139` changed it without touching the threshold or the measure: two
        questions are mostly grammar, and *"where"*, *"would"* and *"does"* were
        counted as shared meaning by one pair and as bulk by the other.
        """

        assert group_related([("a", self.SAME_QUESTION[0]), ("b", self.SAME_QUESTION[1])]) == (
            ("a", "b"),
        )
        assert (
            group_related([("a", self.DIFFERENT_SUBJECTS[0]), ("b", self.DIFFERENT_SUBJECTS[1])])
            == ()
        )

    def test_the_measure_separates_them_once_grammar_is_out_of_the_union(self) -> None:
        """0.143 apart, where it was 0.014.

        **The number that said no threshold could work**: a true pair at 0.300
        and a false one at 0.286, so any value between them was fitted to two
        examples. Removing three grammar words from the union — and only from
        the union, since the false pair shares none of them — leaves the true
        pair at 0.429 and the false one unmoved at 0.286.

        This does not close `GROUP-MEASURE`, which `D-75` already answered with
        cosine. It says the lexical fallback is no longer *unable* to tell these
        two apart, and it is pinned so the next change to the constant meets the
        current evidence rather than the old.
        """

        from kae_memory.domain.lexical import similarity

        true_pair = similarity(*self.SAME_QUESTION)
        false_pair = similarity(*self.DIFFERENT_SUBJECTS)

        assert round(true_pair, 3) == 0.429
        assert round(false_pair, 3) == 0.286
        assert true_pair >= GROUPING_SIMILARITY > false_pair
