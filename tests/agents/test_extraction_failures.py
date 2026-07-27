"""Validation and provider-failure mapping.

Every provider outcome must reach the run as a typed code. Nothing here contacts
a provider: the Bedrock adapter is exercised with an injected fake client.
"""

from typing import Any

import pytest

from kae_memory.agents import (
    Confidence,
    InvalidOutputError,
    OutputTruncatedError,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnverifiableOutputError,
)
from kae_memory.agents.bedrock import DEFAULT_MODEL, BedrockExtractionAdapter
from kae_memory.agents.extraction import ExtractionRequest
from kae_memory.agents.validation import validate
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind

SOURCE = "Coordinators file reports monthly, and the cycle should be configurable."


def _item(**overrides: Any) -> dict[str, Any]:
    base = {
        "kind": "rule",
        "content": "The cycle is configurable.",
        "confidence": "high",
        "source_quote": "the cycle should be configurable",
    }
    base.update(overrides)
    return base


def _request() -> ExtractionRequest:
    return ExtractionRequest(role=AgentRole.REQUIREMENTS, source_text=SOURCE)


class TestValidation:
    def test_accepts_a_well_formed_payload(self) -> None:
        items = validate({"items": [_item()]}, SOURCE, max_items=10)

        assert items[0].kind is KnowledgeKind.RULE
        assert items[0].confidence is Confidence.HIGH

    def test_quote_matching_tolerates_rewrapped_whitespace(self) -> None:
        """A reflowed quote is still a faithful quote."""

        items = validate(
            {"items": [_item(source_quote="the   cycle\n should be  configurable")]},
            SOURCE,
            max_items=10,
        )

        assert len(items) == 1

    def test_rejects_a_fabricated_quote(self) -> None:
        with pytest.raises(UnverifiableOutputError, match="does not occur"):
            validate({"items": [_item(source_quote="the cycle is fixed at 30 days")]}, SOURCE, 10)

    def test_rejects_an_unknown_kind(self) -> None:
        with pytest.raises(InvalidOutputError):
            validate({"items": [_item(kind="epic")]}, SOURCE, max_items=10)

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(InvalidOutputError, match="empty content"):
            validate({"items": [_item(content="   ")]}, SOURCE, max_items=10)

    def test_rejects_more_items_than_the_ceiling(self) -> None:
        with pytest.raises(InvalidOutputError, match="ceiling"):
            validate({"items": [_item(), _item()]}, SOURCE, max_items=1)

    @pytest.mark.parametrize("payload", [{}, {"items": "not a list"}, [1, 2]])
    def test_rejects_malformed_payloads(self, payload: Any) -> None:
        with pytest.raises(InvalidOutputError):
            validate(payload, SOURCE, max_items=10)


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str = "{}", stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.stop_reason = stop_reason
        self.model = DEFAULT_MODEL
        self.usage = None


class _FakeMessages:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


class _FakeClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.messages = _FakeMessages(response, error)

    def with_options(self, **_: Any) -> "_FakeClient":
        return self


class TestBedrockAdapter:
    def test_sends_the_schema_and_a_cached_system_prefix(self) -> None:
        item = (
            '{"kind": "rule", "content": "The cycle is configurable.", '
            '"confidence": "high", "source_quote": "the cycle should be configurable"}'
        )
        client = _FakeClient(_Response(f'{{"items": [{item}]}}'))
        adapter = BedrockExtractionAdapter(region="eu-west-1", client=client)

        result = adapter.extract(_request())

        assert len(result.items) == 1
        assert result.prompt_version == "requirements.v1"
        call = client.messages.calls[0]
        assert call["model"].startswith("anthropic."), "Bedrock IDs carry the anthropic. prefix"
        assert call["output_config"]["format"]["type"] == "json_schema"
        assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
        # Sampling parameters are rejected by the current models.
        assert not {"temperature", "top_p", "top_k"} & set(call)

    def test_refusal_is_detected_from_the_stop_reason(self) -> None:
        """A refusal is a successful response with empty or partial content."""

        client = _FakeClient(_Response(text="", stop_reason="refusal"))
        adapter = BedrockExtractionAdapter(region="eu-west-1", client=client)

        with pytest.raises(ProviderRefusedError):
            adapter.extract(_request())

    def test_truncation_is_detected_from_the_stop_reason(self) -> None:
        client = _FakeClient(_Response(text='{"items": [', stop_reason="max_tokens"))
        adapter = BedrockExtractionAdapter(region="eu-west-1", client=client)

        with pytest.raises(OutputTruncatedError):
            adapter.extract(_request())

    def test_non_json_output_is_invalid(self) -> None:
        client = _FakeClient(_Response(text="Here are the requirements:"))
        adapter = BedrockExtractionAdapter(region="eu-west-1", client=client)

        with pytest.raises(InvalidOutputError):
            adapter.extract(_request())

    @pytest.mark.parametrize(
        ("exception_name", "expected"),
        [
            ("APITimeoutError", ProviderTimeoutError),
            ("RateLimitError", ProviderUnavailableError),
            ("InternalServerError", ProviderUnavailableError),
            ("APIConnectionError", ProviderUnavailableError),
            ("BadRequestError", InvalidOutputError),
        ],
    )
    def test_provider_exceptions_map_to_typed_errors(
        self, exception_name: str, expected: type[Exception]
    ) -> None:
        error = type(exception_name, (Exception,), {})("boom")
        adapter = BedrockExtractionAdapter(region="eu-west-1", client=_FakeClient(error=error))

        with pytest.raises(expected):
            adapter.extract(_request())


def test_error_codes_match_the_agent_execution_model() -> None:
    """The codes recorded on a run are the ones the specification names."""

    assert ProviderUnavailableError.error_code == "provider_unavailable"
    assert ProviderTimeoutError.error_code == "provider_timeout"
    assert ProviderRefusedError.error_code == "provider_refused"
    assert OutputTruncatedError.error_code == "output_truncated"
    assert InvalidOutputError.error_code == "invalid_output"
    assert UnverifiableOutputError.error_code == "unverifiable_output"
    assert UnverifiableOutputError.retryable is False
    assert ProviderUnavailableError.retryable is True
