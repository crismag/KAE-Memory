"""Application contracts for KAE-Memory.

All domain writes pass through this layer. Agents never hold raw database
credentials and never issue SQL against domain tables (ADR-0004).
"""

from .memory_service import MemoryService, WriteKnowledgeRequest
from .readiness_service import ReadinessService
from .retrieval_service import RetrievalService, SearchHit
from .review_service import Finding, FindingKind, ReviewService, Severity

__all__ = [
    "Finding",
    "FindingKind",
    "MemoryService",
    "ReadinessService",
    "RetrievalService",
    "ReviewService",
    "SearchHit",
    "Severity",
    "WriteKnowledgeRequest",
]
