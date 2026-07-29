# Context Index

This repository uses layered, selective context. Load only the layers required
for the current activity.

## Load first — repository status, current phase, implementation kickoff

[`docs/00_project/CURRENT_PROJECT_STATE.md`](00_project/CURRENT_PROJECT_STATE.md)

Every human contributor and every coding agent reads this page before any other
repository context. It records:

- the current milestone and the M0–M11 milestone register;
- repository health, including which quality gates currently fail;
- implementation readiness per area — what exists in code and what does not;
- the current MVP, demo, and architectural direction;
- the branch strategy;
- the immediate next task.

Nothing in this repository authorises implementation on its own. If the current
state page and another document disagree, the current state page is correct and
the other document needs updating.

## Terminology

Use these terms as written. Do not introduce synonyms where one of these already
covers the concept.

| Term | Meaning |
| --- | --- |
| Engineering Memory | The durable, provenance-aware knowledge layer. The platform's core capability. |
| Product Discovery Workspace | The first product experience built on Engineering Memory. Not a separate product direction. |
| Project | The durable boundary that owns all sessions, knowledge, and outputs. No cross-project reads. |
| Session | A bounded period of work within one project. Continuity across sessions is the central proof. |
| Message | A user submission, persisted verbatim as source evidence before interpretation. |
| Evidence | Source material a statement rests on — a message, and later a document. |
| Knowledge | A typed, versioned item of project understanding. Never used loosely for "information". |
| Candidate Knowledge | Knowledge produced by extraction and not yet reviewed by a human. Enters the `proposed` lifecycle state. |
| Confirmed Knowledge | Knowledge a human has validated. The `validated` lifecycle state; shown to users as "confirmed". |
| Provenance | The source, actor, and execution recorded on every knowledge version. |
| Supersession | Replacing knowledge while preserving the prior version. Never deletion. |
| Traceability | The navigable path from an output statement back to the knowledge and evidence that produced it. |
| Blueprint | The user-facing output package generated from confirmed knowledge, with statements labelled grounded, derived, or assumption. |
| AgentRun | The durable record of one agent execution: role, session, status, input context, output, attempt, timing. Not a log line. |
| Agent role | One of exactly three: Requirements, Architecture, Review. No others are authorised. |
| Continuation | Resuming an interrupted run on another worker from its last committed checkpoint. Not a restart. |
| Quality finding | A Review Agent output — a gap, contradiction, or unsupported statement proposed for human attention. |

Lifecycle state names in code — `proposed`, `validated`, `rejected`,
`superseded` — are the authoritative set. User-facing labels may differ, as
"confirmed" does for `validated`, but no third vocabulary should appear.

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
- `docs/05_product/UNIFIED_DEMO_NARRATIVE.md` is the **canonical demo story**.
  Where it and any other narrative disagree, it governs.
- `docs/05_product/MVP_SCOPE.md` defines the approved inclusion and exclusion
  boundary for the first release.

These product documents define the intended user experience but do not approve a
frontend framework or authorise implementation by themselves.

## Architecture context

- `deploy/`, `config/`, and `operations/` hold deployment assets, committed
  non-secret configuration, and runbooks. Each is intentionally minimal; see
  `deploy/README.md` for the boundary and for what is deliberately deferred.
- `specifications/` holds the domain, memory, retrieval, agent-execution, API,
  and database specifications and the accepted architecture decisions ADR-0001 to
  ADR-0017.
- `specifications/AGENT_EXECUTION_MODEL.md` defines AgentRun, the run status
  model, idempotency, retry, continuation, and the three agent roles.
- `docs/06_architecture/MCP_ACCESS_POLICY.md` records the inspection-only MCP
  boundary: **all domain writes go through KAE application contracts**.
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
- `docs/09_development/AWS_DEMONSTRATION_BASELINE.md` defines the smallest
  deployment that proves the claim, plus health checks and secrets handling.
- `docs/09_development/PUBLIC_RELEASE_CHECKLIST.md` defines the release and
  judging assets and the milestone by which each must exist.
- `docs/09_development/AI_PROVIDER_AND_COST_CONTROL_CONTEXT.md` gives the context
  needed to extend provider support without turning the demonstration into an
  unbounded cost centre. Load ADR-0010 before implementing anything it describes.

The roadmap is a control plan. Each implementation still requires one approved,
task-specific context with an exact file scope and acceptance criteria.

## KAE with Memory product-shaping context

Load this proposed package after the current MVP memory foundation is understood
and when defining the wider software-development product. It does not supersede
the approved MVP, current agent-role limit, accepted ADRs, or current state page.

- `docs/05_product/KAE_WITH_MEMORY_PRODUCT_VISION.md` defines the wider product
  proposition: KAE acquires, persists, retrieves, and applies shared project
  knowledge while producing real software-engineering outputs.
- `docs/06_architecture/MEMORY_AND_DATA_OPERATING_MODEL.md` defines event,
  knowledge, directive, and execution memory; authority, scope, retrieval,
  versioning, and agent write-back expectations.
- `docs/06_architecture/AGENT_AND_MCP_FUNCTIONAL_MODEL.md` defines the current and
  candidate future agent responsibilities, bounded context and write-back
  contracts, orchestration principles, human gates, and MCP boundaries.
- `docs/02_requirements/KAE_WITH_MEMORY_FUNCTIONAL_REQUIREMENTS.md` provides a
  proposed requirement register and demonstration scenarios for turning the
  memory foundation into an active software-development system.

- `docs/05_product/KAE_WITH_MEMORY_REVIEW_BRIEF.md` is the originating
  instruction for refining the four documents above: the product claim they must
  carry, the framings they must not drift between, the review work required, and
  the acceptance criteria for it. Stored so the review can be checked against
  what was asked. The review was performed on 2026-07-28.
- `docs/05_product/KAE_WITH_MEMORY_ALIGNMENT_REVIEW.md` records the twelve gaps
  between the package and the implemented system. Read it before planning any
  work from the package: three gaps block planning outright.
- `docs/05_product/KAE_WITH_MEMORY_OPEN_QUESTIONS.md` registers OQ-019 onward —
  the product questions whose wrong answers would be expensive to reverse.
- `docs/09_development/KAE_WITH_MEMORY_DEVELOPMENT_PLAN.md` stages the work from
  the current discovery workspace to the wider product, with the ADRs each stage
  needs and the promotion path a proposed requirement must follow.

Use these documents to shape future requirements and ADRs. Do not issue coding
work directly from them until the relevant requirements are approved and reflected
in `CURRENT_PROJECT_STATE.md` and `project-model.yaml`.

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