# Implementation Roadmap

**Status:** superseded as a sequencing plan, retained for its epic definitions.

The authoritative sequence is the M0–M10 milestone register in
[`../docs/00_project/CURRENT_PROJECT_STATE.md`](../docs/00_project/CURRENT_PROJECT_STATE.md)
and [`../docs/09_development/DEVELOPMENT_PLAN.md`](../docs/09_development/DEVELOPMENT_PLAN.md).
Epics 1 to 3 below are complete.

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

Epics 1 to 3 are complete: requirements are approved, domain contracts and the knowledge persistence foundation are implemented, and ADR-0001 to ADR-0003 are accepted. The current gate is M4 repository realignment, followed by RA-01 to restore the quality gate. Epic 4 continues as milestones M6 and M7.
