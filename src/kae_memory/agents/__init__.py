"""Bounded agent execution.

All three authorised roles (FR-009) are implemented here. Providers sit behind
:class:`ExtractionPort` and :class:`ReviewPort`, so no module above this package
imports a provider SDK.
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
from .review import (
    InvalidReviewOutputError,
    ReviewedStatement,
    ReviewError,
    ReviewFinding,
    ReviewFindingKind,
    ReviewPort,
    ReviewRequest,
    ReviewResult,
    UnverifiableReviewError,
    judges,
)
from .review_adapter import DeterministicReviewAdapter, offline_review_fixture
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
    "DeterministicReviewAdapter",
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
    "InvalidReviewOutputError",
    "OutputTruncatedError",
    "ProviderRefusedError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RequirementsAgent",
    "ReviewError",
    "ReviewFinding",
    "ReviewFindingKind",
    "ReviewPort",
    "ReviewRequest",
    "ReviewResult",
    "ReviewedStatement",
    "UnverifiableOutputError",
    "UnverifiableReviewError",
    "is_normalised",
    "judges",
    "offline_review_fixture",
    "prompt_for",
]
