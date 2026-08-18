"""Reviewing recorded knowledge with a model on this machine (`ADR-0006`).

The last hosted-only step in the loop. Embedding went local with
`OllamaEmbeddingAdapter`, extraction with `OllamaExtractionAdapter`, observation
classification with `OllamaObservationClassifier` — and review did not, so an
offline deployment classified with `DeterministicReviewAdapter`, which assigns an
area only where a knowledge kind is accepted by exactly one area. Two of eight
kinds are. Readiness counts statements per area, so a project whose knowledge was
read perfectly still reported nine of ten areas `missing`.

## A second transport, not a second reviewer (`D-122`, `D-266`)

Everything that decides what a finding *means* is imported: the prompt from
:func:`prompt_for`, ``REVIEW_SCHEMA``, :func:`resolve`, and the typed errors.
This module supplies the HTTP call and the user message. Writing a second prompt
here would be writing a second definition of :class:`ReviewFindingKind`, and the
two would part company at the first change to it.

The user message is copied from :class:`~kae_memory.agents.bedrock.BedrockReviewAdapter`
rather than left to the system prompt, for the reason that adapter's own comment
gives: its first version sent bare lists and the model returned zero findings for
three obviously classifiable statements.

## It does not degrade inside itself (`D-266`)

`OllamaObservationClassifier` falls back to rules on any provider failure because
nothing above it can. This has a caller that already does it better:
``ReviewStep._propose`` catches the failure per batch, places what
``classify_offline_by_content`` can, records the error code, and downgrades the
engine word a person reads. An adapter that swallowed the failure while carrying
``judges = True`` would report `reviewed_by_model` about output no model
produced, which is `AUD-039` rebuilt.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from kae_memory.domain.execution import AgentRole

from .extraction import (
    InvalidOutputError,
    OutputTruncatedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .ollama_extraction import OLLAMA_URL
from .prompts import prompt_for
from .review import (
    REVIEW_SCHEMA,
    SCHEMA_VERSION,
    ReviewRequest,
    ReviewResult,
    resolve,
)

DEFAULT_MODEL = "qwen2.5:14b"
"""The same general model extraction and classification use. Deciding whether a
requirement is about scope or about quality attributes is reading comprehension."""

DEFAULT_TIMEOUT = 300.0
"""Extraction's, not the classifier's. A review request carries forty statements
and ten area names and asks for a finding per statement, so it is the larger of
the two prompts and the longer of the two answers."""


class OllamaReviewAdapter:
    """Review backed by a model on this machine."""

    #: It judges. `review.judges()` defaults to `False` so that an adapter which
    #: forgets this under-claims, and a 14B model placing a statement among ten
    #: named areas is doing the discrimination the deterministic adapter refuses
    #: to guess at (`D-266`).
    judges = True

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    def review(self, request: ReviewRequest) -> ReviewResult:
        """Review the statements, mapping every provider outcome to a typed error."""

        version, system_prompt = prompt_for(AgentRole.REVIEW)
        areas = "\n".join(f"- {key}" for key in request.area_keys)
        statements = "\n".join(f"- {s.text}" for s in request.statements)
        content = (
            f"Discovery areas available:\n{areas}\n\n"
            f"Statements to review:\n{statements}\n\n"
            f"Classify each statement above into one of the areas, using an "
            f"`area_classification` finding whose `statement_quote` repeats the "
            f"statement verbatim. Leave out any statement that belongs to none "
            f"of these areas. Then report any contradictions or unsupported "
            f"claims you found."
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
                        # A schema, not `"json"` — the local equivalent of
                        # Bedrock's `json_schema` output config, and the reason a
                        # 14B model stops wrapping its JSON in prose.
                        "format": REVIEW_SCHEMA,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": content},
                        ],
                    },
                )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(
                f"the local reviewer did not answer within {self._timeout:.0f}s"
            ) from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(
                f"Ollama is not reachable at {self._base_url}: {type(error).__name__}. "
                "Start it, or set KAE_REVIEW to a provider this deployment has."
            ) from error

        if response.status_code == 404:
            raise ProviderUnavailableError(
                f"Ollama has no model {self.model!r}. Pull it with: ollama pull {self.model}"
            )
        if response.status_code != 200:
            raise ProviderUnavailableError(f"Ollama refused the request: {response.status_code}")

        body = response.json()

        # A batch of forty statements reaches the context ceiling before a
        # document does. Named as truncation because the remedy is
        # `KAE_REVIEW_BATCH`, not a repaired adapter.
        if body.get("done_reason") == "length":
            raise OutputTruncatedError("the response hit the context ceiling before completing")

        text = (body.get("message") or {}).get("content", "")
        if not text.strip():
            raise InvalidOutputError("the response contained no content")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise InvalidOutputError(f"the response was not valid JSON: {error}") from error

        # Resolved rather than trusted, exactly as the hosted reviewer is: every
        # quote must match a statement that was actually sent, so a reviewer
        # cannot classify something it invented.
        findings = resolve(payload, request)
        return ReviewResult(
            findings=findings,
            prompt_version=version,
            schema_version=SCHEMA_VERSION,
            model=str(body.get("model") or self.model),
            usage=_usage(body),
        )


def _usage(body: dict[str, Any]) -> dict[str, int]:
    """Token counts, in the shape the run record already stores."""

    return {
        "input_tokens": int(body.get("prompt_eval_count") or 0),
        "output_tokens": int(body.get("eval_count") or 0),
    }


__all__ = ["OLLAMA_URL", "OllamaReviewAdapter"]
