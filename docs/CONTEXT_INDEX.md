# Context Index

This repository uses layered, selective context. Load only the layers required
for the current activity.

| Layer | Repository context | Load when |
| --- | --- | --- |
| Project | `README.md`, `project-model.yaml`, `docs/00_project/` | Always |
| Discovery | `docs/01_discovery/` | Reviewing the problem or product intent |
| Requirements | `docs/02_requirements/` | Defining or reviewing behaviour |
| Product | `docs/05_product/` | Reviewing MVP and release boundaries |
| Architecture | `docs/06_architecture/` | Designing components and contracts |
| Development | `docs/09_development/` | Planning or sequencing work |
| Task | One issued `TASK_CONTEXT.md` | Executing one bounded task |
| Agent instructions | `docs/10_prompts/` | Preparing or reviewing agent handoffs |

## Architecture context

- `docs/06_architecture/ARCHITECTURE_WORKPLAN.md` defines the architecture
  questions, required outputs, and provisional restrictions.
- `docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md` records the
  proposed KAE–AWS–CockroachDB end-to-end architecture for requirements review,
  ADR preparation, task decomposition, and hackathon planning. It is not an
  approved implementation specification until the related requirements and
  decisions are accepted.

## Current loading rule

No coding agent should be asked to implement application code from this context
package alone. An issued task must contain:

- objective and business purpose;
- related approved requirements;
- relevant architecture and interfaces;
- repository state;
- constraints and acceptance criteria;
- required tests;
- allowed file scope;
- prohibited changes;
- open issues.
