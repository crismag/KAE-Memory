# KAE-Memory

Persistent Memory and Knowledge Evolution for Autonomous AI Agents.

KAE-Memory is the engineering-memory foundation for an AI-native software
engineering platform. Its purpose is to let specialised AI agents collaborate
across the software development lifecycle while preserving project knowledge,
requirements, architectural decisions, task progress, implementation history,
and learned experience across sessions.

It is demonstrated through an AI product-discovery workspace: a user arrives with
an incomplete idea and leaves with confirmed, source-traceable engineering
knowledge and a development blueprint. Three predefined agents — Requirements,
Architecture, and Review — do that work behind the workspace, collaborating only
through persistent engineering memory.

## Current phase

**Backend foundation complete; product integration and configuration controls
are next.** The persistent-memory and acquisition-to-context paths are proven
through application, worker, HTTP, and local MCP surfaces.

KAE-Memory is a **headless knowledge service**. It serves two adapters — HTTP
and MCP — and no user interface. KAE-Studio owns the product UI and interview
experience, in its own repository (ADR-0026). UI work does not belong here.

## Repository status

Completed: domain and persistence foundations, durable agents and recovery,
semantic retrieval, knowledge review, readiness, clarification, ingestion,
bounded context assembly, compact MCP responses, project-key resolution, and
observation classification.

## Implementation milestones

| ID | Milestone | Status |
| --- | --- | --- |
| M0 | Foundation | ✔ |
| M1 | Domain | ✔ |
| M2 | Persistence | ✔ |
| M3 | Product Experience | ✔ |
| M4 | Repository Realignment | ✔ |
| M5 | Persistent Memory Proof | ✔ |
| M6 | Agent Collaboration | ✔ |
| M7 | Resilience and Recovery | ✔ |
| M8 | Semantic Retrieval | ✔ |
| M9 | Workspace and Reporting | ✔ |
| M10 | AWS Demonstration assets | ✔ (real-instance proof outstanding) |
| M11 | Demo Ready and Release | superseded by the T-register |

## Development principle

```text
Project model
  -> approved requirements
  -> coherent architecture and contracts
  -> executable development tasks
  -> task-specific agent context
  -> implementation and validation
  -> discoveries fed back into the model
```

Coding agents must receive one bounded task context at a time. They must not be
given the entire package as a universal implementation prompt.

## Architecture overview

```text
KAE-Studio                              user-visible product (separate repository)
        |
API / MCP / worker                      product-neutral control surfaces
        |
Agent execution + Memory services       implemented application capabilities
        |
Domain contracts                        projects, agents, knowledge items,
        |                               immutable versions, provenance,
        |                               lifecycle, typed relationships
Persistence                             SQLAlchemy mappings, repositories,
        |                               bounded serialization-failure retry
PostgreSQL or CockroachDB               durable, authoritative store (selectable)
```

The core is a Python 3.12 library (ADR-0002). Domain contracts carry no
persistence or transport dependencies; persistence sits behind a repository
protocol so database and model-provider adapters can change without rewriting
workflows (ADR-0003). Durable knowledge is built before orchestration, retrieval,
or generation (ADR-0001).

Agents reach the database only through KAE application contracts. Database MCP
is for inspection and management, never domain writes (ADR-0004).


## What exists in code

- `src/kae_memory/domain/` — identifiers, provenance, knowledge items and
  versions, lifecycle, projects, sessions, messages, agent runs and their status
  model, provenance links, typed domain errors.
- `src/kae_memory/persistence/` — SQLAlchemy mappings and repositories for all of
  the above, plus bounded retry where the provider requires it.
- `src/kae_memory/application/` — `MemoryService`: create project, open session,
  record message, start/interrupt/resume/complete run, write knowledge, confirm,
  retrieve. Every domain write passes through here.
- `src/kae_memory/agents/` — `ExtractionPort` with a deterministic fixture
  adapter and a Bedrock adapter, versioned per-role prompts, source-quote
  verification, and the Requirements and Architecture agents.
- `src/kae_memory/application/blueprint_service.py` — blueprint generation from
  confirmed knowledge, labelled grounded, derived, or assumption, with Markdown
  export and a full trace from any statement to the message and run behind it.
