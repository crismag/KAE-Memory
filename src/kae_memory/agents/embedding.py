"""The embedding boundary.

Separate from :class:`~kae_memory.agents.extraction.ExtractionPort`, not a method
on it. Titan is an Amazon model and cannot be invoked by the Anthropic Bedrock
client, so extraction and embedding share a provider *platform*, not a client
(ADR-0008).

The no-live-calls rule carries over unchanged: a deterministic adapter backs the
tests, and nothing in the suite contacts a provider.
"""

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

TITAN_V2_MODEL = "amazon.titan-embed-text-v2:0"
"""The approved embedding model."""

EMBEDDING_DIMENSIONS = 1024
"""1,024 rather than 512.

The corpus is small enough that the storage saving is not worth the semantic
detail, and KAE retrieves closely-related engineering language where finer
distinctions matter (ADR-0008).
"""


class EmbeddingError(Exception):
    """Base class for embedding failures.

    Mirrors the extraction errors: the typed code travels with the exception so a
    provider outcome reaches the run without translation at the call site.
    """

    error_code = "embedding_failed"
    retryable = False


class EmbeddingProviderUnavailableError(EmbeddingError):
    """The provider was unreachable, throttled, or returned a server error."""

    error_code = "embedding_provider_unavailable"
    retryable = True


class EmbeddingTimeoutError(EmbeddingError):
    """The provider did not answer within the bounded timeout."""

    error_code = "embedding_timeout"
    retryable = True


class InvalidEmbeddingError(EmbeddingError):
    """The provider returned a vector of the wrong shape.

    Not retryable by default: a wrong dimension count means the request or the
    model configuration is wrong, and repeating it produces the same answer.
    """

    error_code = "invalid_embedding"
    retryable = False


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Vectors, plus what produced them."""

    vectors: tuple[tuple[float, ...], ...]
    model: str
    dimensions: int


class EmbeddingPort(Protocol):
    """The embedding provider boundary.

    Implementations raise an :class:`EmbeddingError` subclass rather than a
    provider-specific exception.
    """

    def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...


def is_normalised(vector: Sequence[float], tolerance: float = 1e-6) -> bool:
    """Return whether ``vector`` has unit length.

    Cosine distance assumes normalised vectors. Titan is asked to normalise, and
    this checks it actually did rather than trusting the request parameter.
    """

    return abs(math.sqrt(sum(value * value for value in vector)) - 1.0) < tolerance


def _normalise(vector: list[float]) -> tuple[float, ...]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:  # pragma: no cover - degenerate, guarded for safety
        return tuple(vector)
    return tuple(value / magnitude for value in vector)


class DeterministicEmbeddingAdapter:
    """Hash-derived vectors: same text in, same vector out, no network.

    Not a semantic model — it cannot rank meaning. What it *can* do is make the
    surrounding machinery testable: identical text embeds identically, different
    text embeds differently, and vectors are unit length, which is everything the
    persistence, staleness, and query paths depend on.

    Retrieval *quality* is what the evaluation fixture measures, and that is a
    separate question from whether the pipeline works.
    """

    model = "deterministic-embedding"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.call_count = 0

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Return one unit vector per input, derived from its content."""

        self.call_count += 1
        return EmbeddingResult(
            vectors=tuple(self._vector(text) for text in texts),
            model=self.model,
            dimensions=self.dimensions,
        )

    def _vector(self, text: str) -> tuple[float, ...]:
        # Stretch the digest to the required width, so a one-character change
        # moves the whole vector rather than a single component.
        raw: list[float] = []
        counter = 0
        while len(raw) < self.dimensions:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            raw.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1
        return _normalise(raw[: self.dimensions])
