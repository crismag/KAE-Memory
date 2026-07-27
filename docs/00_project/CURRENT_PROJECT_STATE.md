# Current Project State

**Load this file first.** Every human contributor and every coding agent should
read this page before any other repository context. It is the single answer to
"where does KAE-Memory stand today, and what happens next?"

**Last realigned:** 2026-07-27 · **Model version:** 6

## Vision

```text
Engineering Memory Operating System
  -> First product: AI Product Discovery Workspace
  -> Proven by: Persistent Engineering Memory
  -> Delivered as: Blueprint Generation
```

KAE-Memory is the durable, provenance-aware knowledge layer that lets humans and
specialised AI agents work on the same project across sessions. Its first product
is a discovery workspace that turns an incomplete idea into confirmed engineering
knowledge and a traceable blueprint. Three predefined agents — Requirements,
Architecture, and Review — do that work behind the workspace, collaborating only
through persistent memory.

## Current milestone

**M7 — Resilience and Recovery** (next)

M6 is complete: the Architecture Agent consumes requirements confirmed in an
earlier session, with the handoff carried entirely by the database.

M7 makes compute disposable — the lease protocol from ADR-0007, durable
checkpoints, and a worker that resumes what a killed worker left behind. This is
the milestone the demonstration rests on.

## Milestones

| ID | Milestone | Status |
| --- | --- | --- |
| M0 | Foundation — repository, tooling, CI, context model | ✔ complete |
| M1 | Domain — contracts, identifiers, lifecycle, invariants | ✔ complete |
| M2 | Persistence — SQLAlchemy mapping, retry semantics, first migration | ✔ complete (partial coverage, see health) |
| M3 | Product Experience — identity, journey, screens, demo narrative | ✔ complete |
| M4 | Repository Realignment — documentation matches reality | ✔ complete |
| M5 | Persistent Memory Proof — one agent writes, another retrieves in a separate run | ✔ complete |
| M6 | Agent Collaboration — Requirements and Architecture agents, confirmation, context assembly | ✔ complete |
| M7 | Resilience and Recovery — idempotency, retry, durable run status, continuation | ► current |
| M8 | Semantic Retrieval — embeddings, recall, return session | open |
| M9 | Workspace and Reporting — discovery workspace over real state, Review Agent, reports | open |
| M10 | AWS Demonstration — deployed chain, disposable compute, health, secrets | open |
| M11 | Demo Ready and Release — rehearsal, packaging, submission evidence | open |

M0–M3 are complete in the sense that their deliverables exist and are reviewable,
not in the sense that they are final. M2 in particular is a foundation, not full
coverage — see below.

## Repository health

Assessed 2026-07-27 against `make check`, after M6.

| Gate | Result |
| --- | --- |
| `ruff check` | ✔ all checks passed |
| `ruff format --check` | ✔ 52 files formatted |
| `mypy --strict` | ✔ clean across 14 source files |
| `pytest` | ✔ 89 passed, 95% coverage |

RA-01 cleared all four known defects:

1. **Timezone normalisation on rehydration** — `_as_aware` interprets a naive
   stored timestamp as the UTC instant it was written as, so rehydration no
   longer violates the timezone-aware provenance invariant.
2. **Alembic is executable** — `alembic.ini` and `migrations/env.py` exist, and
   revision 0001 applies and rolls back. The database URL comes from
   `KAE_DATABASE_URL`; no credential is stored in the repository.
3. **`uv.lock` is committed** — builds are reproducible.
4. **Retry is tested** — `run_transaction` coverage went from 45% to 97%,
   covering SQLSTATE 40001 detection via both `sqlstate` and `pgcode`, bounded
   exhaustion, non-retryable errors, and backoff doubling.

`main` must stay green. A pull request that leaves `make check` failing should be
rejected rather than merged with a follow-up promise.

## Implementation readiness

