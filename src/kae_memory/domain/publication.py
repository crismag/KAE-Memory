"""What happened when someone tried to publish (N29).

**Append-oriented, and separate from the deliverable.** A publication attempt is
an event; a deliverable is a record of an output that exists. Storing the
attempt on the deliverable would mean a failed publication modifying an
immutable record — and worse, it would make "we could not write this to S3" look
like a property of the document rather than of one attempt at one destination.

The rule that follows: **a failed attempt never marks a deliverable invalid.**
The deliverable is exactly as good as it was; something between it and a bucket
did not work. Retrying is normal, and the history keeps every attempt rather
than overwriting the last one, because "it failed twice and then worked" and "it
worked" are different operational facts.

**No download URL is ever persisted.** A presigned URL is a credential with a
timer on it. Stored, it is a credential in a database that outlives its own
validity — useless when read and dangerous until then. `external_reference`
names *what was written*, and a URL is generated on demand or not at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import Identifier, ProjectId


class AttemptId(Identifier):
    """Identifies one publication attempt."""


class AttemptState(StrEnum):
    """How far one attempt got.

    Seven, and the three failure states are separate because their remedies are.
    `verification_failed` means the bytes did not match the record and nothing
    was written — a correctness problem. `failed` means the provider refused or
    broke — an operations problem. `cancelled` means a person stopped it.
    Collapsing them into "failed" would send everyone to the same runbook.
    """

    REQUESTED = "requested"
    RENDERING = "rendering"
    VERIFICATION_FAILED = "verification_failed"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL: frozenset[AttemptState] = frozenset(
    {
        AttemptState.PUBLISHED,
        AttemptState.VERIFICATION_FAILED,
        AttemptState.FAILED,
        AttemptState.CANCELLED,
    }
)
"""States an attempt does not leave.

A retry is a **new attempt**, never a reopening. Reopening would erase the fact
that this one ended, and "it failed twice and then worked" is exactly the
history an operator needs when it fails a third time.
"""

_ALLOWED: dict[AttemptState, frozenset[AttemptState]] = {
    AttemptState.REQUESTED: frozenset(
        {AttemptState.RENDERING, AttemptState.CANCELLED, AttemptState.FAILED}
    ),
    AttemptState.RENDERING: frozenset(
        {
            AttemptState.PUBLISHING,
            AttemptState.VERIFICATION_FAILED,
            AttemptState.FAILED,
            AttemptState.CANCELLED,
        }
    ),
    AttemptState.PUBLISHING: frozenset(
        {AttemptState.PUBLISHED, AttemptState.FAILED, AttemptState.CANCELLED}
    ),
}
"""Which transitions the model permits. Terminal states are absent by omission.

`rendering → publishing` cannot skip verification, because verification happens
during rendering and the only way out of `rendering` with content is through it.
"""


class ErrorCategory(StrEnum):
    """What kind of failure this was, for someone deciding whether to retry.

    Named by remedy. `transient` is worth retrying unchanged; `authorization`
    needs a person; `integrity` must not be retried at all until the deliverable
    is regenerated, because retrying a hash mismatch produces the same mismatch.
    """

    NONE = "none"
    TRANSIENT = "transient"
    AUTHORIZATION = "authorization"
    INTEGRITY = "integrity"
    CONFIGURATION = "configuration"
    PROVIDER = "provider"


RETRYABLE: frozenset[ErrorCategory] = frozenset({ErrorCategory.TRANSIENT, ErrorCategory.PROVIDER})
"""Categories a caller may retry without changing anything.

`integrity` is deliberately absent: the same deliverable will fail the same way,
and a retry loop over a hash mismatch is a way to turn one problem into a
sustained one.
"""


class PublicationError(DomainInvariantError):
    """An attempt or transition is not one this model permits."""


def ensure_attempt_transition(current: AttemptState, target: AttemptState) -> None:
    """Refuse a transition this lifecycle does not have."""

    if current in TERMINAL:
        raise PublicationError(
            f"a {current.value} attempt is finished. Publish again to create a new "
            f"attempt; reopening this one would erase the fact that it ended."
        )
    allowed = _ALLOWED.get(current, frozenset())
    if target not in allowed:
        raise PublicationError(
            f"cannot move a publication attempt from {current.value} to "
            f"{target.value}; permitted: {', '.join(sorted(s.value for s in allowed))}"
        )


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    """One attempt to write one deliverable to one target."""

    id: AttemptId
    project_id: ProjectId
    deliverable_id: str
    target_id: str
    provider: str
    state: AttemptState = AttemptState.REQUESTED
    package_hash: str | None = None
    package_size: int | None = None
    external_reference: str | None = None
    """What was written, named so a person can find it: an object key, a commit
    SHA, a path relative to the configured root.

    **Never a URL with a signature in it.** A presigned URL is a credential with
    a timer; stored, it is useless when read and dangerous until then.
    """

    verification_passed: bool | None = None
    error_category: ErrorCategory = ErrorCategory.NONE
    error_detail: str = ""
    requested_by: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.external_reference and _is_signed_url(self.external_reference):
            raise PublicationError(
                "external_reference holds a signed URL. That is a credential with "
                "an expiry, and storing one puts a secret in the database that is "
                "useless by the time anybody reads it. Record what was written; "
                "generate a URL on demand."
            )
        if self.state is AttemptState.PUBLISHED and not self.external_reference:
            raise PublicationError(
                "a published attempt must name what it wrote, or nothing can "
                "find the output it claims to have produced"
            )
        if self.state is AttemptState.PUBLISHED and self.verification_passed is not True:
            raise PublicationError(
                "an attempt cannot be published without verification passing. "
                "Writing unverified bytes puts content under an identity that "
                "may no longer describe it."
            )
        if self.error_category is not ErrorCategory.NONE and not self.error_detail.strip():
            raise PublicationError(
                f"a {self.error_category.value} failure with no detail leaves "
                f"whoever reads it with a category and no way to act on it"
            )

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL

    @property
    def succeeded(self) -> bool:
        return self.state is AttemptState.PUBLISHED

    @property
    def retryable(self) -> bool:
        """Whether retrying unchanged could plausibly work.

        False for an integrity failure: the same deliverable produces the same
        mismatch, and a retry loop turns one problem into a sustained one.
        """

        return self.finished and not self.succeeded and self.error_category in RETRYABLE


def _is_signed_url(reference: str) -> bool:
    """Whether a reference is a URL carrying a signature.

    Checks for the query parameters the major providers use. A plain `https://`
    link to a repository file is a location and is fine; the same URL with
    `X-Amz-Signature` on it is a credential.
    """

    lowered = reference.lower()
    markers = (
        "x-amz-signature",
        "x-amz-credential",
        "signature=",
        "sig=",
        "token=",
        "x-goog-signature",
    )
    return any(marker in lowered for marker in markers)
