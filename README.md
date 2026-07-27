# KAE-Memory

Persistent Memory and Knowledge Evolution for Autonomous AI Agents.

KAE-Memory is the engineering-memory foundation for an AI-native software
engineering platform. Its purpose is to let specialised AI agents collaborate
across the software development lifecycle while preserving project knowledge,
requirements, architectural decisions, task progress, implementation history,
and learned experience across sessions.

It is demonstrated through an AI product-discovery workspace: a user arrives with
an incomplete idea and leaves with confirmed, source-traceable engineering
knowledge and a development blueprint.

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

Current: **M4 Repository realignment.** Next: **M5 clickable product prototype.**

## Implementation milestones

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

Repository health, implementation readiness, open risks, and the immediate next
task are in
[`docs/00_project/CURRENT_PROJECT_STATE.md`](docs/00_project/CURRENT_PROJECT_STATE.md).

## Immediate next action

Implement the first product slice:

```text
User creates project
  -> Submits idea
  -> Persistent source capture
  -> Candidate knowledge extraction
  -> Human confirmation
  -> Knowledge persistence
  -> Cross-session retrieval
```

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

## What exists in code

- `src/kae_memory/domain/` — identifiers, provenance, knowledge items and
  versions, lifecycle states and transitions, typed domain errors.
- `src/kae_memory/persistence/` — SQLAlchemy mappings for knowledge items and
  versions, a repository over them, and bounded retry for CockroachDB
  serialization failures.
- `migrations/` — the first knowledge-table revision.
- `tests/` — domain invariant tests and a persistence round-trip test.

Project, session, message, and relationship persistence, application services,
interfaces, retrieval, and the user interface are **not** implemented. Check
`src/kae_memory/` before assuming any capability exists.

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
- [`docs/05_product/MVP_SCOPE.md`](docs/05_product/MVP_SCOPE.md) — first-release
  inclusion and exclusion boundary.
- [`docs/06_architecture/ARCHITECTURE_WORKPLAN.md`](docs/06_architecture/ARCHITECTURE_WORKPLAN.md)
  — architecture questions and required outputs.
- [`docs/09_development/DEVELOPMENT_PLAN.md`](docs/09_development/DEVELOPMENT_PLAN.md)
  — phased implementation plan.
- [`docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md`](docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md)
  — slice sequence and coding-agent control plan.
- [`specifications/`](specifications/) — domain, memory, retrieval, API, and
  database specifications with architecture decisions.
- [`docs/10_prompts/TASK_CONTEXT_TEMPLATE.md`](docs/10_prompts/TASK_CONTEXT_TEMPLATE.md)
  — mandatory per-task handoff format.
