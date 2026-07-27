"""Fixture-backed extraction.

Determinism cannot come from sampling parameters: ``temperature``, ``top_p``, and
``top_k`` are rejected by the current models. It comes from here instead — a
recorded fixture returned without opening a socket (ADR-0006).

This adapter backs every test and is the documented demonstration fallback. No
test may make a live model call.
"""

from collections.abc import Callable, Sequence

from .extraction import (
    SCHEMA_VERSION,
    ExtractionRequest,
    ExtractionResult,
    InvalidOutputError,
)
from .prompts import prompt_for
from .validation import validate

Fixture = Callable[[ExtractionRequest], object]


class DeterministicExtractionAdapter:
    """Return recorded payloads, validated exactly as a live response would be.

    Fixtures pass through the same validation path as the provider, so a fixture
    that would have been rejected in production is rejected here too — otherwise
    the tests would prove something the real adapter does not do.
    """

    model = "deterministic-fixture"

    def __init__(self, fixtures: Sequence[Fixture] | Fixture | None = None) -> None:
        if fixtures is None:
            self._fixtures: list[Fixture] = []
        elif callable(fixtures):
            self._fixtures = [fixtures]
        else:
            self._fixtures = list(fixtures)
        self._calls = 0

    @property
    def call_count(self) -> int:
        """How many extractions have been served."""

        return self._calls

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Return the next fixture, validated against the request's source text."""

        if not self._fixtures:
            raise InvalidOutputError("no fixture configured for this extraction")
        fixture = self._fixtures[min(self._calls, len(self._fixtures) - 1)]
        self._calls += 1

        payload = fixture(request)
        items = validate(payload, request.source_text, request.max_items)
        version, _ = prompt_for(request.role)
        return ExtractionResult(
            items=items,
            prompt_version=version,
            schema_version=SCHEMA_VERSION,
            model=self.model,
        )
