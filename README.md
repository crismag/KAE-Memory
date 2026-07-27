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

**Implementation.** The persistent-memory claim is proven end to end.

The repository contains engineering specifications, domain contracts, CockroachDB
persistence for knowledge and for projects, sessions, messages and agent runs,
application contracts, the product experience definition, the demonstration
narrative, five accepted architecture decisions, and the execution roadmap.

Current work is giving the three agent roles behaviour, so that a Requirements
Agent and an Architecture Agent collaborate through that memory rather than
through conversation.

## Repository status

Completed: foundation, domain contracts, persistence for knowledge and for
projects, sessions, messages and agent runs, product experience, demo planning,
architecture decisions, and the development roadmap.

Current: **M6 agent collaboration.** M5 is proven — one agent writes durable
knowledge, its process ends, and another agent retrieves it in a separate run and
session, reading only from the database.

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
| M9 | Workspace and Reporting | ► current |
| M10 | AWS Demonstration | open |
| M11 | Demo Ready and Release | open |

Repository health, implementation readiness, open risks, and the immediate next
task are in
[`docs/00_project/CURRENT_PROJECT_STATE.md`](docs/00_project/CURRENT_PROJECT_STATE.md).

## Immediate next action

Implement the first product slice:

```text
User creates project
  -> Submits idea
  -> Persistent source capture          [done, M5]
  -> Requirements Agent writes knowledge [done, M6]
  -> Human confirmation                  [done, M5]
  -> Architecture Agent retrieves it     [done, M6]
```

The proof is that the second agent's input is the first agent's confirmed output,
recovered from CockroachDB rather than carried in process memory. That path is
tested in `tests/application/test_cross_run_proof.py`.

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
AI Product Discovery Workspace          user-visible product (not yet built)
        |
Agent execution + Memory services       Requirements, Architecture, Review agents
        |                               behind KAE contracts (not yet built)
Application services                    project, knowledge, retrieval, blueprint
        |                               (specified, not yet built)
Domain contracts                        projects, agents, knowledge items,
        |                               immutable versions, provenance,
        |                               lifecycle, typed relationships
Persistence                             SQLAlchemy mappings, repositories,
        |                               bounded serialization-failure retry
CockroachDB                             durable, authoritative store
```

The core is a Python 3.12 library (ADR-0002). Domain contracts carry no
persistence or transport dependencies; persistence sits behind a repository
protocol so CockroachDB and model-provider adapters can change without rewriting
workflows (ADR-0003). Durable knowledge is built before orchestration, retrieval,
or generation (ADR-0001).

Agents reach the database only through KAE application contracts. CockroachDB MCP
is for inspection and management, never domain writes (ADR-0004).

The demonstration deployment shape is
[`docs/09_development/AWS_DEMONSTRATION_BASELINE.md`](docs/09_development/AWS_DEMONSTRATION_BASELINE.md);
the wider proposed topology is
[`docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md`](docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md)
and is not an approved deployment baseline.

## What exists in code

- `src/kae_memory/domain/` — identifiers, provenance, knowledge items and
  versions, lifecycle, projects, sessions, messages, agent runs and their status
  model, provenance links, typed domain errors.
- `src/kae_memory/persistence/` — SQLAlchemy mappings and repositories for all of
  the above, plus bounded retry for CockroachDB serialization failures.
- `src/kae_memory/application/` — `MemoryService`: create project, open session,
  record message, start/interrupt/resume/complete run, write knowledge, confirm,
  retrieve. Every domain write passes through here.
- `src/kae_memory/agents/` — `ExtractionPort` with a deterministic fixture
  adapter and a Bedrock adapter, versioned per-role prompts, source-quote
  verification, and the Requirements and Architecture agents.
- `src/kae_memory/worker/` — the durable worker: fenced claims, renewable leases,
  checkpoints after every step, and recovery after worker death.
- `migrations/` — revisions `0001` (knowledge), `0002` (workspace and execution),
  `0003` (lease ownership), and `0004` (chunks and the vector index).
- `tests/` — 112 tests including the cross-run persistence proof, the
  cross-session agent-collaboration proof, the kill-and-recovery proof, and
  semantic retrieval over a real vector index.

The Review agent, HTTP interfaces, and the user interface are **not**
implemented. Check
`src/kae_memory/` before assuming any capability exists.

## Getting started

```bash
make install     # uv sync --extra dev
make check       # lint, format check, mypy strict, pytest
```

`make check` passes: ruff, ruff format, mypy strict, and 112 tests against
CockroachDB. No test contacts a model provider.

To run migrations, copy `.env.example` to `.env` and set `KAE_DATABASE_URL`, then
`make migrate`. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Repository context

- [`docs/00_project/CURRENT_PROJECT_STATE.md`](docs/00_project/CURRENT_PROJECT_STATE.md)
  — **load first**; milestones, health, readiness, and next task.
- [`project-model.yaml`](project-model.yaml) — durable source of project state.
- [`docs/CONTEXT_INDEX.md`](docs/CONTEXT_INDEX.md) — navigation and loading guide.
- [`docs/00_project/PROJECT_BRIEF.md`](docs/00_project/PROJECT_BRIEF.md) — current
  project framing.
- [`docs/01_discovery/PROBLEM_DEFINITION.md`](docs/01_discovery/PROBLEM_DEFINITION.md)
  — accepted problem definition.
- [`docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md`](docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md)
  — approved MVP requirements and deferred scope.
- [`docs/05_product/PRODUCT_EXPERIENCE_NORTH_STAR.md`](docs/05_product/PRODUCT_EXPERIENCE_NORTH_STAR.md)
  — product identity, journey, and proof moments.
- [`docs/05_product/UNIFIED_DEMO_NARRATIVE.md`](docs/05_product/UNIFIED_DEMO_NARRATIVE.md)
  — the canonical demo story.
- [`docs/05_product/MVP_SCOPE.md`](docs/05_product/MVP_SCOPE.md) — first-release
  inclusion and exclusion boundary.
- [`docs/06_architecture/MCP_ACCESS_POLICY.md`](docs/06_architecture/MCP_ACCESS_POLICY.md)
  — MCP is inspection-only; writes go through KAE contracts.
- [`docs/09_development/AWS_DEMONSTRATION_BASELINE.md`](docs/09_development/AWS_DEMONSTRATION_BASELINE.md)
  — deployment shape, health checks, and secrets.
- [`docs/09_development/PUBLIC_RELEASE_CHECKLIST.md`](docs/09_development/PUBLIC_RELEASE_CHECKLIST.md)
  — release and judging assets with due milestones.
- [`docs/06_architecture/ARCHITECTURE_WORKPLAN.md`](docs/06_architecture/ARCHITECTURE_WORKPLAN.md)
  — architecture questions and required outputs.
- [`docs/09_development/DEVELOPMENT_PLAN.md`](docs/09_development/DEVELOPMENT_PLAN.md)
  — phased implementation plan.
- [`docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md`](docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md)
  — slice sequence and coding-agent control plan.
- [`specifications/`](specifications/) — domain, memory, retrieval, agent
  execution, API, and database specifications with architecture decisions.

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
- [`docs/10_prompts/TASK_CONTEXT_TEMPLATE.md`](docs/10_prompts/TASK_CONTEXT_TEMPLATE.md)
  — mandatory per-task handoff format.
