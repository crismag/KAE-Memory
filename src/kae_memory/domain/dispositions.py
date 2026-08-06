"""How a question was left, not only whether it was answered (N36).

The clarification model had two states: a question was open, or it had an
answer. Manual testing found what that cannot express. Asked which problem the
product solves, the answer was *"I don't know yet. Recommend something
reasonable for a prototype, but don't make it a permanent project decision."*

That is a real answer. Recording it as an answer would have closed the
question, and closing it would have been false — nobody decided anything.
Leaving it open would have lost the instruction. Neither state was the truth,
so the vocabulary was wrong rather than the workflow.

**A disposition says what happened to a question. Only some dispositions
settle it.** That distinction is the whole target: a queue that cannot tell
"deferred" from "answered" stops telling anyone what is genuinely undecided,
and a queue nobody trusts gets ignored.

Priority is separate and answers a different question — not *what happened to
this* but *does it matter now*. Ten helpful questions must never make a project
look blocked.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import DomainInvariantError


class QuestionPriority(StrEnum):
    """How much this question's absence costs, by consequence rather than count.

    Only the last three can block an operation, and each blocks exactly one.
    `HELPFUL` and `IMPORTANT` change the quality of an answer and never the
    availability of one — which is the N34 rule applied to questions.
    """

    HELPFUL = "helpful"
    IMPORTANT = "important"
    DEFERRED = "deferred"
    CAPABILITY_BLOCKING = "capability_blocking"
    AUTHORIZATION_BLOCKING = "authorization_blocking"
    INTEGRITY_BLOCKING = "integrity_blocking"


BLOCKING_PRIORITIES: frozenset[QuestionPriority] = frozenset(
    {
        QuestionPriority.CAPABILITY_BLOCKING,
        QuestionPriority.AUTHORIZATION_BLOCKING,
        QuestionPriority.INTEGRITY_BLOCKING,
    }
)
"""Priorities that may stop an operation, each for a technical reason.

None of them is "this would be nice to know". A project with ten helpful and
two deferred questions is not blocked, and a model that let it look blocked
would be the readiness gate again, in the question queue.
"""


class Disposition(StrEnum):
    """What happened to a question."""

    OPEN = "open"
    SUGGESTED = "suggested"
    ANSWERED = "answered"
    DEFERRED = "deferred"
    UNKNOWN_BY_USER = "unknown_by_user"
    DELEGATED = "delegated"
    ASSUMED_FOR_GENERATION = "assumed_for_generation"
    NO_LONGER_RELEVANT = "no_longer_relevant"
    SUPERSEDED = "superseded"


SETTLES: frozenset[Disposition] = frozenset(
    {
        Disposition.ANSWERED,
        Disposition.NO_LONGER_RELEVANT,
        Disposition.SUPERSEDED,
    }
)
"""Dispositions that close a question.

`answered` because someone answered it. The other two because the question
stopped applying — a different thing from being resolved, and worth
distinguishing when a reader asks why it left the queue.

**Everything else leaves the question open**, and that is the correction this
target makes. `unknown_by_user`, `delegated`, and `assumed_for_generation` all
record that the conversation moved on *without* the question being settled: the
project proceeded on something provisional, and the queue must keep saying so.
"""


NEEDS_ASSUMPTION: frozenset[Disposition] = frozenset(
    {Disposition.DELEGATED, Disposition.ASSUMED_FOR_GENERATION}
)
"""Dispositions that mean KAE chose something, so an assumption must exist.

Recording "KAE decided" without recording *what* it decided would leave a
project proceeding on a choice nobody can find, review, or reverse. The
assumption is the record; the disposition only says a question points at one.
"""


class DispositionError(DomainInvariantError):
    """A disposition that cannot mean what it claims."""


def ensure_disposition(
    disposition: Disposition,
    answer: str | None = None,
    assumption_id: str | None = None,
) -> None:
    """Check that a disposition is supported by what came with it.

    Each rule exists because the alternative is a record that reads as more
    settled than the conversation was.
    """

    if disposition is Disposition.ANSWERED and not (answer or "").strip():
        raise DispositionError(
            "an answered question needs the answer. Marking one answered with "
            "nothing recorded would close it on the strength of a claim nobody "
            "can read"
        )
    if disposition in NEEDS_ASSUMPTION and not assumption_id:
        raise DispositionError(
            f"{disposition.value} means KAE chose something, so it must name the "
            f"assumption holding that choice. Otherwise the project proceeds on a "
            f"decision nobody can find, review, or reverse."
        )
    if disposition is Disposition.OPEN:
        raise DispositionError(
            "`open` is where a question starts, not somewhere it is put. Use "
            "`deferred` for a question set aside deliberately."
        )


def settles(disposition: Disposition) -> bool:
    """Whether this disposition takes the question out of the open queue."""

    return disposition in SETTLES


def blocks(priority: QuestionPriority) -> bool:
    """Whether a question at this priority may stop an operation."""

    return priority in BLOCKING_PRIORITIES
