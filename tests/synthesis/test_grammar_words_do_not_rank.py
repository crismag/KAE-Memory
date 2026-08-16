"""`LEX-MODALS`: completing the stopword families, and what it does not move.

`D-139`. Widening `_STOPWORDS` touches every lexical path in the estate at once —
retrieval, neighbourhoods, support pairs, near-duplicates and grouping — so the
row asked for a before/after measurement rather than a one-line edit. This file
is the after half of it, pinned: the meaning-bearing consumers are asserted
*unchanged* over both regression corpora, and the retrieval defect the row was
opened for is asserted fixed.

The numbers below were measured on the corpora **before** the widening. If one
moves, grammar has started carrying meaning somewhere.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations

from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.lexical import (
    _STOPWORDS,
    group_related,
    is_near_duplicate,
    match,
    terms,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.reconciliation import (
    EvidenceSnapshot,
    classify_pair,
    lexical_neighborhood,
)
from tests.synthesis import corpus as golden
from tests.synthesis.compute_lab import OBSERVATIONS as COMPUTE_LAB

STORAGE_QUERY = "where should reports be stored"
"""The row's own example: a modal was doing half the work of the match."""

ANSWERING_STATEMENT = "Reports are stored in S3 with a pointer."
UNRELATED_RULE = "A submitter should not approve their own report."

DEVELOPMENT_READY_QUESTION = "What does development-ready mean for this project?"
"""Had no lexical neighbours at all, because ``does`` was a third of its query."""


def _snapshots(observations: tuple[object, ...]) -> tuple[EvidenceSnapshot, ...]:
    return tuple(
        EvidenceSnapshot(
            KnowledgeItemId(f"item-{index:04d}"),
            item.kind.value,  # type: ignore[attr-defined]
            item.content,  # type: ignore[attr-defined]
            LifecycleState.PROPOSED,
        )
        for index, item in enumerate(observations)
    )


def _relation_counts(observations: tuple[object, ...]) -> Counter[str]:
    snapshots = _snapshots(observations)
    return Counter(classify_pair(left, right).value for left, right in combinations(snapshots, 2))


def _texts(observations: tuple[object, ...]) -> list[tuple[str, str]]:
    return [
        (f"item-{index:04d}", item.content)  # type: ignore[attr-defined]
        for index, item in enumerate(observations)
    ]


class TestTheFamiliesAreComplete:
    """A half-present family is worse than an absent one: the missing member ranks."""

    def test_every_interrogative_is_a_stopword(self) -> None:
        assert {"how", "what", "when", "where", "which", "who", "why"} <= _STOPWORDS

    def test_every_modal_is_a_stopword(self) -> None:
        assert {"can", "could", "may", "must", "shall", "should", "will", "would"} <= _STOPWORDS

    def test_every_auxiliary_is_a_stopword(self) -> None:
        assert {"be", "been", "is", "are", "was", "were", "has", "have"} <= _STOPWORDS
        assert {"do", "does", "did"} <= _STOPWORDS


class TestTheDefectTheRowNamed:
    def test_a_modal_no_longer_carries_a_quarter_of_the_query(self) -> None:
        assert terms(STORAGE_QUERY) == ("report", "stor")

    def test_the_answer_outranks_the_rule_that_merely_says_should(self) -> None:
        query = terms(STORAGE_QUERY)
        assert match(query, ANSWERING_STATEMENT).score == 1.0
        assert match(query, UNRELATED_RULE).score == 0.5

    def test_a_question_reaches_its_own_paraphrases(self) -> None:
        """It reached nothing before: ``does`` held coverage below `MIN_COVERAGE`."""

        snapshots = _snapshots(golden.OBSERVATIONS)
        focus = next(item for item in snapshots if item.content == DEVELOPMENT_READY_QUESTION)
        neighbours = lexical_neighborhood(focus, snapshots)
        by_id = {snapshot.id: snapshot.content for snapshot in snapshots}
        assert {by_id[neighbour.item_id] for neighbour in neighbours} == {
            "When is a plan development-ready?",
            "How do we know the plan is development-ready?",
            "What makes output development-ready rather than merely documented?",
        }


class TestNothingAboutMeaningMoves:
    """Measured before the widening. Grammar has no meaning to lose."""

    def test_golden_corpus_pair_relations_are_unchanged(self) -> None:
        counts = _relation_counts(golden.OBSERVATIONS)
        assert counts["resolve"] == 18
        assert counts["support"] == 5
        assert counts["contradict"] == 0

    def test_compute_lab_pair_relations_are_unchanged(self) -> None:
        counts = _relation_counts(COMPUTE_LAB)
        assert counts["support"] == 15
        assert counts["resolve"] == 3
        assert counts["contradict"] == 0

    def test_grouping_is_unchanged_on_both_corpora(self) -> None:
        assert len(group_related(_texts(golden.OBSERVATIONS))) == 9
        assert len(group_related(_texts(COMPUTE_LAB))) == 7

    def test_near_duplicates_are_unchanged_on_both_corpora(self) -> None:
        for observations, expected in ((golden.OBSERVATIONS, 1), (COMPUTE_LAB, 0)):
            pairs = combinations(_snapshots(observations), 2)
            found = sum(
                1 for left, right in pairs if is_near_duplicate(left.content, right.content)
            )
            assert found == expected
