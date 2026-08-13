"""Embeddings from a model running on this machine (`ADR-0006`).

The offline counterpart to :mod:`kae_memory.agents.titan`. Same port, same
contract, no credential and no network beyond loopback: `nomic-embed-text` under
Ollama on `127.0.0.1:11434`.

## Why this is not a drop-in swap for Titan

Titan returns 1,024 dimensions; `nomic-embed-text` returns 768. Vectors from two
models are not comparable — cosine distance between them is noise — so a
deployment that changed provider over an existing corpus would rank on nonsense
unless every chunk were re-embedded.

This adapter therefore **reports what it produced and coerces nothing**: no
padding to 1,024, no truncation, and no accepting a width it did not ask for.
Padding is the tempting fix and the worst one, because a padded vector indexes
and ranks perfectly happily while meaning nothing. `knowledge_chunks` records
`embedding_model` and `embedding_dimensions` per row so the mixture is
detectable rather than silent (`D-72`).

`httpx` is used directly rather than an Ollama SDK: four fields of one endpoint
do not justify a dependency, and the failure modes worth naming — not running,
model not pulled, timeout — are clearer handled here than translated twice.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import httpx

from .embedding import (
    EmbeddingProviderUnavailableError,
    EmbeddingResult,
    EmbeddingTimeoutError,
    InvalidEmbeddingError,
    is_normalised,
)

OLLAMA_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "nomic-embed-text"

#: What `nomic-embed-text` produces. Declared so a mismatch is a failure with a
#: number in it rather than a vector of unexpected width reaching the database.
NOMIC_DIMENSIONS = 768


class OllamaEmbeddingAdapter:
    """Embeddings from a local Ollama instance."""

    def __init__(
        self,
        base_url: str = OLLAMA_URL,
        model: str = EMBEDDING_MODEL,
        dimensions: int = NOMIC_DIMENSIONS,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed each text, one request per text.

        Ollama's `/api/embeddings` takes a single prompt, so this loops as the
        Titan adapter does. Batching is a different endpoint and is not needed
        for a corpus this size.
        """

        vectors: list[tuple[float, ...]] = []

        for text in texts:
            try:
                response = self._client.post(
                    "/api/embeddings", json={"model": self.model, "prompt": text}
                )
            except httpx.TimeoutException as error:
                raise EmbeddingTimeoutError(
                    f"the local embedding model did not answer within {self._client.timeout.read}s"
                ) from error
            except httpx.HTTPError as error:
                raise EmbeddingProviderUnavailableError(
                    "Ollama is not reachable at "
                    f"{self._client.base_url}. Start it, or configure a different "
                    "embedding provider."
                ) from error

            if response.status_code == 404:
                # Ollama's own words name the model, and the remedy is one
                # command. Reporting "404" instead would send somebody to read
                # about HTTP.
                raise EmbeddingProviderUnavailableError(
                    f"Ollama has no model {self.model!r}. Pull it with: ollama pull {self.model}"
                )
            if response.status_code != 200:
                raise EmbeddingProviderUnavailableError(
                    f"Ollama refused the request: {response.status_code}"
                )

            vector = response.json().get("embedding")
            if not isinstance(vector, list) or not vector:
                raise InvalidEmbeddingError("Ollama returned no embedding")
            if len(vector) != self.dimensions:
                # **Never padded or truncated.** A vector of the wrong width is
                # a different model, and coercing it produces something that
                # indexes and ranks and means nothing (`D-72`).
                raise InvalidEmbeddingError(
                    f"expected {self.dimensions} dimensions from {self.model}, got {len(vector)}"
                )

            values = _normalise(tuple(float(value) for value in vector))
            # Normalised here rather than requested: Ollama offers no such
            # parameter. Asserted afterwards for the Titan adapter's reason —
            # cosine distance is meaningless if it silently did not happen.
            if not is_normalised(values):
                raise InvalidEmbeddingError("a vector could not be normalised to unit length")
            vectors.append(values)

        return EmbeddingResult(vectors=tuple(vectors), model=self.model, dimensions=self.dimensions)

    def close(self) -> None:
        self._client.close()


def _normalise(vector: tuple[float, ...]) -> tuple[float, ...]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        # Every component zero. Normalising would divide by zero, and a unit
        # vector invented from nothing would rank against everything.
        raise InvalidEmbeddingError("the model returned a zero vector")
    return tuple(value / magnitude for value in vector)
