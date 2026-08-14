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


class KnowledgeNotFoundError(DomainError):
    """The knowledge item does not exist, or does not belong to this project.

    Deliberately one error for both. A distinct "wrong project" code would
    confirm to a caller that an item they cannot touch exists somewhere else,
    which is the one fact the ownership check is there to withhold. Which case
    occurred is recorded server-side.
    """


class StaleVersionError(DomainError):
    """The item changed since the caller read it.

    Review decisions are made about specific wording, so a decision carrying a
    version number that is no longer current is a decision about text the
    reviewer has not seen. Applying it anyway is last-write-wins, which for
    authority decisions means the slower reviewer silently overrules the faster
    one.
    """


class AlreadyAnsweredError(DomainError):
    """The question already carries an answer, and a different one was offered.

    A replay of the same answer is fine and returns what was recorded. Two
    different answers under one question is not: nothing downstream could say
    which one the project believes, and extraction would run over both.
    """


class AuthoritativeOverrideError(DomainError):
    """Working-model synthesis tried to change a human-authoritative object.

    Accepted decisions and human corrections outrank unconfirmed observations.
    New evidence may create an attention item; it must not silently rewrite the
    object a person already settled.
    """
