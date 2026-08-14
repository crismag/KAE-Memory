"""Extraction from a model on this machine.

The gap that made the offline stack look like it worked and do nothing. A local
interview produced a reply, and `default_extractor` returns the **fixture**
adapter unless `KAE_EXTRACTION=bedrock` — so every turn ended with zero
candidates and no error. Nothing failed; nothing happened.

Mirrors :class:`~kae_memory.agents.bedrock.BedrockExtractionAdapter`
deliberately: the same prompt from :func:`prompt_for`, the same
``EXTRACTION_SCHEMA``, the same :func:`validate`, and the same typed errors. Two
providers that behave differently under failure are two things to learn rather
than one.

## What is different, and why it matters more here

`verify_quotes` fails the **whole batch** when any item cites a quote absent
from the source — *"knowledge that misstates its own provenance is worse than
knowledge that is missing, because the audit trail is the product."*

A 14B model paraphrases far more readily than Claude does, so one paraphrase
discards an extraction that was otherwise correct. **That is a real cost of the
local model and it is not softened here.** The remedy, when it bites, is a
better prompt or a larger model — never a looser check.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .extraction import (
    EXTRACTION_SCHEMA,
    SCHEMA_VERSION,
    ExtractionRequest,
    ExtractionResult,
    InvalidOutputError,
    OutputTruncatedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .prompts import prompt_for
from .validation import validate

OLLAMA_URL = "http://127.0.0.1:11434"

#: §13 names this the general model. Extraction is reading comprehension rather
#: than code generation, so the general model is the right one of the four.
DEFAULT_MODEL = "qwen2.5:14b"

#: A local model on a cold GPU takes tens of seconds before its first token, and
#: extraction runs on a worker rather than in front of a person. Generous on
#: purpose: a timeout here is reported as a provider failure and costs a retry.
DEFAULT_TIMEOUT = 300.0


class OllamaExtractionAdapter:
    """Extraction from a local Ollama instance."""

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._timeout = timeout_seconds
        self._transport = transport
        self._base_url = base_url.rstrip("/")

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract candidates, mapping every provider outcome to a typed error."""

        version, system_prompt = prompt_for(request.role)

        content = request.source_text
        if request.context:
            joined = "\n\n".join(request.context)
            content = f"Confirmed context:\n{joined}\n\nSource text:\n{request.source_text}"

        try:
            with httpx.Client(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = client.post(
                    "/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        # A schema, not `"json"`. Ollama constrains generation to
                        # it, which is the local equivalent of Bedrock's
                        # `json_schema` output config — and without it a 14B
                        # model returns prose around its JSON often enough to
                        # matter.
                        "format": EXTRACTION_SCHEMA,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": content},
                        ],
                    },
                )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(
                f"the local extractor did not answer within {self._timeout:.0f}s"
            ) from error
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(
                f"Ollama is not reachable at {self._base_url}: {type(error).__name__}. "
                "Start it, or set KAE_EXTRACTION to a provider this deployment has."
            ) from error

        if response.status_code == 404:
            raise ProviderUnavailableError(
                f"Ollama has no model {self.model!r}. Pull it with: ollama pull {self.model}"
            )
        if response.status_code != 200:
            raise ProviderUnavailableError(f"Ollama refused the request: {response.status_code}")

        body = response.json()

        # A local model hits its context ceiling on a long document, and Ollama
        # says so in `done_reason`. Reported as truncation rather than as bad
        # JSON, because the remedies differ: one is a shorter chunk, the other
        # is a broken adapter.
        if body.get("done_reason") == "length":
            raise OutputTruncatedError("the response hit the context ceiling before completing")

        text = (body.get("message") or {}).get("content", "")
        if not text.strip():
            raise InvalidOutputError("the response contained no content")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise InvalidOutputError(f"the response was not valid JSON: {error}") from error

        # The same validation as every other provider, and it fails the whole
        # batch on one invented quote. A local model paraphrases more, so this
        # will fire more often here; the answer is a better prompt, not a
        # weaker check.
        items = validate(payload, request.source_text, request.max_items)

        return ExtractionResult(
            items=items,
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
