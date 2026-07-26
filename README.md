# KAE-Memory

Persistent Memory and Knowledge Evolution for Autonomous AI Agents.

KAE-Memory is the persistent-memory foundation for an AI-native software
engineering platform. Its purpose is to let specialised AI agents collaborate
across the software development lifecycle while preserving project knowledge,
requirements, architectural decisions, task progress, implementation history,
and learned experience across sessions.

## Current repository phase

This repository is in **specification and controlled bootstrap**.

The immediate objective is not to implement the full platform. It is to define
and validate the smallest release that can prove persistent, shared engineering
memory for multiple AI agents.

No application language, framework, service topology, API style, vector-search
implementation, or CockroachDB schema is approved by this bootstrap package.
Those decisions must be derived from approved requirements and recorded as
architecture decisions.

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

## Repository context

- [`project-model.yaml`](project-model.yaml) — durable source of project state.
- [`docs/CONTEXT_INDEX.md`](docs/CONTEXT_INDEX.md) — navigation and loading guide.
- [`docs/00_project/PROJECT_BRIEF.md`](docs/00_project/PROJECT_BRIEF.md) — current
  project framing.
- [`docs/01_discovery/PROBLEM_DEFINITION.md`](docs/01_discovery/PROBLEM_DEFINITION.md)
  — accepted provisional problem definition.
- [`docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md`](docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md)
  — requirements work still needed before architecture is executable.
- [`docs/05_product/MVP_SCOPE.md`](docs/05_product/MVP_SCOPE.md) — first-release
  proof and exclusions.
- [`docs/06_architecture/ARCHITECTURE_WORKPLAN.md`](docs/06_architecture/ARCHITECTURE_WORKPLAN.md)
  — architecture questions and required outputs.
- [`docs/09_development/DEVELOPMENT_PLAN.md`](docs/09_development/DEVELOPMENT_PLAN.md)
  — staged implementation plan.
- [`docs/10_prompts/TASK_CONTEXT_TEMPLATE.md`](docs/10_prompts/TASK_CONTEXT_TEMPLATE.md)
  — mandatory per-task handoff format.

## Immediate next action

Approve the MVP requirements baseline before application scaffolding or database
schema implementation begins.
