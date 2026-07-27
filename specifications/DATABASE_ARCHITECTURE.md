# Database Architecture

**Status:** logical design. The physical schema for the M5 proof is approved in
[`ADR/ADR-0005-m5-physical-schema.md`](ADR/ADR-0005-m5-physical-schema.md) and
**implemented** as revisions `0001` and `0002`. Everything beyond that scope
remains logical only — vector storage in particular is M8 and an additive later
revision.

## Role of CockroachDB

CockroachDB is the preferred durable persistence foundation for project memory, provenance, lifecycle state, traceability, executions, and transactional updates. This preference must still be validated against consistency, scale, deployment, cost, and operational requirements.

## Logical data groups

- Project and policy metadata
- Agent registry and capabilities
- Knowledge items and versions
- Specialised requirement and decision metadata
- Typed relationships and trace links
- Execution history
- Context bundle manifests
- Snapshots and release boundaries
- Audit and state-transition records

## Transaction boundaries

Candidate transactions include project creation, knowledge submission with provenance, validation state transition, supersession, relationship creation, and execution completion with outputs. Exact aggregate boundaries remain open.

## Consistency expectations

Strong consistency is likely required for version changes, lifecycle transitions, validation, supersession, permissions, and trace-link creation. Semantic indexing and derived summaries may be asynchronous if the retrieval contract clearly exposes freshness.

## Storage separation

Large artefacts may require object storage with durable references and integrity metadata. Embeddings are derived data and must remain traceable to source item and model version. Neither object storage nor vector-index implementation is selected.

## CockroachDB design questions

- Primary and locality keys
- Transaction contention and retry handling
- Multi-region requirements
- Secondary and inverted indexes
- JSON usage versus normalised structures
- Changefeeds or outbox pattern
- Schema migration strategy
- Backup, restore, and point-in-time recovery
- Tenant isolation
- Retention and deletion

## Prohibited assumption

A table list is not an approved domain model. Physical design must follow accepted entities, invariants, access patterns, and non-functional requirements.
