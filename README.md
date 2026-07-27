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

**Product Experience Alignment and Implementation Kickoff.**

The engineering foundations of KAE-Memory have been established. The repository
now contains:

- engineering specifications;
- domain contracts;
- CockroachDB persistence foundations;
- product experience definition;
- demonstration narrative;
- architecture context;
- execution roadmap.

Current work is focused on implementing the first end-to-end product slice that
proves persistent engineering memory.

## Repository status

Completed: foundation, domain contracts, knowledge persistence, product
experience, demo planning, architecture context, and the development roadmap.

Current: **M4 Repository realignment.** Next: **M5 persistent-memory proof** —
one agent writes durable knowledge, another retrieves it in a separate run.

## Implementation milestones

| ID | Milestone | Status |
| --- | --- | --- |
| M0 | Foundation | ✔ |
| M1 | Domain | ✔ |
| M2 | Persistence | ✔ |
| M3 | Product Experience | ✔ |
| M4 | Repository Realignment | ► current |
| M5 | Persistent Memory Proof | open |
| M6 | Agent Collaboration | open |
| M7 | Resilience and Recovery | open |
| M8 | Semantic Retrieval | open |
| M9 | Workspace and Reporting | open |
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
  -> Persistent source capture
  -> Requirements Agent writes candidate knowledge
  -> Human confirmation
  -> Architecture Agent retrieves confirmed requirements in a later run
```

The proof is that the second agent's input is the first agent's confirmed output,
recovered from CockroachDB rather than carried in process memory.

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
  versions, lifecycle states and transitions, typed domain errors.
- `src/kae_memory/persistence/` — SQLAlchemy mappings for knowledge items and
  versions, a repository over them, and bounded retry for CockroachDB
  serialization failures.
- `migrations/` — the first knowledge-table revision.
- `tests/` — domain invariant tests and a persistence round-trip test.

Project, session, message, relationship, and AgentRun persistence, application
services, agent execution, interfaces, retrieval, and the user interface are
**not** implemented. Check `src/kae_memory/` before assuming any capability
exists.

## Getting started

```bash
make install     # uv sync --extra dev
make check       # lint, format check, mypy strict, pytest
```

`make check` does not currently pass. Known defects and their remediation order
are recorded in
[`docs/00_project/CURRENT_PROJECT_STATE.md`](docs/00_project/CURRENT_PROJECT_STATE.md).

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
