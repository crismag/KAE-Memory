"""Classifying an observation with a model on this machine (`ADR-0006`).

The last hosted-model dependency in the extraction loop. `OllamaEmbeddingAdapter`
made ranking local and `OllamaExtractionAdapter` made extraction local; until
this, a deployment that reached no network still had to classify by regular
expression, which `semantic_classifier.py` opens by explaining is honest and is
also most sentences.

## A second transport, not a second classifier (`D-122`)

Everything that decides what a classification *means* is imported from
`semantic_classifier`: the prompt, the schema, the sentence split, the parser,
and the span assembly. This module supplies the HTTP call and nothing else.
Writing a second prompt here would be writing a second definition of the
twenty-six classes, and the two would part company at the first change to
`ObservationClass`.

The schema is sent as Ollama's ``format`` rather than described in prose, for
the reason `OllamaExtractionAdapter` already gives: it constrains generation,
and without it a local model returns prose around its JSON often enough to
matter.

## It degrades the same way, and says so

Any provider failure falls back to the deterministic classifier and sets
`last_degraded`. The local case makes that more than theoretical — Ollama not
running is the ordinary state of a machine that has not started it — so a
degraded call must stay distinguishable from a confident one rather than being
reported as semantic.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx

from kae_memory.domain.observation import ClassifiedSpan, ObservationClass, Span

from .observation_classifier import DeterministicObservationClassifier
from .ollama_extraction import OLLAMA_URL
from .semantic_classifier import (
    CLASSIFICATION_PROMPT,
    CLASSIFICATION_SCHEMA,
    SemanticClassificationError,
    parse_assignments,
    spans_for,
    split_sentences,
)

OLLAMA_CLASSIFIER_NAME = "kae-ollama-observation-classifier"
"""Its own name, because `name` is persisted with the span.

Sharing the Bedrock adapter's name would leave the record unable to answer which
model read the sentence, which is the question provenance exists for.
"""

OLLAMA_CLASSIFIER_VERSION = "1.0"

DEFAULT_MODEL = "qwen2.5:14b"
"""The same general model extraction uses. Assigning one of twenty-six labels to
a sentence is reading comprehension, not code generation."""

DEFAULT_TIMEOUT = 120.0
"""Shorter than extraction's 300s: this reads sentences already split, and one
observation is a much smaller prompt than a document. Still generous, because a
cold GPU takes tens of seconds before its first token."""


class OllamaObservationClassifier:
    """Classification by meaning, backed by a local Ollama instance."""

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        fallback: DeterministicObservationClassifier | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport
        self._fallback = fallback or DeterministicObservationClassifier()
        self._degraded = False

    @property
    def name(self) -> str:
        return OLLAMA_CLASSIFIER_NAME

    @property
    def version(self) -> str:
        return OLLAMA_CLASSIFIER_VERSION

    @property
    def semantic(self) -> bool:
        """Whether the **most recent** call classified by meaning."""

        return not self._degraded

    @property
    def last_degraded(self) -> bool:
        """Whether the most recent call fell back to rules."""

        return self._degraded

    def classify(self, text: str) -> tuple[ClassifiedSpan, ...]:
        """Classify each sentence, falling back to rules if the provider fails."""

        sentences = split_sentences(text)
        if not sentences:
            self._degraded = False
            return ()

        try:
            assigned = self._ask(sentences)
        except Exception:
            # Any provider failure, including Ollama simply not running. The
            # observation is already recorded, so losing its classification is
            # the smaller loss and `last_degraded` keeps the difference readable.
            self._degraded = True
            return self._fallback.classify(text)

        self._degraded = False
        return spans_for(sentences, assigned)

    def _ask(
        self, sentences: Sequence[tuple[str, Span]]
    ) -> dict[int, tuple[ObservationClass, float, str]]:
        """Return the model's class per sentence index."""

        numbered = "\n".join(
            f"{index}. {sentence}" for index, (sentence, _) in enumerate(sentences)
        )

        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = client.post(
                    "/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "format": CLASSIFICATION_SCHEMA,
                        "messages": [
                            {"role": "system", "content": CLASSIFICATION_PROMPT},
                            {"role": "user", "content": numbered},
                        ],
                    },
                )
        except httpx.TimeoutException as error:
            raise SemanticClassificationError(
                f"the local classifier did not answer within {self._timeout:.0f}s"
            ) from error
        except httpx.HTTPError as error:
            raise SemanticClassificationError(
                f"Ollama is not reachable at {self._base_url}: {type(error).__name__}. "
                "Start it, or set KAE_OBSERVATION_CLASSIFIER to a provider this "
                "deployment has."
            ) from error

        if response.status_code == 404:
            raise SemanticClassificationError(
                f"Ollama has no model {self.model!r}. Pull it with: ollama pull {self.model}"
            )
        if response.status_code != 200:
            raise SemanticClassificationError(f"Ollama refused the request: {response.status_code}")

        body = response.json()
        if body.get("done_reason") == "length":
            # The context ceiling, which a long observation can reach. Named as
            # truncation rather than as bad JSON, because the remedies differ.
            raise SemanticClassificationError(
                "the response hit the context ceiling before completing"
            )

        content = (body.get("message") or {}).get("content", "")
        if not content.strip():
            raise SemanticClassificationError("the response contained no content")

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise SemanticClassificationError(
                f"the response was not valid JSON: {error}"
            ) from error

        return parse_assignments(payload, len(sentences))
