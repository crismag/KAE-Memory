"""Timestamp normalisation at the persistence boundary."""

from datetime import UTC, datetime


def as_aware(value: datetime) -> datetime:
    """Return a timezone-aware timestamp.

    Timestamps are always stored in UTC. CockroachDB returns them aware through
    ``TIMESTAMPTZ``, but some drivers used in tests drop the offset on read, so a
    naive value is interpreted as the UTC instant it was written as. Without this,
    rehydration would violate the domain's timezone-aware invariants.
    """

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
