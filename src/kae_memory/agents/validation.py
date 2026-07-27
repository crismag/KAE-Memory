"""Validation between the provider and durable memory.

Structured outputs guarantee the shape of a response, not its truth. Everything
here is the second layer: the checks the schema cannot express, and the one check
that matters most — that a cited quote actually exists in the source (ADR-0006).
"""

import re
from collections.abc import Sequence
from typing import Any

from kae_memory.domain.models import KnowledgeKind

from .extraction import (
    Confidence,
    ExtractedItem,
    InvalidOutputError,
    UnverifiableOutputError,
)

_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Collapse whitespace so quoting is not defeated by re-wrapping.

    A model that reflows a quote across lines is quoting faithfully; one that
    invents words is not. Normalising whitespace distinguishes the two.
    """

    return _WHITESPACE.sub(" ", text).strip().casefold()


def parse_items(payload: Any, max_items: int) -> tuple[ExtractedItem, ...]:
    """Turn a validated JSON payload into typed items.

    Raises:
        InvalidOutputError: the payload is malformed, uses an unknown vocabulary,
            or exceeds the configured ceiling.
    """

    if not isinstance(payload, dict) or "items" not in payload:
        raise InvalidOutputError("extraction payload must be an object with an 'items' key")

    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise InvalidOutputError("extraction 'items' must be a list")
    if len(raw_items) > max_items:
        raise InvalidOutputError(
            f"extraction returned {len(raw_items)} items, ceiling is {max_items}"
        )

    items: list[ExtractedItem] = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise InvalidOutputError(f"item {index} is not an object")
        try:
            kind = KnowledgeKind(raw["kind"])
            confidence = Confidence(raw["confidence"])
            content = str(raw["content"])
            source_quote = str(raw["source_quote"])
        except (KeyError, ValueError) as error:
            raise InvalidOutputError(f"item {index} is invalid: {error}") from error

        if not content.strip():
            raise InvalidOutputError(f"item {index} has empty content")
        if not source_quote.strip():
            raise InvalidOutputError(f"item {index} has an empty source quote")

        rationale = raw.get("rationale")
        items.append(
            ExtractedItem(
                kind=kind,
                content=content,
                confidence=confidence,
                source_quote=source_quote,
                rationale=str(rationale) if rationale is not None else None,
            )
        )
    return tuple(items)


def verify_quotes(items: Sequence[ExtractedItem], source_text: str) -> None:
    """Check every cited quote against the text it claims to come from.

    This is what makes the message-to-knowledge link auditable rather than
    asserted. A fabricated quote fails the whole batch: knowledge that misstates
    its own provenance is worse than knowledge that is missing, because the audit
    trail is the product.

    Raises:
        UnverifiableOutputError: an item cites a quote absent from the source.
    """

    haystack = _normalise(source_text)
    for index, item in enumerate(items):
        if _normalise(item.source_quote) not in haystack:
            raise UnverifiableOutputError(
                f"item {index} cites a quote that does not occur in the source: "
                f"{item.source_quote!r}"
            )


def validate(payload: Any, source_text: str, max_items: int) -> tuple[ExtractedItem, ...]:
    """Parse and verify a payload, or raise.

    Nothing reaches durable memory without passing both stages.
    """

    items = parse_items(payload, max_items)
    verify_quotes(items, source_text)
    return items
