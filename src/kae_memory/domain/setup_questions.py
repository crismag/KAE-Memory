"""Questions about how a project is configured, not about what it is (N25).

**Its own model, and the decision was made on evidence rather than economy.**
A `Clarification` is derived from a `Finding`, has no identity until
materialised, carries `finding_kind`, `severity`, and `knowledge_ids`, and is
answerable only through the finding that produced it. A setup question has no
finding, targets a configuration field rather than a statement, and has to
record whether its answer becomes the project default.

Forcing one into the other would have needed a `purpose` field plus four
nullable columns that mean nothing for half the rows, and every query would then
have to remember which half it was looking at. The two lifecycles would distort
each other, which the product context explicitly forbids.

The queues stay separate for a reason a person feels: "what should this product
do?" and "where should this publish?" are different conversations, and a system
that interleaves them makes both worse.

What is **shared** is the disposition vocabulary (N36). "I don't know yet,
choose something reasonable" is exactly as valid an answer about a publication
target as about a requirement, and re-inventing it here would have produced a
second, subtly different version of a distinction that took a manual test
failure to get right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .dispositions import Disposition, settles
from .errors import DomainInvariantError
from .identifiers import Identifier, ProjectId
from .setup import InferencePolicy, ensure_inferable


class SetupQuestionId(Identifier):
    """Identifies one setup question."""


class SetupPurpose(StrEnum):
    """What answering this would let the project do.

    Named by outcome rather than by subject, because that is what makes a
    question worth answering. "Where do deliverables go?" is a chore;
    "publication needs a destination" is a reason.
    """

    ACQUISITION = "acquisition"
    """Reading a repository, a document set, or another primary source."""

    GENERATION = "generation"
    """Assembling and rendering an output."""

    PUBLICATION = "publication"
    """Writing an output somewhere durable."""

    AUTHORIZATION = "authorization"
    """Granting KAE permission to reach a provider. **Always blocking**, and
    never inferable: permission is granted, not worked out."""


ALWAYS_BLOCKING: frozenset[SetupPurpose] = frozenset({SetupPurpose.AUTHORIZATION})
"""Purposes whose questions block regardless of how they were created.

One entry, and it is the one that must not be softened by a caller in a hurry.
Everything else is blocking or not depending on what was asked.
"""


class SetupQuestionError(DomainInvariantError):
    """A setup question or its answer is not one this model permits."""


@dataclass(frozen=True, slots=True)
class SetupQuestion:
    """One question about configuration, with what KAE would suggest.

    `suggested_answer` and `suggestion_evidence` travel together or not at all.
    A suggestion with no evidence is KAE asserting a preference, and a person
    reading one has no way to judge it — which turns "does this look right?"
    into "do you trust the machine?".
    """

    id: SetupQuestionId
    project_id: ProjectId
    purpose: SetupPurpose
    question: str
    field_name: str
    """The configuration field an answer sets. Named rather than inferred from
    the wording, because an answer that cannot be routed to a field is a
    sentence in a log."""

    blocking: bool = False
    suggested_answer: str | None = None
    suggestion_evidence: str | None = None
    policy: InferencePolicy = InferencePolicy.ASK
    disposition: Disposition = Disposition.OPEN
    answer: str | None = None
    answered_by: str | None = None
    becomes_default: bool = False
    """Whether the answer configures the project or only this operation.

    Recorded rather than assumed either way. An override that silently became
    the default is the failure N27 names; a default nobody meant to set is the
    same failure earlier in the sequence.
    """

    revisitable: bool = True
    asked_at: datetime | None = None
    answered_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise SetupQuestionError("a setup question needs a question")
        if not self.field_name.strip():
            raise SetupQuestionError(
                "a setup question needs the field it configures; an answer that "
                "cannot be routed to a field is a sentence in a log"
            )
        if self.suggested_answer and not (self.suggestion_evidence or "").strip():
            raise SetupQuestionError(
                f"the suggestion for {self.field_name} has no evidence. A person "
                f"reading it could only judge whether to trust the machine."
            )
        ensure_inferable(self.field_name, self.policy)
        if self.purpose in ALWAYS_BLOCKING and not self.blocking:
            raise SetupQuestionError(
                f"a {self.purpose.value} question is always blocking: permission "
                f"is granted, and proceeding without it is proceeding without it"
            )
        if settles(self.disposition) and not (self.answer or "").strip():
            raise SetupQuestionError(
                f"{self.field_name} is marked {self.disposition.value} with no answer"
            )

    @property
    def settled(self) -> bool:
        """Whether this stops being owed.

        The same rule as a clarification (N36): a response that did not decide
        leaves the question open. "Pick something reasonable for now" configures
        nothing permanently, and recording it as settled would make it permanent
        by accident.
        """

        return settles(self.disposition)

    @property
    def blocks(self) -> bool:
        """Whether this stops an operation right now."""

        return self.blocking and not self.settled

    @property
    def configures_project(self) -> bool:
        """Whether answering this changes the project's default configuration."""

        return self.settled and self.becomes_default
