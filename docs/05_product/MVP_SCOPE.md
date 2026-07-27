# MVP Scope

**Status:** approved boundary, 2026-07-27.

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
- **Full coding agent runtime** — no orchestration, code generation, execution,
  or autonomous delivery.
- **Administration** — no admin console, configuration surface, or user
  management.
- **Advanced analytics** — no usage dashboards, team metrics, or reporting.
- **Production deployment** — no multi-region, scaling, SLA, or operational
  hardening beyond what the demonstration requires.

Also excluded: automatic merging or deployment of generated code, a universal
cross-domain knowledge graph, and performance optimisation against unverified
scale targets.

## Relationship to deferred requirements

The MVP requirements baseline additionally defers multi-agent runtime, MCP write
operations, advanced retrieval, and document ingestion. Those are product
direction that will be revisited after the core journey works; the exclusions
listed above are outside the product's first release entirely.

## MVP success evidence

A reviewer can inspect a project started in one session, observe a later session
retrieve and apply the knowledge confirmed in the first, watch a correction
supersede an outdated fact while both versions remain visible, and follow the
provenance links that explain why the generated blueprint says what it says.
