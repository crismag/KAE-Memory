"""Typed errors raised by KAE-Memory domain contracts."""


class DomainError(ValueError):
    """Base class for domain validation failures."""


class InvalidIdentifierError(DomainError):
    """Raised when a stable identifier is empty or malformed."""


class InvalidLifecycleTransitionError(DomainError):
    """Raised when a knowledge item attempts an unsupported state transition."""


class DomainInvariantError(DomainError):
    """Raised when construction would violate a domain invariant."""


class InvalidRunTransitionError(DomainError):
    """Raised when an agent run attempts an unsupported status transition."""


class IdempotencyConflictError(DomainError):
    """A retried write reused a key with a different payload.

    Returning the original record would silently discard the caller's new
    content; writing a second record would break the guarantee the key exists
    to provide. Neither is safe, so the conflict is reported.
    """
