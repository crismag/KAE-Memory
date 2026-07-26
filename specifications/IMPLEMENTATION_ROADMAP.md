# Implementation Roadmap

**Status:** proposed dependency order.

## Epic 1 — Requirements and proof definition

Approve the MVP workflow, actors, permissions, lifecycle rules, failure behaviour, security boundaries, measurable non-functional requirements, and acceptance tests.

## Epic 2 — Domain and contract foundation

Approve domain entities, invariants, ownership boundaries, state transitions, API contracts, error model, and architecture decisions.

## Epic 3 — Repository bootstrap

Select language, framework, package management, test tooling, CI, configuration, migration tooling, and module layout. Record each significant choice in an ADR.

## Epic 4 — Persistent memory vertical slice

Implement project identity, agent identity, knowledge submission, provenance, versioning, lifecycle state, persistence, and tests as one end-to-end slice.

## Epic 5 — Traceability and retrieval

Implement typed relationships, structural retrieval, history, current-state queries, conflict visibility, and bounded ContextBundle generation.

## Epic 6 — Human validation

Implement validate, reject, correct, and supersede workflows with audit history and concurrency handling.

## Epic 7 — Multi-agent proof

Run a requirements agent in one session and an architecture agent in another. Demonstrate retrieval and reuse of validated requirements, traceable architecture output, conflict correction, and reproducible context.

## Epic 8 — Operational hardening

Add the observability, security, backup, recovery, performance, deployment, and documentation work required by approved non-functional requirements.

## Task issuance rule

Every implementation task must identify its objective, requirement and architecture links, inputs, outputs, allowed file scope, prohibited changes, acceptance criteria, required tests, dependencies, and unresolved issues.

## Current next gate

Review and approve the proposed product requirements and domain/memory principles. Application scaffolding remains blocked until implementation technology and module decisions are accepted.
