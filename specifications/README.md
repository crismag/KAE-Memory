# Engineering Specifications

This directory defines what KAE-Memory must become before implementation-specific scaffolding is approved.

## Status model

- **Established** — directly supported by approved project context.
- **Proposed** — derived design or requirement awaiting review.
- **Open** — unresolved and must not be silently decided by an implementation agent.

## Specifications

1. [Product Requirements Specification](PRODUCT_REQUIREMENTS_SPECIFICATION.md)
2. [Domain Model](DOMAIN_MODEL.md)
3. [Memory Architecture](MEMORY_ARCHITECTURE.md)
4. [Retrieval Architecture](RETRIEVAL_ARCHITECTURE.md)
5. [Agent Collaboration](AGENT_COLLABORATION.md)
6. [API Contracts](API_CONTRACTS.md)
7. [Database Architecture](DATABASE_ARCHITECTURE.md)
8. [Verification Gates](VERIFICATION_GATES.md)
9. [Findings and action register](FINDINGS_REGISTER.md)
10. [Documentation plan](documentation-plan/) — Phase 2A planning artifacts, not documentation
11. [ADR-0001: Memory-first foundation](ADR/ADR-0001-memory-first.md)

## Use by coding agents

These files are not a universal implementation prompt. A coding agent must receive one bounded task context that cites only the approved parts relevant to that task.
