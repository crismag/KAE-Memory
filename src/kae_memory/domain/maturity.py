"""What a deliverable is for, and what a person accepted (N38).

Maturity is the most gate-shaped idea in this phase, which is why it is built
the way it is. "Exploratory" through "production-review candidate" reads as a
ladder, and a ladder invites the question "what level are you at" — which is
one refactor away from "you are only at level two, so you cannot generate".
That is the readiness gate again, wearing a third set of words.

So **maturity is not ordered**. There is no rank, no numeric level, no
comparison, and no function anywhere that decides whether one maturity is
"enough". Each value names what the output is *for* and what evidence it rests
on, and a reader compares those to their own need rather than to a threshold.

**Accepted sufficiency is a record, not a permission.** It says a named person,
at a named time, for a named purpose, decided the current knowledge boundary
was enough for *this* generation. It does not mark any question answered, does
not confirm any assumption, and does not carry forward to the next request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .generation import GenerationMode


class Maturity(StrEnum):
    """What a deliverable is for, and what it rests on.

    Unordered by construction. The values are names, not levels, and nothing in
    this codebase compares two of them — `MATURITY_IS_UNORDERED` and its test
    exist to keep it that way.
    """

    EXPLORATORY = "exploratory"
    PRELIMINARY = "preliminary"
    PROVISIONAL = "provisional"
    IMPLEMENTATION_ORIENTED = "implementation_oriented"
    VALIDATION_ORIENTED = "validation_oriented"
    PRODUCTION_REVIEW_CANDIDATE = "production_review_candidate"


MATURITY_IS_UNORDERED = True
"""A flag with one job: to be findable.

Anyone about to add `MATURITY_ORDER` or a `>=` comparison will find this
constant and its test first, and the test says plainly why the ordering they
are about to add is the thing this model was built to avoid.
"""


DESCRIBES: dict[Maturity, str] = {
    Maturity.EXPLORATORY: (
        "developed from an early idea; offers possibilities and alternatives rather than decisions"
    ),
    Maturity.PRELIMINARY: (
        "organises what is known so far and names the major gaps; not yet a plan"
    ),
    Maturity.PROVISIONAL: (
        "usable now and expected to change; rests on stated assumptions that have not been settled"
    ),
    Maturity.IMPLEMENTATION_ORIENTED: (
        "actionable for building, with assumptions and open questions disclosed "
        "alongside what is confirmed"
    ),
    Maturity.VALIDATION_ORIENTED: (
        "emphasises evidence, risk, and unresolved commitments for review"
    ),
    Maturity.PRODUCTION_REVIEW_CANDIDATE: (
        "offered for production review; the reviewer decides, and this label does "
        "not claim the review passed"
    ),
}
"""What each maturity means, in words a reader can compare to their own need.

Exhaustive by construction: a value without a description would be a label
nobody can act on.
"""

if set(DESCRIBES) != set(Maturity):  # pragma: no cover - import guard
    missing = sorted(set(Maturity) - set(DESCRIBES))
    raise DomainInvariantError(f"maturity values without a description: {missing}")


SUGGESTED_FOR: dict[GenerationMode, Maturity] = {
    GenerationMode.EXPLORE: Maturity.EXPLORATORY,
    GenerationMode.SHAPE: Maturity.PRELIMINARY,
    GenerationMode.PLAN: Maturity.PROVISIONAL,
    GenerationMode.BUILD: Maturity.IMPLEMENTATION_ORIENTED,
    GenerationMode.VALIDATE: Maturity.VALIDATION_ORIENTED,
}
"""A default label per mode. A **suggestion**, never a requirement.

No mode demands a maturity and no maturity demands a mode. A caller who asks
for a build package and labels it exploratory has described their own output
accurately, and nothing here second-guesses that.
"""


@dataclass(frozen=True, slots=True)
class AcceptedSufficiency:
    """A person deciding the current knowledge is enough for one generation.

    Every field exists to bound the decision. Without the purpose it would read
    as a blanket approval; without the actor it is nobody's decision; without
    what was disclosed, a later reader cannot tell whether the person accepting
    knew what they were accepting.
    """

    purpose: str
    accepted_by: str
    accepted_at: datetime
    disclosed: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.purpose.strip():
            raise DomainInvariantError(
                "an acceptance names the purpose it applies to. Without one it reads "
                "as approval of the project rather than of one generation."
            )
        if not self.accepted_by.strip():
            raise DomainInvariantError(
                "an acceptance names who made it: a decision nobody is named for is none"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "purpose": self.purpose,
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at.isoformat(),
            "disclosed": list(self.disclosed),
            # Stated in the record rather than left to a reader's assumption.
            # This is the field that stops an acceptance being read as a
            # standing permission.
            "applies_to": "this generation only",
        }


@dataclass(frozen=True, slots=True)
class DeliverableQualification:
    """What a deliverable is for, and what it rests on.

    Carried alongside the immutable identity rather than inside it. Identity
    says *what was produced*; this says *what it was produced for* and what a
    reader should know before acting on it. Immutability describes the first
    and makes no claim about completeness.
    """

    maturity: Maturity
    mode: GenerationMode
    intended_use: str = ""
    confirmed_count: int = 0
    unconfirmed_count: int = 0
    material_assumptions: tuple[str, ...] = ()
    open_decisions: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    deferred_questions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    accepted: AcceptedSufficiency | None = None
    qualifications: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.confirmed_count < 0 or self.unconfirmed_count < 0:
            raise DomainInvariantError("a statement count cannot be negative")
        if self.unconfirmed_count and not self.qualifications:
            raise DomainInvariantError(
                "a deliverable resting on unconfirmed statements must carry the "
                "qualification that says so. Silence here is the package claiming "
                "more than its evidence."
            )

    @property
    def rests_on_unconfirmed(self) -> bool:
        return self.unconfirmed_count > 0

    def as_dict(self) -> dict[str, object]:
        return {
            "maturity": self.maturity.value,
            "maturity_means": DESCRIBES[self.maturity],
            "mode": self.mode.value,
            "intended_use": self.intended_use,
            "confirmed_statements": self.confirmed_count,
            "unconfirmed_statements": self.unconfirmed_count,
            "material_assumptions": list(self.material_assumptions),
            "open_decisions": list(self.open_decisions),
            "contradictions": list(self.contradictions),
            "deferred_questions": list(self.deferred_questions),
            "limitations": list(self.limitations),
            "next_actions": list(self.next_actions),
            "qualifications": list(self.qualifications),
            "accepted_sufficiency": self.accepted.as_dict() if self.accepted else None,
            # The sentence that keeps this whole structure from becoming a gate.
            "note": (
                "Maturity describes what this package is for and what it rests on. "
                "It is not a permission level and nothing compares two of them."
            ),
        }
