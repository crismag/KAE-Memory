# Architecture Workplan

**Status:** partially approved. ADR-0001 to ADR-0003 are accepted; the questions
below are the architecture work that remains. See
[`../00_project/CURRENT_PROJECT_STATE.md`](../00_project/CURRENT_PROJECT_STATE.md)
for which decisions block which milestone.

The architecture must be derived from the approved MVP requirements. This
workplan records the views and decisions required before implementation tasks
can be issued.

## Architecture questions

1. What is the system boundary for KAE-Memory?
2. Which component owns durable project memory?
3. How are immutable evidence, mutable interpretations, and approved decisions
   distinguished?
4. How are provenance, versioning, supersession, and conflicts represented?
5. What constitutes a retrieval request and a context result?
6. Which operations require strong transactional consistency?
7. Which operations may be asynchronous?
8. What does the system do when CockroachDB or an AI provider is unavailable?
9. What sensitive data may enter memory, logs, traces, or embeddings?
10. Which contracts allow orchestration and agent implementations to remain
    replaceable?

## Required architecture outputs

- System context and trust boundaries
- Component model with responsibilities and non-responsibilities
- Behavioural views for write, validate, retrieve, supersede, and conflict flows
- Domain model with one owner per entity
- Interface contracts, inputs, outputs, typed errors, and idempotency rules
- Data architecture and CockroachDB rationale
- Retrieval and optional embedding architecture
- Security and privacy architecture
- Deployment and observability views
- Architecture decision records with alternatives and consequences
- Module contexts suitable for independent task decomposition

## Provisional boundary rule

Until approved architecture exists:

- no service split is approved;
- no framework or language is approved;
- no table or index design is approved;
- no vector database or embedding provider is approved;
- no event bus is approved;
- no public API contract is approved.

CockroachDB is a user-stated technology preference for durable memory. Its exact
role remains a design decision requiring requirements and constraints.
