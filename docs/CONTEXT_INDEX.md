# Context Index

This repository uses layered, selective context. Load only the layers required
for the current activity.

| Layer | Repository context | Load when |
| --- | --- | --- |
| Project | `README.md`, `project-model.yaml`, `docs/00_project/` | Always |
| Discovery | `docs/01_discovery/` | Reviewing the problem or product intent |
| Requirements | `docs/02_requirements/` | Defining or reviewing behaviour |
| Product | `docs/05_product/` | Reviewing MVP, user experience, demo, and release boundaries |
| Architecture | `docs/06_architecture/` | Designing components and contracts |
| Development | `docs/09_development/` | Planning, sequencing, or issuing coding-agent work |
| Task | One issued `TASK_CONTEXT.md` | Executing one bounded task |
| Agent instructions | `docs/10_prompts/` | Preparing or reviewing agent handoffs |

## Product experience context

- `docs/05_product/PRODUCT_EXPERIENCE_NORTH_STAR.md` defines the product identity,
  first user, value proposition, primary journey, visible proof moments, MVP
  screens, and product principles.
- `docs/05_product/DEMO_STORY_AND_SCRIPT.md` defines the three-minute hackathon
  narrative, demonstration data, proof matrix, failure strategy, and acceptance
  conditions.
- `docs/05_product/MVP_UI_WORKSPACE.md` defines the proposed start screen,
  discovery workspace, memory explorer, quality view, blueprint viewer, interface
  states, accessibility baseline, and visual direction.

These product documents define the intended user experience but do not approve a
frontend framework or authorise implementation by themselves.

## Architecture context

- `docs/06_architecture/ARCHITECTURE_WORKPLAN.md` defines the architecture
  questions, required outputs, and provisional restrictions.
- `docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md` records the
  proposed KAE–AWS–CockroachDB end-to-end architecture for requirements review,
  ADR preparation, task decomposition, and hackathon planning. It is not an
  approved implementation specification until the related requirements and
  decisions are accepted.

## Development and coding-agent context

- `docs/09_development/CODEX_CLAUDE_EXECUTION_ROADMAP.md` defines planning gates,
  vertical product slices, bounded Codex or Claude responsibilities, initial task
  prompts, pull-request evidence, review strategy, and service-provisioning rules.

The roadmap is a control plan. Each implementation still requires one approved,
task-specific context with an exact file scope and acceptance criteria.

## Current loading rule

No coding agent should be asked to implement application code from this context
package alone. An issued task must contain:

- objective and business purpose;
- related approved requirements;
- relevant product experience and architecture;
- repository state;
- constraints and acceptance criteria;
- required tests;
- allowed file scope;
- prohibited changes;
- open issues.
