"""Embeddings from a model on this machine, and the coercions it refuses.

`ADR-0006` makes local execution canonical and `D-72` found that **no chunk in
the production corpus has ever been embedded** — 2030 rows, all `pending`. So
this adapter is not swapping one provider for another; it is the first one that
will actually write a vector.

Most of these are about what it will not do. Titan returns 1,024 dimensions and
`nomic-embed-text` returns 768, and the tempting fix — pad, or truncate — yields
a vector that indexes and ranks perfectly happily and means nothing.

The live test at the end runs against a real Ollama when one is there, and skips
with its reason when it is not. A mocked transport proves our end of the
protocol; only the real model proves the model.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from kae_memory.agents.embedding import (
    EmbeddingProviderUnavailableError,
    EmbeddingTimeoutError,
    InvalidEmbeddingError,
    is_normalised,
)
from kae_memory.agents.ollama import NOMIC_DIMENSIONS, OllamaEmbeddingAdapter


def responding(handler: Any) -> OllamaEmbeddingAdapter:
    return OllamaEmbeddingAdapter(transport=httpx.MockTransport(handler))


def vector_of(width: int, value: float = 0.5) -> list[float]:
    return [value] * width


class TestWhatItProduces:
    def test_a_vector_comes_back_normalised(self) -> None:
        """Ollama offers no `normalize` parameter, so this adapter does it.

        Asserted rather than assumed, for the Titan adapter's stated reason:
        cosine distance is meaningless if normalisation silently did not happen.
        """

        adapter = responding(
            lambda request: httpx.Response(200, json={"embedding": vector_of(NOMIC_DIMENSIONS)})
        )

        result = adapter.embed(["a booking system for a clinic"])

        assert result.dimensions == NOMIC_DIMENSIONS
        assert result.model == "nomic-embed-text"
        assert is_normalised(result.vectors[0])

    def test_each_text_is_embedded(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"embedding": vector_of(NOMIC_DIMENSIONS)})

        result = responding(handler).embed(["first", "second", "third"])

        assert seen == ["first", "second", "third"]
        assert len(result.vectors) == 3

    def test_it_reports_the_model_that_produced_them(self) -> None:
        """`knowledge_chunks` stores this per row, which is what makes a mixed
        corpus detectable instead of silent."""

        adapter = OllamaEmbeddingAdapter(
            model="some-other-model",
            dimensions=4,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"embedding": vector_of(4)})
            ),
        )

        assert adapter.embed(["x"]).model == "some-other-model"


class TestWhatItRefuses:
    """Each of these is a way a meaningless vector reaches the database."""

    def test_a_vector_of_the_wrong_width_is_refused_not_padded(self) -> None:
        """The whole of `D-72`.

        Titan's 1,024 and nomic's 768 are different models, and a padded vector
        ranks against everything while meaning nothing. The failure names both
        numbers because *"expected 768, got 1024"* identifies the mistake and
        *"invalid embedding"* does not.
        """

        adapter = responding(
            lambda request: httpx.Response(200, json={"embedding": vector_of(1024)})
        )

        with pytest.raises(InvalidEmbeddingError) as raised:
            adapter.embed(["x"])

        assert "768" in str(raised.value) and "1024" in str(raised.value)

    def test_a_zero_vector_is_refused(self) -> None:
        """Normalising it divides by zero; inventing a unit vector from nothing
        would rank against every query in the corpus.

        **Defended twice, and no single mutation isolates it.** Removing the
        zero check leaves `is_normalised` to reject the result, and removing
        normalisation leaves it too. Kept as defence in depth with the
        redundancy stated, rather than contriving a mutation to justify it
        (`D-43`'s precedent).
        """

        adapter = responding(
            lambda request: httpx.Response(
                200, json={"embedding": vector_of(NOMIC_DIMENSIONS, 0.0)}
            )
        )

        with pytest.raises(InvalidEmbeddingError):
            adapter.embed(["x"])

    def test_an_empty_response_is_refused(self) -> None:
        adapter = responding(lambda request: httpx.Response(200, json={}))

        with pytest.raises(InvalidEmbeddingError):
            adapter.embed(["x"])


class TestWhenItCannotWork:
    def test_a_missing_model_says_how_to_pull_it(self) -> None:
        """Ollama answers `404` for a model it does not have, and the remedy is
        one command. Reporting the status code sends somebody to read about
        HTTP."""

        adapter = responding(lambda request: httpx.Response(404, json={"error": "not found"}))

        with pytest.raises(EmbeddingProviderUnavailableError) as raised:
            adapter.embed(["x"])

        assert "ollama pull nomic-embed-text" in str(raised.value)

    def test_ollama_not_running_says_so_and_where(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        with pytest.raises(EmbeddingProviderUnavailableError) as raised:
            responding(refuse).embed(["x"])

        assert "not reachable" in str(raised.value)

    def test_a_timeout_is_its_own_failure(self) -> None:
        """A local model on a cold GPU is slow, which is not the same as absent
        — and the two have different remedies."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        with pytest.raises(EmbeddingTimeoutError):
            responding(stall).embed(["x"])


@pytest.mark.skipif(
    not __import__("os").environ.get("KAE_OLLAMA_LIVE"),
    reason="set KAE_OLLAMA_LIVE=1 to run against the Ollama on this machine",
)
def test_the_real_model_returns_something_that_ranks() -> None:
    """A mocked transport proves our end of the protocol. Only the model proves
    the model — that near things are near and unrelated things are not."""

    adapter = OllamaEmbeddingAdapter()
    result = adapter.embed(
        [
            "a booking system for a physiotherapy clinic",
            "scheduling appointments for a small medical practice",
            "a compiler for a statically typed language",
        ]
    )

    def similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    close = similarity(result.vectors[0], result.vectors[1])
    far = similarity(result.vectors[0], result.vectors[2])

    assert result.dimensions == NOMIC_DIMENSIONS
    assert close > far, f"related text scored {close}, unrelated {far}"
