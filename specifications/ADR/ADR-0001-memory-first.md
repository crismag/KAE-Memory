# ADR-0001: Build the persistent-memory foundation first

- **Status:** proposed
- **Date:** 2026-07-26

## Context

The broader product vision includes agent orchestration, implementation, testing, review, documentation, user interfaces, and increasing autonomy. The central unresolved risk is whether specialised agents can collaborate effectively through durable shared engineering memory without creating stale, conflicting, or untrusted knowledge.

## Decision

Build and validate the persistent engineering-memory foundation before broad orchestration, user-interface, plugin, or autonomous-delivery capabilities.

The first release will centre on durable project identity, provenance, lifecycle state, versioning, traceability, retrieval, human validation, conflict visibility, context assembly, and a cross-session two-agent proof workflow.

## Rationale

Memory quality is the dependency that distinguishes KAE-Memory from an ordinary agent runner or chat wrapper. Building surrounding platform capabilities first would increase scope without testing the primary product hypothesis.

## Consequences

### Positive

- The MVP tests the highest-risk assumption directly.
- Later agents and workflows can depend on explicit memory contracts.
- Requirements and architecture remain traceable.
- The implementation can evolve in vertical slices.

### Negative

- Early releases may have little or no production UI.
- Some orchestration features will remain manual.
- The team must invest in provenance, lifecycle, and retrieval evaluation before visible automation breadth.

## Deferred alternatives

- Orchestration-first platform
- UI-first product prototype
- Chat-history persistence as memory
- Autonomous code-delivery MVP

## Review trigger

Revisit this decision if the proof workflow shows that persistent structured memory does not materially improve cross-session collaboration quality or if a simpler architecture meets the approved requirements.
