"""Amazon Titan Text Embeddings V2 on Bedrock.

The only module that knows an embedding provider exists. It uses ``boto3``
against ``bedrock-runtime``, not the Anthropic SDK: Titan is an Amazon model and
the Anthropic Bedrock client cannot invoke it (ADR-0008).

``boto3`` is an optional dependency, imported lazily, so the suite and a
fixture-only demonstration run without it installed.
"""

import json
from collections.abc import Sequence
from typing import Any

from .embedding import (
    EMBEDDING_DIMENSIONS,
    TITAN_V2_MODEL,
    EmbeddingProviderUnavailableError,
    EmbeddingResult,
    EmbeddingTimeoutError,
    InvalidEmbeddingError,
    is_normalised,
)


class TitanEmbeddingAdapter:
    """Embeddings from Titan Text Embeddings V2."""

    def __init__(
        self,
        region: str,
        model: str = TITAN_V2_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
        client: Any | None = None,
    ) -> None:
        self._region = region
        self.model = model
        self.dimensions = dimensions
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                import boto3
            except ImportError as error:  # pragma: no cover - depends on extras
                raise EmbeddingProviderUnavailableError(
                    "the bedrock extra is not installed: uv sync --extra bedrock"
                ) from error
            self._client = boto3.client("bedrock-runtime", region_name=self._region)
        return self._client

    def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed each text, one request per text.

        Titan's text-embedding endpoint takes a single input per call, so this
        loops rather than batching. Batching would need a different endpoint and
        is not part of the approved scope.
        """

        client = self._ensure_client()
        vectors: list[tuple[float, ...]] = []

        for text in texts:
            body = json.dumps(
                {
                    "inputText": text,
                    "dimensions": self.dimensions,
                    "normalize": True,
                    "embeddingTypes": ["float"],
                }
            )
            try:
                response = client.invoke_model(modelId=self.model, body=body)
                payload = json.loads(response["body"].read())
            except Exception as error:
                raise _as_embedding_error(error) from error

            vector = payload.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise InvalidEmbeddingError(
                    f"expected {self.dimensions} dimensions, got "
                    f"{len(vector) if isinstance(vector, list) else type(vector).__name__}"
                )
            values = tuple(float(value) for value in vector)
            # Normalisation was requested; verified rather than assumed, because
            # cosine distance is meaningless if it silently did not happen.
            if not is_normalised(values):
                raise InvalidEmbeddingError("provider returned a vector that is not unit length")
            vectors.append(values)

        return EmbeddingResult(vectors=tuple(vectors), model=self.model, dimensions=self.dimensions)


def _as_embedding_error(error: Exception) -> Exception:
    """Map a provider exception onto the typed embedding errors.

    Matched by class name so this works whether or not boto3 is installed.
    """

    name = type(error).__name__
    if "Timeout" in name or "ConnectTimeout" in name:
        return EmbeddingTimeoutError(str(error))
    if name in {"ThrottlingException", "ServiceUnavailableException", "EndpointConnectionError"}:
        return EmbeddingProviderUnavailableError(str(error))
    if name == "ValidationException":
        return InvalidEmbeddingError(str(error))
    return EmbeddingProviderUnavailableError(str(error))
