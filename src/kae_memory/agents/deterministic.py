"""Fixture-backed extraction.

Determinism cannot come from sampling parameters: ``temperature``, ``top_p``, and
``top_k`` are rejected by the current models. It comes from here instead — a
recorded fixture returned without opening a socket (ADR-0006).

This adapter backs every test and is the documented demonstration fallback. No
test may make a live model call.
"""

import re
from collections.abc import Callable, Sequence

from kae_memory.domain.models import KnowledgeKind

from .extraction import (
    SCHEMA_VERSION,
    Confidence,
    ExtractionRequest,
    ExtractionResult,
    InvalidOutputError,
)
from .prompts import prompt_for
from .validation import validate

Fixture = Callable[[ExtractionRequest], object]

_SENTENCE = re.compile(r"[^.!?]+[.!?]?")

# Which knowledge kind a sentence looks like. Order matters: the first match
# wins. Stated intent outranks a mentioned noun — "we need a way for staff to
# submit reports" is a goal that happens to name an actor, not an actor
# description.
_CUES: tuple[tuple[KnowledgeKind, tuple[str, ...]], ...] = (
    (KnowledgeKind.UNKNOWN, ("not decided", "undecided", "not sure", "tbd", "unclear", "?")),
    (KnowledgeKind.DECISION, ("we chose", "we will use", "we decided")),
    (KnowledgeKind.GOAL, ("we want", "we need", "our goal", "so that", "in order to")),
    (KnowledgeKind.CONSTRAINT, ("must not", "cannot", "only", "limited to", "no more than")),
    (KnowledgeKind.RULE, ("before", "after", "whenever", "each time", "always")),
    (KnowledgeKind.ACTOR, ("staff", "user", "users", "admin", "manager", "customer")),
)


def sentence_fixture(request: ExtractionRequest) -> object:
    """Derive candidates from the source text, one per sentence.

    **This is not extraction intelligence.** It is a rule-based stand-in that
    keeps the product workflow demonstrable without a provider: every sentence
    becomes a candidate, quoted verbatim so the provenance chain is real, and
    classified by surface cues that a language model would not need.

    It exists so that cloning the repository is enough to walk the workflow. Any
    judgement about what the *content* means requires the live adapter, and a
    demonstration that leans on this should say which one it used.
    """

    items = []
    for match in _SENTENCE.finditer(request.source_text):
        sentence = match.group().strip()
        if len(sentence) < 12:
            continue
        items.append(
            {
                "kind": _classify(sentence).value,
                "content": sentence,
                "confidence": Confidence.MEDIUM.value,
                "source_quote": sentence,
                "rationale": "derived by the offline sentence fixture, not by a model",
            }
        )
        if len(items) >= request.max_items:
            break
    return {"items": items}


def _classify(sentence: str) -> KnowledgeKind:
    lowered = sentence.casefold()
    for kind, cues in _CUES:
        if any(cue in lowered for cue in cues):
            return kind
    return KnowledgeKind.REQUIREMENT


class DeterministicExtractionAdapter:
    """Return recorded payloads, validated exactly as a live response would be.

    Fixtures pass through the same validation path as the provider, so a fixture
    that would have been rejected in production is rejected here too — otherwise
    the tests would prove something the real adapter does not do.
    """

    model = "deterministic-fixture"

    def __init__(self, fixtures: Sequence[Fixture] | Fixture | None = None) -> None:
        if fixtures is None:
            # The default keeps `python -m kae_memory.worker` demonstrable with
            # no configuration. Tests that assert specific extraction behaviour
            # pass their own fixtures and never reach this path.
            self._fixtures: list[Fixture] = [sentence_fixture]
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
