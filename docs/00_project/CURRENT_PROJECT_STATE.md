# Current Project State

**Load this file first.** Every human contributor and every coding agent should
read this page before any other repository context. It is the single answer to
"where does KAE-Memory stand today, and what happens next?"

**Last realigned:** 2026-08-05 · **Model version:** 8

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

**Backend foundation complete; product integration and configuration controls
are now the active phase.**

The milestone register below carried the project to M11. Work is now tracked by
the **T-numbered register** in
[`../09_development/MCP_TARGET_CHECKLIST.md`](../09_development/MCP_TARGET_CHECKLIST.md),
which is the source of truth for what happens next. The milestones remain as
history; they are no longer the queue.

**T1 through T24 are delivered.** T4/T5 closed response pagination and verified
that compaction preserves integrity fields. T24 now classifies observations and
records operational updates without auto-confirming them. T25.2 added stateless
`project_key` resolution alongside `project_id`. T25.3 (server-side active
project) remains deliberately conditional, and T25.4 (cross-project comparison)
remains undesigned; neither is part of the current product path.

The complete next-phase orientation and independent action contexts are in
[`NEXT_PHASE_FULL_CONTEXT.md`](NEXT_PHASE_FULL_CONTEXT.md). Use one focus file
per implementation task rather than treating the entire next phase as a single
coding prompt.

**Phase E closed the acquisition-to-package loop.** A document can be ingested,
read into candidates, confirmed by a person, and assembled into a bounded
context package with a deterministic description. The Demo V1 scenario runs end
to end through the MCP surface in
`tests/mcp_adapter/test_end_to_end_workflow.py`.

**The Titan caveat is discharged.** T8 implemented the real embedding provider,
T10 re-embedded all 32 existing chunks, and T11 validated retrieval quality.
The deterministic embedder remains the offline default, and any response ranked
by it says so rather than presenting hash-derived ordering as meaning.

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
| M7 | Resilience and Recovery — idempotency, retry, durable run status, continuation | ✔ complete |
| M8 | Semantic Retrieval — embeddings, recall, return session | ✔ complete |
| M9 | Workspace and Reporting — discovery workspace over real state, Review Agent, reports | ✔ complete |
| M10 | AWS Demonstration — deployed chain, disposable compute, health, secrets | ✔ complete (ADR-0017; not yet run on a real instance) |
| M11 | Demo Ready and Release — rehearsal, packaging, submission evidence | superseded by the T-register |

M0–M3 are complete in the sense that their deliverables exist and are reviewable,
not in the sense that they are final. M2 in particular is a foundation, not full
coverage — see below.

## Repository health

Assessed 2026-08-05 against the full gate, on PostgreSQL.

| Gate | Result |
| --- | --- |
| `ruff check` | ✔ all checks passed |
| `ruff format --check` | ✔ 273 files formatted |
| `mypy --strict` | ✔ clean across 141 source files |
| `pytest` | ✔ 901 passed, 92% coverage, against PostgreSQL 5432 |

**This table is the single source for gate figures.** Other documents link here
rather than restating a count: the previous figure of 792 survived two later
runs in three separate files, because a number copied into prose is a number
nobody updates.

**PostgreSQL with pgvector is the default provider** (ADR-0022); CockroachDB is
also supported. `KAE_DATABASE_PROVIDER` is mandatory and has no default,
because a connection URL says where to connect and not what to expect there.
Schema head is revision `0011`, which added `observation_classifications` and `operational_updates` for T24.

**The type gate was repaired on 2026-08-04.** `tests/support/` had been added
without `tests/__init__.py`, so mypy resolved one file under two module names,
reported that, and stopped before checking anything — 192 real errors sat
unreported while `make check` failed on module resolution. Anything asserting
"mypy passes" before that date was asserting a command that verified nothing.

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
| Agent execution | Implemented — Requirements, Architecture, and Review agents behind `ExtractionPort` |
| Relationship persistence | Table and contradiction recording exist. **No general write path or traversal** — the gap `kae_get_module_context` reports |
| Semantic retrieval and embeddings | Implemented — vector index, cosine, lexical and semantic modes. Titan validated in T11; the offline embedder is hash-derived and every response says so |
| Deployment and health endpoint | Implemented — both entrypoints, systemd units, install and deploy scripts, SIGTERM handling, runbooks (ADR-0017). Not yet run on a real instance |
| Application services | Implemented — memory, blueprint, readiness, review, retrieval, clarification, ingestion, assembly, re-embedding |
| HTTP interface | Implemented — four routers (workspace, readiness, blueprint, root), ADR-0014 contract, generated client |
| Embedded user interface | Implemented in `frontend/`, but no longer the presumed product UI; it requires a dependency/value survey before removal |
| Product user interface | Owned by KAE-Studio; integration with the real Memory contract is the next product proof |
| Cloud services | None provisioned |
| MCP surface | Implemented — 15 tools, 4 resource templates, 1 prompt over STDIO (ADR-0018) |
| Document ingestion and context assembly | Implemented — `kae_ingest_document`, `kae_assemble_context`, deterministic package description (T19–T22) |
| Modules as first-class knowledge | **Not implemented** — no `module` kind, no relationship write path, no traversal, no module-scoped readiness |
| Artifact rendering and publication | **Not implemented** — assembly describes a package; rendering and writing it belong elsewhere (ADR-0020, proposed) |
| BYOK and usage governance | **Not implemented** — approved as a post-demo direction by ADR-0010 |

