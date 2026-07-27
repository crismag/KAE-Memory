# Current Project State

**Load this file first.** Every human contributor and every coding agent should
read this page before any other repository context. It is the single answer to
"where does KAE-Memory stand today, and what happens next?"

**Last realigned:** 2026-07-27 · **Model version:** 5

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
knowledge and a traceable blueprint.

## Current milestone

**M4 — Repository Realignment** (in progress)

The repository's engineering foundations are built, but its project documents
still described a pre-implementation bootstrap. M4 makes the documentation
describe the repository that actually exists, so that implementation work can
trace cleanly to an accurate baseline.

M4 is documentation-only. It adds no application code, schema, or services.

## Milestones

| ID | Milestone | Status |
| --- | --- | --- |
| M0 | Foundation — repository, tooling, CI, context model | ✔ complete |
| M1 | Domain — contracts, identifiers, lifecycle, invariants | ✔ complete |
| M2 | Persistence — SQLAlchemy mapping, retry semantics, first migration | ✔ complete (partial coverage, see health) |
| M3 | Product Experience — identity, journey, screens, demo narrative | ✔ complete |
| M4 | Repository Realignment — documentation matches reality | ► current |
| M5 | Clickable Prototype — seeded UI proving the journey | open |
| M6 | Walking Skeleton — application layer over the existing persistence foundation | open |
| M7 | Knowledge Lifecycle — confirm, reject, revise, supersede | open |
| M8 | Semantic Retrieval — embeddings, recall, return session | open |
| M9 | AWS Integration — deploy what the slice requires | open |
| M10 | Demo Ready — hardening, seed data, fallbacks, submission evidence | open |

M0–M3 are complete in the sense that their deliverables exist and are reviewable,
not in the sense that they are final. M2 in particular is a foundation, not full
coverage — see below.

## Repository health

Assessed 2026-07-27 against `make check`.

| Gate | Result |
| --- | --- |
| `ruff check` | ✖ 6 findings (`I001`, 3× `E501`, `UP047`, `B008`) |
| `ruff format --check` | ✖ 2 files would be reformatted |
| `mypy --strict` | ✔ clean across 13 source files |
| `pytest` | ✖ 1 failed, 9 passed |

Known defects to clear during M4 or at the start of M5:

1. **Repository round-trip test fails.** SQLite returns naive datetimes for
   `DateTime(timezone=True)`, so rehydration violates the domain's
   timezone-aware provenance invariant. The mapping does not normalise on load.
2. **Alembic cannot run.** `migrations/versions/0001_create_knowledge_tables.py`
   exists, but there is no `alembic.ini` and no `migrations/env.py`.
3. **No lockfile.** `uv sync` is used by the Makefile and CI, but `uv.lock` is
   not committed, so builds are not reproducible.
4. **Transaction retry is untested.** `run_transaction` and its SQLSTATE 40001
   detection have no direct tests.

These are tracked as TASK-002 through TASK-005.

## Implementation readiness

| Area | State |
| --- | --- |
| Domain contracts | Implemented — project, agent, knowledge item, version, provenance, relationship, lifecycle |
| Knowledge persistence | Implemented — `knowledge_items`, `knowledge_versions`, repository, retry policy |
| Project / session / message persistence | **Not implemented** — required by M6 |
| Relationship persistence | **Not implemented** — required by M7 traceability |
| Application services | Not implemented |
| HTTP or MCP interface | Not implemented |
| User interface | Not implemented |
| Retrieval and embeddings | Not implemented |
| Cloud services | None provisioned |

The domain layer is ahead of the persistence layer, and the persistence layer is
ahead of everything above it. No coding agent should assume a service, endpoint,
or table exists without checking `src/kae_memory/`.

## Current MVP

An AI product-discovery workspace that converts an incomplete software idea into
confirmed, source-traceable engineering knowledge that survives across sessions
and produces a development blueprint.

Authorised MVP capabilities are listed in
[`docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md`](../02_requirements/MVP_REQUIREMENTS_BASELINE.md).
The inclusion and exclusion boundary is in
[`docs/05_product/MVP_SCOPE.md`](../05_product/MVP_SCOPE.md).

## Current demo

A three-minute narrative in which a user submits a paragraph, sees structured
knowledge and unknowns appear, answers one purposeful question, returns in a
later session to find the project state intact, corrects a rule so the prior
version becomes superseded rather than deleted, and generates a blueprint whose
statements link back to their sources.

Defined in
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
- AWS deployment baseline remains proposed, not approved. See
  [`docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md`](../06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md).

### Architecture status

| Decision | State |
| --- | --- |
| ADR-0001 memory-first ordering | accepted |
| ADR-0002 Python library-first bootstrap | accepted |
| ADR-0003 SQLAlchemy, Alembic, psycopg | accepted |
| Frontend technology | **open** — OQ-011, blocks M5 |
| Physical schema for projects, sessions, messages, relationships | **open** — OQ-010, blocks M6 |
| Extraction provider, prompt contract, output schema | **open** — OQ-012, blocks M6 |
| Readiness model | **open** — OQ-013, blocks M10 |
| AWS deployment baseline | **open** — blocks M9 |
| Embedding model and index strategy | **open** — blocks M8 |

## Open risks

| ID | Risk | Status |
| --- | --- | --- |
| RISK-002 | Shared memory may accumulate conflicting knowledge or degrade engineering quality | open — mitigated by lifecycle states, supersession without deletion, and provenance on every version |
| RISK-004 | Documentation drifts from implemented code, so agents act on inaccurate state | mitigating — this page is first-loaded context and is updated at every milestone close |
| RISK-005 | `main` does not pass its own quality gate, so CI signal is unreliable | open — TASK-003 to TASK-005 |
| RISK-006 | The demonstration depends on unprovisioned services and unmeasured model behaviour | open — deterministic adapters, seeded state, and documented fallbacks required before M10 |
| KG-002 | Extraction quality is unmeasured, so confirmation effort is unknown | open |

RISK-001 and RISK-003, both concerning premature implementation, are mitigated by
the recorded decisions and bounded task contexts.

## Target release

The first release is the hackathon demonstration at M10: a resettable environment
in which the three-minute story runs twice from a clean reset, with AT-001 to
AT-004 passing. It is a demonstration release, not a production one —
authentication, teams, billing, and multi-region deployment are outside the MVP
boundary.

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

1. Merge the repository-realignment change (this milestone). M4 closes on merge.
2. Execute **RA-01 — Restore Repository Readiness Gates** as its own bounded
   engineering pull request, limited to the four recorded defects:
   - timezone normalisation when rehydrating knowledge from the database;
   - the ruff and formatting findings;
   - `alembic.ini` and `migrations/env.py` so revision 0001 is executable;
   - `uv.lock`, plus tests for `run_transaction` retry and exhaustion.

**RA-01 acceptance condition:** a clean checkout can install, lint, type-check,
and test successfully using the documented commands.

RA-01 must not add UI scaffolding, application services, API routes, schema
expansion, or architectural redesign.

Only after RA-01 restores a clean baseline, issue Prompt PX-01 to plan the M5
clickable prototype. Do not begin PX-01 while the repository is known to be red,
and do not begin M5 implementation before that plan is reviewed.
