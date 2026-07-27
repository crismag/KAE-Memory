"""The extraction boundary.

The application depends on :class:`ExtractionPort`, never on a provider SDK.
Swapping models, or falling back to fixtures during the demonstration, is a
composition-root change (ADR-0006).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind


class Confidence(StrEnum):
    """How sure the extractor is.

    Supporting information only. Confidence never substitutes for human
    confirmation (FR-005), which is why this is an enum rather than a score that
    invites being treated as a probability.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExtractionError(Exception):
    """Base class for extraction failures.

    Every subclass carries the ``error_code`` recorded on the agent run, so a
    provider outcome maps onto the run failure model without translation at the
    call site.
    """

    error_code = "extraction_failed"
    retryable = False


class ProviderUnavailableError(ExtractionError):
    """The provider was unreachable, throttled, or returned a server error."""

    error_code = "provider_unavailable"
    retryable = True


class ProviderTimeoutError(ExtractionError):
    """The provider did not answer within the bounded timeout."""

    error_code = "provider_timeout"
    retryable = True


class ProviderRefusedError(ExtractionError):
    """The provider declined the request.

    A refusal arrives as a successful response with empty or partial content, so
    it is detected from the stop reason rather than from an exception.
    """

    error_code = "provider_refused"
    retryable = False


class OutputTruncatedError(ExtractionError):
    """The response hit the token ceiling before completing."""

    error_code = "output_truncated"
    retryable = True


class InvalidOutputError(ExtractionError):
    """The response did not satisfy the schema or the domain vocabulary."""

    error_code = "invalid_output"
    retryable = True


class UnverifiableOutputError(ExtractionError):
    """An item cited a source quote that does not occur in the message.

    Not retryable: the model produced a plausible statement with fabricated
    attribution, and retrying invites the same fabrication. Knowledge that
    misstates where it came from is worse than no knowledge.
    """

    error_code = "unverifiable_output"
    retryable = False


@dataclass(frozen=True, slots=True)
class ExtractedItem:
    """One candidate produced by extraction, before any human review."""

    kind: KnowledgeKind
    content: str
    confidence: Confidence
    source_quote: str
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """What an agent asks the extractor to do."""

    role: AgentRole
    source_text: str
    context: Sequence[str] = ()
    max_items: int = 20


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """What the extractor returned, plus what it took to produce it."""

    items: tuple[ExtractedItem, ...]
    prompt_version: str
    schema_version: str
    model: str
    usage: dict[str, Any] | None = None


class ExtractionPort(Protocol):
    """The provider boundary.

    Implementations must raise an :class:`ExtractionError` subclass rather than a
    provider-specific exception, so the caller maps outcomes to run failure codes
    without knowing which provider ran.
    """

    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


SCHEMA_VERSION = "extraction.v1"

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "content", "confidence", "source_quote"],
                "properties": {
                    "kind": {"type": "string", "enum": [kind.value for kind in KnowledgeKind]},
                    "content": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": [level.value for level in Confidence],
                    },
                    "source_quote": {"type": "string"},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}
"""JSON schema constraining the response.

``additionalProperties: false`` is required on every object. Length and numeric
constraints are deliberately absent — structured outputs cannot express them, so
they are enforced in :mod:`kae_memory.agents.validation` instead.
"""
