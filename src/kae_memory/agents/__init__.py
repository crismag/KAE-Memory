"""Bounded agent execution.

Three roles are authorised (FR-009); two are implemented here. The provider sits
behind :class:`ExtractionPort`, so no module above this package imports a
provider SDK.
"""

from .deterministic import DeterministicExtractionAdapter
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
    "EXTRACTION_SCHEMA",
    "SCHEMA_VERSION",
    "AgentOutcome",
    "ArchitectureAgent",
    "Confidence",
    "DeterministicExtractionAdapter",
    "ExtractedItem",
    "ExtractionError",
    "ExtractionPort",
    "ExtractionRequest",
    "ExtractionResult",
    "InvalidOutputError",
    "OutputTruncatedError",
    "ProviderRefusedError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RequirementsAgent",
    "UnverifiableOutputError",
    "prompt_for",
]