That inversion has closed: the layers are now built through to the MCP surface.
What remains genuinely absent is named above — modules, and anything that
renders or publishes an artifact. No coding agent should assume a service,
endpoint, or table exists without checking `src/kae_memory/`.

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
- PostgreSQL/pgvector and CockroachDB as selectable durable providers
  (ADR-0022), with provider-specific behaviour behind persistence adapters.
- Memory-first ordering: durable knowledge before orchestration, retrieval,
  or generation (ADR-0001).
- Ports and adapters at the persistence and model-provider boundaries so
  CockroachDB and model providers can be introduced without rewriting workflows.
- Bedrock remains the only approved live demonstration adapter. Provider-neutral
  extraction and BYOK are approved future directions, not current capabilities
  (ADR-0010).
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
| ADR-0009 discovery workspace frontend | accepted — closes OQ-011 |
| ADR-0010 provider-neutral extraction and BYOK direction | accepted — direction only; no current implementation |
| ADR-0011 tests run against CockroachDB | accepted — SQLite retired; amends ADR-0003 and ADR-0008 |
| ADR-0012 blueprint readiness model | accepted — closes OQ-013 |
| ADR-0013 portable runtime, optional AWS | accepted — closes OQ-016; amends FR-016 |
| ADR-0014 HTTP API contract | accepted — settles the open decisions in API_CONTRACTS.md |
| ADR-0013 amendment, 2026-07-28 | the runnable local worker moves to M9; deployment stays M10 |
| ADR-0015 Review Agent and findings | accepted — findings are derived, never stored |
| ADR-0016 blueprint generation and trace | accepted — no model writes blueprint prose |
| ADR-0017 deployment topology | accepted — closes OQ-018; EC2 and systemd, static frontend |
| SQS as a run-request signal | **open** — OQ-017, no ADR authorises it |
| KAE with Memory product direction | **14 open questions** — OQ-019 to OQ-032; see the alignment review |

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
billing, administration, BYOK, provider selection, usage governance, and
multi-region deployment are outside the MVP boundary. Recovery after worker
death is the proof; a demo without it does not satisfy the release.

## Current branch strategy

- `main` is protected and must stay green against `make check`.
- One branch per bounded task, named `type/short-subject`
  (`docs/repository-realignment`, `fix/alembic-environment`).
- One task per pull request, within its declared file scope.
- Pull requests follow the evidence expectations in
  [`docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md`](../09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md).
- Two coding agents must not edit the same branch. A second agent may review a
  completed pull request.

## Immediate next tasks

Choose one bounded focus; do not execute all four as one branch:

1. **Configuration foundation:** inventory and classify magic numbers and
   backend messages, define validated defaults and precedence, then migrate one
   coherent slice. See
   [`focus/CONFIGURATION_AND_MESSAGES.md`](focus/CONFIGURATION_AND_MESSAGES.md).
2. **Frontend separation survey:** map every dependency on `frontend/` and
   prepare a deletion manifest without deleting it in the survey task. See
   [`focus/FRONTEND_SEPARATION.md`](focus/FRONTEND_SEPARATION.md).
3. **Studio integration:** prove project creation through first proposal review
   against the real Memory contract, then extend to readiness and assembly. See
   [`focus/STUDIO_INTEGRATION.md`](focus/STUDIO_INTEGRATION.md).
4. **Remaining gaps:** address module modelling, publication, remote MCP, or
   deployment proof only through their separately identified decisions and
   gates. See [`focus/ENGINE_AND_PROOF_GAPS.md`](focus/ENGINE_AND_PROOF_GAPS.md).

No current task authorises a KAE-Memory settings UI, a broad administration
policy system, or new product UI work inside this repository.
