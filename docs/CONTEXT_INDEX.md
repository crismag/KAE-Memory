# Context Index

This repository uses layered, selective context. Load only the layers required
for the current activity.

## Load first — repository status, current phase, implementation kickoff

[`docs/00_project/CURRENT_PROJECT_STATE.md`](00_project/CURRENT_PROJECT_STATE.md)

Every human contributor and every coding agent reads this page before any other
repository context. It records:

- the current milestone and the M0–M10 milestone register;
- repository health, including which quality gates currently fail;
- implementation readiness per area — what exists in code and what does not;
- the current MVP, demo, and architectural direction;
- the branch strategy;
- the immediate next task.

Nothing in this repository authorises implementation on its own. If the current
state page and another document disagree, the current state page is correct and
the other document needs updating.

## Layers

| Layer | Repository context | Load when |
| --- | --- | --- |
| Status | `docs/00_project/CURRENT_PROJECT_STATE.md` | Always, first |
| Project | `README.md`, `project-model.yaml`, `docs/00_project/` | Always |
| Discovery | `docs/01_discovery/` | Reviewing the problem or product intent |
| Requirements | `docs/02_requirements/` | Defining or reviewing behaviour |
| Product | `docs/05_product/` | Reviewing MVP, user experience, demo, and release boundaries |
| Architecture | `docs/06_architecture/`, `specifications/` | Designing components and contracts |
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
- `docs/05_product/MVP_SCOPE.md` defines the approved inclusion and exclusion
  boundary for the first release.

These product documents define the intended user experience but do not approve a
frontend framework or authorise implementation by themselves.

## Architecture context

- `specifications/` holds the domain, memory, retrieval, API, and database
  specifications and the accepted architecture decisions ADR-0001 to ADR-0003.
- `docs/06_architecture/ARCHITECTURE_WORKPLAN.md` defines the remaining
  architecture questions, required outputs, and provisional restrictions.
- `docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md` records the
  proposed KAE–AWS–CockroachDB end-to-end architecture for requirements review,
  ADR preparation, task decomposition, and hackathon planning. It is not an
  approved implementation specification until the related requirements and
  decisions are accepted.

## Development and coding-agent context

- `docs/09_development/DEVELOPMENT_PLAN.md` defines the phased plan from
  repository realignment to demo hardening.
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

An agent must also verify claimed capabilities against `src/kae_memory/` rather
than assuming that a documented module, table, or service exists.
