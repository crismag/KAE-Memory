# MVP Scope

**Status:** approved boundary, amended 2026-07-27 to cover bounded agent
execution, workflow durability, semantic retrieval, and demonstration deployment.

## Product hypothesis

Specialised AI agents and their human owners collaborate more consistently on
long-running software engineering work when they share a persistent,
provenance-aware project memory.

## First-release objective

Prove the hypothesis with one real, repeatable discovery workflow that crosses
session boundaries, makes knowledge growth visible, and produces a traceable
output the user keeps.

## In scope

| Capability | Requirement | Meaning |
| --- | --- | --- |
| Project creation | FR-001 | A durable project is created from an incomplete idea and reopened by identifier. |
| Discovery | FR-003, FR-004 | Submitted input is captured verbatim and converted into typed candidate knowledge with provenance. |
| Persistent memory | FR-002, FR-004 | Projects, sessions, messages, and knowledge versions survive process restarts and session boundaries. |
| Knowledge confirmation | FR-005 | A human confirms, rejects, or revises candidates; status is visible. |
| Knowledge correction | FR-006 | Corrections supersede prior versions without erasing them. |
| Cross-session continuity | FR-002, FR-007 | A later session resumes from durable state and explains what changed. |
| Blueprint preview | FR-008 | Confirmed knowledge renders as a reviewable, source-linked Markdown blueprint. |
| Bounded agent execution | FR-009, FR-010 | Three predefined agents — Requirements, Architecture, Review — run behind the workspace, each execution durably recorded. |
| Durable workflow | FR-011, FR-012 | An interrupted run resumes on another worker; submission is idempotent and retry is bounded. |
| Semantic retrieval | FR-013 | Concept search returns related knowledge and evidence with an explanation of why. |
| MCP inspection | FR-014 | CockroachDB MCP for schema, plans, health, and audit. Writes stay in KAE contracts. |
| Review and reporting | FR-015 | Quality findings and operational reports generated from the same data the workspace shows. |
| Demonstration deployment | FR-016, FR-017, FR-018 | Application, worker, and CockroachDB Cloud on AWS with health checks and managed secrets. |

## Out of scope

Not implemented in the MVP, and not to be added without a new approved
requirement and an architecture decision:

- **Authentication** — no login, sessions-as-identity, or credential handling.
  The MVP assumes a single trusted operator.
- **Teams** — no multi-user projects, sharing, roles, or permissions.
- **Billing** — no accounts, plans, metering, or payment.
- **Marketplace** — no plugins, extensions, or third-party integrations.
- **General AI chat** — the interface asks purposeful discovery questions; it is
  not an open-ended assistant.
- **General coding-agent hosting** — no code generation, execution, or
  autonomous delivery. The three authorised agents write knowledge, not code.
- **Arbitrary agent swarms** — no roles beyond the three in FR-009, no dynamic
  role creation, no unrestricted autonomous orchestration.
- **Production-scale RAG** — no hybrid ranking, reranking cascades, or
  cross-project retrieval beyond the single model and index in FR-013.
- **Administration** — no admin console, configuration surface, or user
  management.
- **Advanced analytics** — no usage dashboards, team metrics, or reporting.
- **Production-grade deployment** — no multi-region, autoscaling, SLA, failover
  engineering, or operational hardening beyond the demonstration baseline. AWS
  demonstration deployment is in scope; production operation is not.

Also excluded: automatic merging or deployment of generated code, a universal
cross-domain knowledge graph, and performance optimisation against unverified
scale targets.

## Relationship to deferred requirements

The MVP requirements baseline additionally defers MCP write operations and
document ingestion. Those are product direction that will be revisited after the
core journey works; the exclusions listed above are outside the product's first
release entirely.

The distinction that matters: agent execution, workflow durability, semantic
retrieval, and deployment are **in scope but bounded**. The boundary is the
approval — three fixed roles, one embedding model, one region, one worker.
Exceeding a boundary requires a new requirement, not an implementer's judgement.

## MVP success evidence

A reviewer can inspect a project started in one session, watch one agent's
confirmed output become another agent's input, see a terminated worker's run
resumed and completed by a different worker, observe a correction supersede an
outdated fact while both versions remain visible, and follow the provenance links
that explain why the generated blueprint says what it says.

The full sequence is
[`UNIFIED_DEMO_NARRATIVE.md`](UNIFIED_DEMO_NARRATIVE.md).
