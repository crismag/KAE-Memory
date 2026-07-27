"""Application contracts for KAE-Memory.

All domain writes pass through this layer. Agents never hold raw database
credentials and never issue SQL against domain tables (ADR-0004).
"""

from .memory_service import MemoryService, WriteKnowledgeRequest

__all__ = ["MemoryService", "WriteKnowledgeRequest"]
