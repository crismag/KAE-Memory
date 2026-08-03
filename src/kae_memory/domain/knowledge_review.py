"""The durable record of human decisions about proposed knowledge.

A lifecycle state says what a statement *is* now. It cannot say who decided
that, when, on which wording, or why — and for knowledge that a person accepted
as authoritative, "why" is the part that matters when someone later disagrees.
The state is the conclusion; these events are the reasoning, and they are
append-only because a decision that can be edited is not a record of a decision.

Confirmation is a human act (FR-005). Every event therefore names an actor, and
an agent-authored event is never recorded as a human one.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import KnowledgeItemId, ProjectId, ReviewEventId
from .lifecycle import LifecycleState
from .workspace import ActorType


class ReviewAction(StrEnum):
    """What a reviewer did.

    Named for the decision rather than the resulting state. ``corrected`` and
    ``validated`` can both leave an item ``VALIDATED``; collapsing them into one
    "updated" event would lose the distinction between accepting what an agent
    proposed and rewriting it first, which is precisely the distinction an audit
    reader is looking for.
    """

    VALIDATED = "knowledge_validated"
    REJECTED = "knowledge_rejected"
    CORRECTED = "knowledge_corrected"


class RejectionReason(StrEnum):
    """Why proposed knowledge was turned down.

    Deliberately small. A large taxonomy invites reviewers to shop for a label
    that fits rather than write the sentence that explains, and the note is the
    part a future reader actually needs.
    """

    INCORRECT = "incorrect"
    IRRELEVANT = "irrelevant"
    DUPLICATE = "duplicate"
    OBSOLETE = "obsolete"
    UNSUPPORTED = "unsupported"
    OUT_OF_SCOPE = "out_of_scope"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class KnowledgeReviewEvent:
    """One recorded review decision. Append-only; never updated.

    ``version_number`` is the version the decision was made *about*. A reviewer
    confirms wording, not an abstract item, so an event that did not name a
    version could not answer "what did they actually agree to" after a later
    correction.
    """

    id: ReviewEventId
    project_id: ProjectId
    knowledge_item_id: KnowledgeItemId
    version_number: int
    action: ReviewAction
    from_lifecycle: LifecycleState
    to_lifecycle: LifecycleState
    actor_type: ActorType
    created_at: datetime
    actor_id: str | None = None
    reason_code: RejectionReason | None = None
    note: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.version_number < 1:
            raise DomainInvariantError("a review event must name a version")
        if self.created_at.tzinfo is None:
            raise DomainInvariantError("review event created_at must be timezone-aware")
        if self.action is ReviewAction.REJECTED and self.reason_code is None:
            raise DomainInvariantError("a rejection must record why")
        if self.action is not ReviewAction.REJECTED and self.reason_code is not None:
            raise DomainInvariantError("only a rejection carries a reason code")
        if self.reason_code is RejectionReason.OTHER and not (self.note or "").strip():
            # "other" is not a reason. Without the note the event records that
            # someone declined to say, which is worse than no category at all.
            raise DomainInvariantError("a rejection reason of 'other' requires a note")


__all__ = [
    "KnowledgeReviewEvent",
    "RejectionReason",
    "ReviewAction",
]
