"""Typed errors raised by KAE-Memory domain contracts."""


class DomainError(ValueError):
    """Base class for domain validation failures."""


class InvalidIdentifierError(DomainError):
    """Raised when a stable identifier is empty or malformed."""


class InvalidLifecycleTransitionError(DomainError):
    """Raised when a knowledge item attempts an unsupported state transition."""


class DomainInvariantError(DomainError):
    """Raised when construction would violate a domain invariant."""
