"""Timestamp normalisation at the persistence boundary."""

from datetime import UTC, datetime


def as_aware(value: datetime) -> datetime:
    """Return a timezone-aware timestamp.

    Timestamps are stored as ``TIMESTAMPTZ`` and CockroachDB returns them aware,
    so this is now a boundary guard rather than a translation: a naive value is
    interpreted as the UTC instant it was written as.

    It is kept because the invariant it protects — every domain timestamp carries
    a zone — is worth enforcing at the edge rather than trusting a driver. The
    defect that introduced it (RA-01) was a driver silently dropping the offset.
    """

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
