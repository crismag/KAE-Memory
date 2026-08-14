"""Extraction from a model on this machine, and the quote check it must not relax.

The gap that made the offline stack look like it worked and do nothing: a local
interview produced a reply and `default_extractor` returns the **fixture**
adapter unless `KAE_EXTRACTION=bedrock`, so every turn ended with zero
candidates and no error.

The assertion that matters most here is the one about invented quotes. A 14B
model paraphrases far more readily than Claude, so `validate` rejects more —
and that is correct. An extraction that keeps a quote nobody wrote is knowledge
traceable to a sentence that does not exist.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from kae_memory.agents.extraction import (
    ExtractionRequest,
    InvalidOutputError,
    OutputTruncatedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnverifiableOutputError,
)
from kae_memory.agents.ollama_extraction import OllamaExtractionAdapter
from kae_memory.domain.execution import AgentRole

SOURCE = (
    "The receptionist books appointments for four therapists. "
    "Every invoice must carry the client reference assigned at booking."
)


def request(text: str = SOURCE) -> ExtractionRequest:
    return ExtractionRequest(source_text=text, role=AgentRole.DISCOVERY, context=(), max_items=10)


def answering(payload: Any, **body: Any) -> OllamaExtractionAdapter:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:14b",
                "message": {
                    "content": json.dumps(payload) if not isinstance(payload, str) else payload
                },
                "prompt_eval_count": 120,
                "eval_count": 40,
                **body,
            },
        )

    return OllamaExtractionAdapter(transport=httpx.MockTransport(handler))


def item(quote: str, content: str = "Invoices carry the client reference.") -> dict[str, Any]:
    return {
        "kind": "rule",
        "content": content,
        "source_quote": quote,
        "confidence": "high",
    }


class TestWhatItProduces:
    def test_a_quote_from_the_source_survives(self) -> None:
        adapter = answering({"items": [item("Every invoice must carry the client reference")]})

        result = adapter.extract(request())

        assert len(result.items) == 1
        assert result.model == "qwen2.5:14b"
        assert result.usage is not None
        assert result.usage["input_tokens"] == 120

    def test_it_sends_the_prompt_and_the_source(self) -> None:
        sent: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"message": {"content": '{"items": []}'}})

        OllamaExtractionAdapter(transport=httpx.MockTransport(handler)).extract(request())

        messages = sent["messages"]
        assert isinstance(messages, list)
        roles = [m["role"] for m in messages]
        assert roles == ["system", "user"]
        assert SOURCE in messages[1]["content"]
        # A schema, not `"json"`. Ollama constrains generation to it, which is
        # what keeps a 14B model from wrapping its JSON in prose.
        assert isinstance(sent["format"], dict)
        assert sent["stream"] is False

    def test_confirmed_context_is_given_to_the_model(self) -> None:
        sent: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"message": {"content": '{"items": []}'}})

        adapter = OllamaExtractionAdapter(transport=httpx.MockTransport(handler))
        adapter.extract(
            ExtractionRequest(
                source_text=SOURCE,
                role=AgentRole.DISCOVERY,
                context=("The clinic has four therapists.",),
                max_items=10,
            )
        )

        assert "Confirmed context" in sent["messages"][1]["content"]


class TestTheQuoteCheckIsNotRelaxed:
    def test_an_invented_quote_fails_the_whole_extraction(self) -> None:
        """`verify_quotes` fails the **batch**, not the item — deliberately.

        *"Knowledge that misstates its own provenance is worse than knowledge
        that is missing, because the audit trail is the product."* This adapter
        does not soften that, and the first draft of it claimed the opposite:
        that a bad quote merely costs an item. It costs the run.
        """

        adapter = answering({"items": [item("The receptionist handles all billing")]})

        with pytest.raises(UnverifiableOutputError):
            adapter.extract(request())

    def test_one_invented_quote_takes_the_real_ones_with_it(self) -> None:
        """Recorded because it is a **risk of the local model**, not a bug.

        A 14B model paraphrases more than Claude, and one paraphrase discards a
        batch that was otherwise correct. The remedy is a better prompt or a
        larger model, never a looser check — so this asserts the cost rather
        than hiding it.
        """

        adapter = answering(
            {
                "items": [
                    item("four therapists", "The clinic has four therapists."),
                    item("The receptionist handles all billing"),
                ]
            }
        )

        with pytest.raises(UnverifiableOutputError):
            adapter.extract(request())


class TestWhenItCannotWork:
    def test_a_missing_model_says_how_to_pull_it(self) -> None:
        adapter = OllamaExtractionAdapter(
            transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"error": "no"}))
        )

        with pytest.raises(ProviderUnavailableError, match="ollama pull qwen2.5:14b"):
            adapter.extract(request())

    def test_ollama_not_running_names_the_setting_that_changes_it(self) -> None:
        def refuse(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = OllamaExtractionAdapter(transport=httpx.MockTransport(refuse))

        with pytest.raises(ProviderUnavailableError, match="KAE_EXTRACTION"):
            adapter.extract(request())

    def test_a_timeout_is_its_own_failure(self) -> None:
        def stall(_: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        adapter = OllamaExtractionAdapter(transport=httpx.MockTransport(stall))

        with pytest.raises(ProviderTimeoutError):
            adapter.extract(request())

    def test_hitting_the_context_ceiling_is_truncation_not_bad_json(self) -> None:
        """Different remedies: a shorter chunk, or a broken adapter."""

        adapter = answering({"items": []}, done_reason="length")

        with pytest.raises(OutputTruncatedError):
            adapter.extract(request())

    def test_prose_around_the_json_is_an_invalid_output(self) -> None:
        adapter = answering('Here are the items: {"items": []}')

        with pytest.raises(InvalidOutputError):
            adapter.extract(request())

    def test_an_empty_response_is_refused(self) -> None:
        adapter = answering("   ")

        with pytest.raises(InvalidOutputError):
            adapter.extract(request())
