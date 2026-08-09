"""A question about many items must still fit in the column that stores it.

The clarification idempotency key spelled its subject out as a comma-joined
list of knowledge ids — 37 characters each, against a `varchar(200)` column. A
question spanning five or more items could not be recorded at all, and the
failure surfaced as a 500 from PostgreSQL that no application layer could
explain.

Nothing caught it because it needs a project with enough accumulated open
questions for one clarification to span them, and no small fixture has that.
It appeared in a real deployment, from a real conversation, as a message the
operator sent that produced an error instead of a reply.
"""

from __future__ import annotations

from kae_memory.application.clarification_service import Clarification, _question_key

#: The width of `messages.idempotency_key`. Named here so a schema change that
#: narrows it fails this test rather than production.
COLUMN_WIDTH = 200


def _clarification(count: int) -> Clarification:
    return Clarification(
        finding_kind="open_question",
        area_key=None,
        question="Answer each question and record the answer.",
        severity="critical",
        knowledge_ids=tuple(f"{i:08d}-539f-4f17-938d-a77dce12f2aa" for i in range(count)),
    )


class TestTheKeyFitsTheColumn:
    def test_a_question_about_many_items(self) -> None:
        """Fifty is not a stress test — it is a project that has been used."""

        assert len(_question_key(_clarification(50))) <= COLUMN_WIDTH

    def test_the_width_does_not_grow_with_the_subject(self) -> None:
        assert len(_question_key(_clarification(2))) == len(_question_key(_clarification(200)))

    def test_a_question_about_nothing(self) -> None:
        assert len(_question_key(_clarification(0))) <= COLUMN_WIDTH


class TestTheKeyStillIdentifiesTheSubject:
    def test_the_same_subject_gives_the_same_key(self) -> None:
        """Re-deriving a question must not re-ask it."""

        assert _question_key(_clarification(6)) == _question_key(_clarification(6))

    def test_order_does_not_matter(self) -> None:
        forward = _clarification(6)
        reversed_ = Clarification(
            finding_kind=forward.finding_kind,
            area_key=forward.area_key,
            question=forward.question,
            severity=forward.severity,
            knowledge_ids=tuple(reversed(forward.knowledge_ids)),
        )

        assert _question_key(forward) == _question_key(reversed_)

    def test_an_aggregate_that_grows_is_still_the_same_question(self) -> None:
        """The defect this file used to assert the opposite of.

        A finding covering several statements asks about an *area* — "these
        unresolved items need answers" — and its membership grows as the project
        does. Keying on membership gave every growth a new key, so the identical
        question was re-asked each time one more `unknown` joined it: roughly
        ten times in a 42-message session, which is enough to make an
        interviewer feel like it is not listening.

        Two aggregates of the same kind in the same area therefore collide, and
        that is the intended reading rather than a tolerated cost. They are the
        same question, asked about a set that happens to differ today.
        """

        assert _question_key(_clarification(6)) == _question_key(_clarification(7))

    def test_a_question_about_one_statement_still_names_it(self) -> None:
        """Because it is about that statement, and ends when it is resolved.

        Only aggregates lose their membership from the key. Collapsing
        single-subject questions too would make every open question in an area
        one question.
        """

        first = _clarification(1)
        second = Clarification(
            finding_kind=first.finding_kind,
            area_key=first.area_key,
            question=first.question,
            severity=first.severity,
            knowledge_ids=("99999999-539f-4f17-938d-a77dce12f2aa",),
        )

        assert _question_key(first) != _question_key(second)

    def test_one_statement_and_several_are_different_questions(self) -> None:
        """"Answer this" and "answer these" are not the same ask."""

        assert _question_key(_clarification(1)) != _question_key(_clarification(4))

    def test_a_different_finding_kind_is_a_different_question(self) -> None:
        same_subject = _clarification(3)
        other = Clarification(
            finding_kind="missing_area",
            area_key=same_subject.area_key,
            question=same_subject.question,
            severity=same_subject.severity,
            knowledge_ids=same_subject.knowledge_ids,
        )

        assert _question_key(same_subject) != _question_key(other)
