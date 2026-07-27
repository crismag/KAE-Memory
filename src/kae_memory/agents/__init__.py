"""Bounded agent execution.

Three roles are authorised (FR-009); two are implemented here. The provider sits
behind :class:`ExtractionPort`, so no module above this package imports a
provider SDK.
"""

from .deterministic import DeterministicExtractionAdapter
from .embedding import (
    EMBEDDING_DIMENSIONS,
    TITAN_V2_MODEL,
    DeterministicEmbeddingAdapter,
    EmbeddingError,
    EmbeddingPort,
    EmbeddingResult,
    InvalidEmbeddingError,
    is_normalised,
)
from .extraction import (
    EXTRACTION_SCHEMA,
    SCHEMA_VERSION,
    Confidence,
    ExtractedItem,
    ExtractionError,
    ExtractionPort,
    ExtractionRequest,
    ExtractionResult,
    InvalidOutputError,
    OutputTruncatedError,
    ProviderRefusedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnverifiableOutputError,
)
from .prompts import prompt_for
from .roles import AgentOutcome, ArchitectureAgent, RequirementsAgent

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EXTRACTION_SCHEMA",
    "SCHEMA_VERSION",
    "TITAN_V2_MODEL",
    "AgentOutcome",
    "ArchitectureAgent",
    "Confidence",
    "DeterministicEmbeddingAdapter",
    "DeterministicExtractionAdapter",
    "EmbeddingError",
    "EmbeddingPort",
    "EmbeddingResult",
    "ExtractedItem",
    "ExtractionError",
    "ExtractionPort",
    "ExtractionRequest",
    "ExtractionResult",
    "InvalidEmbeddingError",
    "InvalidOutputError",
    "OutputTruncatedError",
    "ProviderRefusedError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RequirementsAgent",
    "UnverifiableOutputError",
    "is_normalised",
    "prompt_for",
]
