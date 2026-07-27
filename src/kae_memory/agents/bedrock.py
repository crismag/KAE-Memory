"""Claude on Amazon Bedrock.

The only module that knows a provider exists. Everything above it depends on
:class:`~kae_memory.agents.extraction.ExtractionPort` (ADR-0006).

The SDK is an optional dependency, imported lazily, so the test suite and a
fixture-only demonstration run without it installed.
"""

from typing import Any

from .extraction import (
    EXTRACTION_SCHEMA,
    SCHEMA_VERSION,
    ExtractionRequest,
    ExtractionResult,
    InvalidOutputError,
    OutputTruncatedError,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .prompts import prompt_for
from .validation import validate

DEFAULT_MODEL = "anthropic.claude-opus-5"
"""Bedrock model identifier.

Bedrock model IDs carry an ``anthropic.`` prefix; a bare first-party identifier is
rejected by that endpoint.
"""

DEFAULT_MAX_TOKENS = 16_000
"""Generous by design.

``max_tokens`` caps thinking *and* response text together, so a value sized only
for the expected answer truncates mid-response.
"""


class BedrockExtractionAdapter:
    """Extraction backed by Claude on Amazon Bedrock."""

    def __init__(
        self,
        region: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_seconds: float = 120.0,
        client: Any | None = None,
    ) -> None:
        self._region = region
        self.model = model
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AnthropicBedrockMantle
            except ImportError as error:  # pragma: no cover - depends on extras
                raise ProviderUnavailableError(
                    "the bedrock extra is not installed: uv sync --extra bedrock"
                ) from error
            self._client = AnthropicBedrockMantle(aws_region=self._region)
        return self._client

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract candidates, mapping every provider outcome to a typed error."""

        import json

        version, system_prompt = prompt_for(request.role)
        client = self._ensure_client()

        content = request.source_text
        if request.context:
            joined = "\n\n".join(request.context)
            content = f"Confirmed context:\n{joined}\n\nSource text:\n{request.source_text}"

        try:
            response = client.with_options(timeout=self._timeout).messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        # The stable prefix is cached; the volatile message goes
                        # after it. Caching is a prefix match, so anything that
                        # varies per request must not precede this breakpoint.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
                messages=[{"role": "user", "content": content}],
            )
        except Exception as error:
            raise _as_extraction_error(error) from error

        # Checked before reading content: a refusal is a successful response
        # whose content is empty or partial.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise ProviderRefusedError("the provider declined the extraction request")
        if stop_reason == "max_tokens":
            raise OutputTruncatedError("the response hit the token ceiling before completing")

        text = next(
            (block.text for block in response.content if getattr(block, "type", None) == "text"),
            None,
        )
        if text is None:
            raise InvalidOutputError("the response contained no text block")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise InvalidOutputError(f"the response was not valid JSON: {error}") from error

        items = validate(payload, request.source_text, request.max_items)
        usage = getattr(response, "usage", None)
        return ExtractionResult(
            items=items,
            prompt_version=version,
            schema_version=SCHEMA_VERSION,
            model=getattr(response, "model", self.model),
            usage=_usage_summary(usage),
        )


def _as_extraction_error(error: Exception) -> Exception:
    """Map a provider exception onto the typed extraction errors.

    Matched by class name rather than by import so this works whether or not the
    SDK is installed.
    """

    name = type(error).__name__
    if "Timeout" in name:
        return ProviderTimeoutError(str(error))
    if name in {"RateLimitError", "InternalServerError", "APIConnectionError", "APIStatusError"}:
        return ProviderUnavailableError(str(error))
    if name == "BadRequestError":
        return InvalidOutputError(str(error))
    return ProviderUnavailableError(str(error))


def _usage_summary(usage: Any) -> dict[str, Any] | None:
    """Return a bounded token summary.

    Bounded on purpose: ``agent_runs`` records structured state, never prompts or
    raw provider responses (ADR-0005).
    """

    if usage is None:
        return None
    return {
        field: getattr(usage, field, None)
        for field in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        if getattr(usage, field, None) is not None
    }