| Area | State |
| --- | --- |
| Domain contracts | Implemented — project, agent, knowledge item, version, provenance, relationship, lifecycle |
| Knowledge persistence | Implemented — `knowledge_items`, `knowledge_versions`, repository, retry policy |
| Project / session / message persistence | Implemented — revision `0002`, repositories, application contracts |
| AgentRun and workflow state | Implemented — status model, idempotency, interrupt and resume |
| Provenance links | Implemented — produced-by, used-by, derived-from-message |
| Agent execution | Implemented — Requirements and Architecture agents behind `ExtractionPort`. Review agent is M9 |
| Relationship persistence | Table exists; domain wiring is M9 |
| Semantic retrieval and embeddings | **Not implemented** — decided (ADR-0008); needs a CockroachDB v25.4+ cluster |
| Deployment and health endpoint | **Not implemented** — required by M10 |
| Application services | Implemented — `MemoryService` |
| HTTP interface | Not implemented |
| User interface | Not implemented — moved to M9 |
| Cloud services | None provisioned |

The domain layer is ahead of the persistence layer, and the persistence layer is
ahead of everything above it. No coding agent should assume a service, endpoint,
or table exists without checking `src/kae_memory/`.

## Current MVP

An AI product-discovery workspace that converts an incomplete software idea into
confirmed, source-traceable engineering knowledge that survives across sessions
and produces a development blueprint.

Three predefined agents — Requirements, Architecture, Review — do the work behind
the workspace, collaborating only through persistent memory.

Authorised MVP capabilities are FR-001 to FR-018 in
[`docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md`](../02_requirements/MVP_REQUIREMENTS_BASELINE.md),
each **bounded**: three fixed agent roles, one embedding model, one region, one
worker. Exceeding a boundary requires a new requirement, not an implementer's
judgement.
The inclusion and exclusion boundary is in
[`docs/05_product/MVP_SCOPE.md`](../05_product/MVP_SCOPE.md).

## Current demo

A three-minute narrative in which a user submits a paragraph, the Requirements
Agent turns it into structured knowledge, the user confirms it, the Architecture
Agent derives decisions from those confirmed requirements, the worker is killed
mid-run and resumed by another, the Review Agent reports gaps in a new session,
and a blueprint is generated whose statements link back to their sources.

**Recovery is the proof.** A demonstration that omits the interruption and
resumption beats does not satisfy the release.

Canonical sequence:
[`docs/05_product/UNIFIED_DEMO_NARRATIVE.md`](../05_product/UNIFIED_DEMO_NARRATIVE.md).
Timing, sample data, and delivery craft:
[`docs/05_product/DEMO_STORY_AND_SCRIPT.md`](../05_product/DEMO_STORY_AND_SCRIPT.md).

## Current architectural direction

- Python 3.12 library-first core (ADR-0002), with application layers added only
  as slices require them.
- SQLAlchemy 2.0 + Alembic + psycopg 3 for persistence (ADR-0003).
- CockroachDB as the authoritative durable store, with serialization-failure
  retry handled at the unit-of-work boundary.
- Memory-first ordering: durable knowledge before orchestration, retrieval,
  or generation (ADR-0001).
- Ports and adapters at the persistence and model-provider boundaries so
  CockroachDB and Bedrock can be introduced without rewriting workflows.
- Three predefined agents behind the workspace, writing only through KAE
  application contracts. CockroachDB MCP is inspection-only (ADR-0004).
- Disposable compute: every run is durably recorded before work starts, so a
  killed worker loses nothing.
- AWS demonstration baseline approved in shape
  ([`docs/09_development/AWS_DEMONSTRATION_BASELINE.md`](../09_development/AWS_DEMONSTRATION_BASELINE.md));
  the wider topology in
  [`docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md`](../06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md)
  is not approved.

### Architecture status