- `src/kae_memory/application/review_service.py` — quality findings derived from
  operational data: gaps, unclassified and unconfirmed knowledge, open questions,
  unresolved contradictions, and blockers.
- `src/kae_memory/worker/` — the durable worker: fenced claims, renewable leases,
  checkpoints after every step, recovery after worker death, and the daemon loop
  behind `python -m kae_memory.worker`.
- `src/kae_memory/api/` — the HTTP contract (ADR-0014): projects, sessions,
  messages, knowledge, runs, readiness, review findings, blockers,
  contradictions, blueprint generation and Markdown export, knowledge trace,
  `GET /health`, and run progress over Server-Sent Events. Served by `python -m kae_memory.api`.
- `src/kae_memory/domain/readiness.py` and `application/readiness_service.py` —
  the deterministic blueprint-readiness calculator, discovery blockers,
  contradiction resolution, area assignment, and append-only snapshots.
- `migrations/` — eleven revisions, `0001` (knowledge) through `0011`. Along the
  way: workspace and execution, lease ownership, chunks and the vector index,
  readiness and area links, message idempotency, and the knowledge review log.
- `tests/` — 792 tests including the HTTP contract, the cross-run persistence
  proof, the cross-session agent-collaboration proof, the kill-and-recovery
  proof, semantic retrieval over a real vector index, readiness scoring that
  cannot be inflated by generating unconfirmed text, and the Demo V1 workflow
  from document ingestion to an assembled context package.

Two things are genuinely absent. **Modules are not modelled** — there is no
`module` knowledge kind, no general relationship write path, and no traversal,
which is why `kae_get_module_context` reports a capability gap instead of
inventing one. **Nothing renders or publishes an artifact** — assembly
describes what a package would contain and stops there. Check
`src/kae_memory/` before assuming any capability exists.

## Getting started

```bash
make install     # uv sync --extra dev --extra api
make dev         # database, migrations, API, and worker
```

The API is then on <http://localhost:8000> — `/health` for status, `/docs` for
the routes. Nothing needs AWS and no credentials are required; extraction runs
offline against a fixture. KAE-Memory serves no interface of its own
(ADR-0026).

To enable live models and deploy, follow
[`operations/runbooks/enablement-sequence.md`](operations/runbooks/enablement-sequence.md)
in order — each stage has a verification gate.

```bash
make check       # lint, format check, mypy strict, pytest
```

`make check` passes: ruff, ruff format, mypy strict, and the full suite against
the selected provider — 792 tests, 92% coverage on PostgreSQL. No test contacts
a model provider.

`make worker` runs the durable worker as a **separate process** from the API — it
claims queued runs and executes them, so an enqueued run actually completes. It
uses the offline extractor by default and needs no credentials.

`make api` serves the HTTP contract at <http://127.0.0.1:8000>, with interactive
documentation at `/docs` and the OpenAPI document at `/openapi.json`. **It has no
authentication** — the MVP defers it, so keep it behind a network boundary
(ADR-0014).

To run migrations, copy `.env.example` to `.env` and set `KAE_DATABASE_URL`, then
`make migrate`. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Where files belong

The layout separates by **responsibility, not by hosting vendor**, and is
intentionally minimal — directories appear when a real file belongs in them.

| Responsibility | Location |
| --- | --- |
| Python business logic, API, worker | `src/kae_memory/` |
| Recorded HTTP contract, guarded by a test | [`specifications/openapi.json`](specifications/openapi.json) |
| Safe committed defaults | [`config/`](config/) |
| Local credentials and overrides | ignored `.env`, `.local/`, `.secrets/` |
| Generic Linux installation, systemd, reverse proxy | [`deploy/server/`](deploy/server/) |
| Deployment and recovery procedures | [`operations/runbooks/`](operations/runbooks/) |

`scripts/` operates the project; `deploy/` installs it onto a target system. No
Docker, Kubernetes, or infrastructure-as-code framework is introduced — see
[`deploy/README.md`](deploy/README.md) for what is deferred and why.

## Repository context

- [`specifications/`](specifications/) — domain, memory, retrieval, agent
  execution, API, and database specifications with architecture decisions.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
