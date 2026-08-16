"""Where a source's material is to live (`ADR-0004`, `D-162`).

Five values, and the set is closed. `classify` used to record any non-blank
string, so `EPHEMERAL` and a misspelling of it were stored alike and both read
as a decision somebody made. Nothing consumes the column yet, which is exactly
why the set closes now: the first reader inherits every value ever written, and
`ADR-0004` says reclassifying real data afterwards is the expensive order.

**Deliberately not `dispositions.Disposition`.** That name is taken, by the
*setup question* vocabulary — `answered`, `deferred`, `open` — which
`api/schemas.py` already imports. These five are a different axis about a
different subject, so they get their own word rather than a second meaning for
one this codebase has spent.

**Naming the five is not enforcing them.** `EPHEMERAL` still discards nothing;
that is a retention boundary in the ingest path (`D-161`) and a larger piece of
work. This makes the column mean one of five things instead of anything at all.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import DomainInvariantError


class SourceDisposition(StrEnum):
    """What Memory keeps of this source, and where the content itself lives."""

    MEMORY = "memory"
    """The statement itself, here. Pasted text has no other durable home."""

    RAG = "rag"
    """Plain files, with location, revision and digest recorded here."""

    ARTIFACT = "artifact"
    """The user's repository. Path, revision and hash here, never the bytes."""

    REFERENCE = "reference"
    """The source system, unmoved. A pinned coordinate here."""

    EPHEMERAL = "ephemeral"
    """Nowhere durable. A record that it was seen and discarded."""


class UnknownDispositionError(DomainInvariantError):
    """A disposition outside `ADR-0004`'s five."""


def ensure_source_disposition(value: str) -> SourceDisposition:
    """Read a caller's word as one of the five, or refuse it.

    Case and surrounding space are forgiven because `MEMORY` and `memory` are
    the same decision; a word outside the set is not, and is refused with the
    five named rather than with a bare rejection — a caller who mistyped one
    needs to see the list, and a caller who invented one needs to know there is
    a list.
    """

    try:
        return SourceDisposition(value.strip().lower())
    except ValueError:
        raise UnknownDispositionError(
            f"unknown disposition {value.strip()!r}; ADR-0004 defines "
            + ", ".join(member.value for member in SourceDisposition)
        ) from None