| Decision | State |
| --- | --- |
| ADR-0001 memory-first ordering | accepted |
| ADR-0002 Python library-first bootstrap | accepted |
| ADR-0003 SQLAlchemy, Alembic, psycopg | accepted |
| ADR-0004 MCP inspection-only | accepted |
| ADR-0005 M5 physical schema (revision 0002) | accepted — closes OQ-010 |
| ADR-0006 extraction provider, prompt, and schema | accepted — closes OQ-012 |
| ADR-0007 worker runtime and renewable leases | accepted — closes OQ-015 |
| ADR-0008 embedding model and vector index | accepted — closes OQ-014 |
| Frontend technology | **open** — OQ-011, blocks M9 |
| Readiness model | **open** — OQ-013, blocks M9 |
| AWS runtime choice | **open** — OQ-016, blocks M10 |

## Open risks

| ID | Risk | Status |
| --- | --- | --- |
| RISK-002 | Shared memory may accumulate conflicting knowledge or degrade engineering quality | open — mitigated by lifecycle states, supersession without deletion, and provenance on every version |
| RISK-004 | Documentation drifts from implemented code, so agents act on inaccurate state | mitigating — this page is first-loaded context and is updated at every milestone close |
| RISK-005 | `main` does not pass its own quality gate, so CI signal is unreliable | closed — RA-01 restored all four gates |
| RISK-006 | The demonstration depends on unprovisioned services and unmeasured model behaviour | open — deterministic adapters, seeded state, and documented fallbacks required before M10 |
| KG-002 | Extraction quality is unmeasured, so confirmation effort is unknown | open |

RISK-001 and RISK-003, both concerning premature implementation, are mitigated by
the recorded decisions and bounded task contexts.

## Target release

The first release is the hackathon demonstration at M11: a resettable environment
in which the ten-beat narrative in
[`../05_product/UNIFIED_DEMO_NARRATIVE.md`](../05_product/UNIFIED_DEMO_NARRATIVE.md)
runs twice from a clean reset, with AT-001 to AT-009 passing, plus the package in
[`../09_development/PUBLIC_RELEASE_CHECKLIST.md`](../09_development/PUBLIC_RELEASE_CHECKLIST.md).

It is a demonstration release, not a production one — authentication, teams,
billing, administration, and multi-region deployment are outside the MVP
boundary. Recovery after worker death is the proof; a demo without it does not
satisfy the release.

## Current branch strategy

- `main` is protected and must stay green against `make check`.
- One branch per bounded task, named `type/short-subject`
  (`docs/repository-realignment`, `fix/alembic-environment`).
- One task per pull request, within its declared file scope.
- Pull requests follow the evidence expectations in
  [`docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md`](../09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md).
- Two coding agents must not edit the same branch. A second agent may review a
  completed pull request.

## Immediate next task

**Complete M4 and restore a green `make check`.**

M4 and RA-01 are complete. The quality gate is green and the documentation
describes the system that exists.

**M5 is complete.** Revision `0002` is applied, the application contracts exist,
and the proof passes: Agent A writes, its process ends, Agent B retrieves in
another run.

**M6 is unblocked.** ADR-0006 closes OQ-012: Claude on Amazon Bedrock behind an
`ExtractionPort`, structured JSON outputs, versioned per-role prompts, and
source-quote verification before any write.

**Next: implement M6 — agent collaboration.** The Requirements and Architecture
agents over these contracts, a deterministic fixture adapter, and context assembly
that gives the Architecture Agent confirmed requirements only.

Task context: [`../../development/tasks/TASK-007-m6-agent-collaboration.md`](../../development/tasks/TASK-007-m6-agent-collaboration.md).

Success condition for M6: the Architecture Agent uses validated requirements
created in an earlier session.

**Note for implementers:** `temperature`, `top_p`, and `top_k` are rejected by the
current models. Determinism comes from the fixture adapter, and no test may make
a live model call.

Product workspace integration remains at M9, after the memory and collaboration
chain is proven.
