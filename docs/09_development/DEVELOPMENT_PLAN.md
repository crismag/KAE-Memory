# Development Plan

## Objective

Take KAE-Memory from an implemented memory foundation to a demonstrable
product slice that proves persistent engineering memory, without allowing coding
agents to invent product or architecture decisions.

## Delivery strategy

Build vertical, independently verifiable slices. Each milestone below maps to a
status entry in [`../00_project/CURRENT_PROJECT_STATE.md`](../00_project/CURRENT_PROJECT_STATE.md)
and to a slice in [`CODEX_CLAUDE_EXECUTION_ROADMAP.md`](CODEX_CLAUDE_EXECUTION_ROADMAP.md).
A milestone is complete when its exit condition is demonstrable, `make check` is
green, and the project model is updated.

| ID | Milestone | Status |
| --- | --- | --- |
| M0 | Foundation | ✔ |
| M1 | Domain | ✔ |
| M2 | Persistence | ✔ |
| M3 | Product Experience | ✔ |
| M4 | Repository Realignment | ► current |
| M5 | Clickable Prototype | open |
| M6 | Walking Skeleton | open |
| M7 | Knowledge Lifecycle | open |
| M8 | Semantic Retrieval | open |
| M9 | AWS Integration | open |
| M10 | Demo Ready | open |

## Completed groundwork

Phases previously labelled bootstrap, requirements, architecture, and work
breakdown are complete and are recorded as milestones M0–M3: repository and CI
foundation, domain contracts, knowledge persistence, and product experience
definition. Their outputs are the specifications, ADR-0001 to ADR-0003,
`src/kae_memory/`, and the product documents in `docs/05_product/`.

## M4 — Repository realignment ► current

**Outcome:** repository documentation describes the system that exists, and the
quality gate is green again.

**Work:**

- update the project model, README, requirements baseline, MVP scope, project
  brief, development plan, execution roadmap, and context index;
- add the first-loaded current-state page;
- fix timezone normalisation on knowledge rehydration;
- clear the ruff and formatting findings;
- add `alembic.ini` and `migrations/env.py` so revision 0001 is executable;
- commit `uv.lock`;
- test `run_transaction` retry, backoff, and exhaustion.

**Exit condition:** `make check` passes on `main`, and a new contributor can
state the project's position in under a minute from `CURRENT_PROJECT_STATE.md`.

**Permitted changes:** documentation, plus the defect fixes listed above.

## M5 — Clickable prototype

**Outcome:** a clickable prototype of the discovery journey using seeded local
data only.

**Work:** start screen, discovery workspace, memory cards with status, readiness
explanation, quality finding, blueprint viewer, seeded demo state, accessibility
baseline.

**Blocked by:** OQ-011, frontend technology decision, which must be recorded as
an ADR first.

**Exit condition:** the three-minute demo story can be walked end to end with no
backend, and the missing product rules it exposes are written down.

## M6 — Walking skeleton

**Outcome:** one vertical path from project creation to persisted message to
candidate knowledge, over a real API, behind replaceable adapters.

**Work:** project and session creation, message submission, durable source
capture, deterministic fake extraction adapter, discovery workspace reading real
state, tests for input durability and idempotency.

**Blocked by:** OQ-010 physical schema, OQ-012 extraction contract.

**Exit condition:** AT-001 passes against a running application.

## M7 — Knowledge lifecycle

**Outcome:** trustworthy knowledge evolution.

**Work:** confirm, reject, revise, and supersede over the existing lifecycle
contracts; revision-history UI; transactionally safe active-state changes;
dependent-output review flags; audit records; relationship persistence.

**Also delivered here:** CockroachDB becomes authoritative for the whole slice —
integration tests against CockroachDB rather than SQLite, retry behaviour
verified under contention, cross-session recall demonstrated, and any temporary
store removed.

**Exit condition:** AT-002 and AT-003 pass, no correction path deletes history,
and the local development store is gone.

## M8 — Semantic retrieval

**Outcome:** recall that finds related knowledge the user did not name exactly.

**Work:** approved embedding model, vector columns and indexes, structured and
semantic retrieval, project and status filters, source-aware results.

**Blocked by:** an embedding decision recorded as an ADR.

**Exit condition:** a concept search returns related evidence, requirements, and
decisions with their sources.

## M9 — AWS integration

**Outcome:** the coherent product slice is deployed.

**Work:** only the services justified by approved decisions — runtime, model
access, object storage, secrets, logging, and asynchronous processing if
long-running work exists — with infrastructure-as-code and a teardown procedure.

**Rule:** launch a service only when a user-visible slice requires it, its
decision is approved, cost controls are understood, and a local or fake adapter
exists for tests.

**Exit condition:** the demo runs against deployed infrastructure and can be torn
down cleanly.

## M10 — Demo ready

**Outcome:** a demonstration that survives a live audience.

**Work:** resettable demo environment, stable sample project, seed and cleanup
commands, fallback outputs for model or network failure, monitoring checks,
rehearsal script, public README and architecture diagram, submission evidence.

**Exit condition:** the three-minute story runs twice in a row from a clean
reset, and AT-004 passes.

## Critical path

```text
Realign repository and restore green build
  -> validate the journey in a clickable prototype
  -> prove the workflow with a walking skeleton
  -> prove knowledge evolution on authoritative CockroachDB
  -> add semantic recall
  -> deploy what the slice requires
  -> harden the demonstration
```

## Controlled implementation loop

For each task:

1. issue one task-context bundle from `docs/10_prompts/TASK_CONTEXT_TEMPLATE.md`;
2. implement only within the allowed file scope;
3. run `make check` and the required tests;
4. review against requirements and architecture;
5. classify deviations rather than absorbing them;
6. update `project-model.yaml` and `CURRENT_PROJECT_STATE.md` before issuing the
   next task.

## Work not yet executable

| Work | Missing input |
| --- | --- |
| UI implementation | OQ-011 frontend decision and ADR |
| Project, session, message, relationship tables | OQ-010 physical schema |
| Real extraction | OQ-012 provider, prompt contract, and output schema |
| Readiness scoring | OQ-013 readiness model |
| Semantic retrieval | Approved embedding model and index strategy |
| Production deployment | Approved security, availability, and operating constraints |
