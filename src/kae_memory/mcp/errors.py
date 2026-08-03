"""Structured errors for the MCP surface.

A traceback is not a tool result. Every failure returns a typed payload the
model can act on, and no failure carries a connection string, a credential, or
a driver message that might contain one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class McpError(Exception):
    """Base class for errors that are safe to return to a client."""

    code = "error"

    def payload(self) -> dict[str, Any]:
        """Return the structured form of this error."""

        return {"error": self.code, "message": str(self)}


class ProjectNotFoundError(McpError):
    """The requested project does not exist."""

    code = "project_not_found"


class InvalidArgumentError(McpError):
    """An argument was missing, malformed, or out of range."""

    code = "invalid_argument"


class KnowledgeNotFoundError(McpError):
    """The knowledge item does not exist in this project.

    One code covers "no such item" and "belongs to another project". A separate
    mismatch code would confirm that an item the caller may not touch exists
    somewhere else, and that is the fact the ownership check withholds.
    """

    code = "knowledge_not_found"


class VersionConflictError(McpError):
    """The item changed since the caller read it.

    Not a transient failure and not worth a blind retry: the wording the
    decision was about is no longer the current wording. Re-read the item and
    decide again on what it says now.
    """

    code = "version_conflict"


class InvalidStateTransitionError(McpError):
    """The requested decision is not available from the item's current state.

    Rejected and superseded knowledge cannot be confirmed. Reopening is a
    different act with different consequences, and it is not this tool.
    """

    code = "invalid_state_transition"


@dataclass
class CapabilityUnavailableError(McpError):
    """The capability is not implemented, and the gap is reported rather than faked.

    ADR-0018 requires this for module context: fabricating module records in
    the adapter would place a second, unversioned project model outside the
    domain. An agent correctly declining to proceed on undefined ground is the
    product working.
    """

    capability: str
    missing: list[str] = field(default_factory=list)
    use_instead: list[str] = field(default_factory=list)
    subject: dict[str, Any] | None = None
    available_now: dict[str, Any] | None = None
    next_steps: list[str] = field(default_factory=list)
    code = "capability_unavailable"

    def __str__(self) -> str:
        return f"{self.capability} is not available in this KAE-Memory version"

    def payload(self) -> dict[str, Any]:
        """Render the gap, and where possible the path out of it.

        ``subject``, ``available_now``, and ``next_steps`` are additive. They
        describe what *was* asked for, what the store can honestly offer in its
        place, and what would close the gap — without softening the error. A
        caller that only understands the original fields still reads this
        correctly as unavailable.
        """

        payload: dict[str, Any] = {
            "error": self.code,
            "message": str(self),
            "capability": self.capability,
            "missing_capabilities": self.missing,
            "use_instead": self.use_instead,
            "guidance": (
                "This is a real capability gap, not a transient failure. Do not "
                "infer the missing information and do not proceed as though it "
                "were known."
            ),
        }
        if self.subject is not None:
            payload["subject"] = self.subject
        if self.available_now is not None:
            payload["available_now"] = self.available_now
        if self.next_steps:
            payload["next_steps"] = self.next_steps
        return payload


def safe_error(exception: Exception) -> dict[str, Any]:
    """Return a structured payload for any exception.

    Unexpected exceptions are reported by type only. Their text may embed a
    DSN, a host, or a driver detail, and a tool result is not the place to
    discover that.
    """

    if isinstance(exception, McpError):
        return exception.payload()
    return {
        "error": "internal_error",
        "message": f"the operation failed ({type(exception).__name__})",
    }
