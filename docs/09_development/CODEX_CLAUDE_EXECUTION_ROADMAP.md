# Codex and Claude Execution Roadmap

**Status:** active development-control plan, resequenced 2026-07-27 against the
implemented repository. This document does not authorise implementation before
the corresponding requirements and architecture decisions are approved.

Read [`../00_project/CURRENT_PROJECT_STATE.md`](../00_project/CURRENT_PROJECT_STATE.md)
first. It records which milestone is current and which defects block the next
slice.

## 1. Purpose

This roadmap defines how Codex or Claude should assist with KAE-Memory without
turning the repository into an uncontrolled collection of generated code.

The user remains product owner and final approver. AI coding assistants execute
bounded tasks, report evidence, and stop at the defined boundary.

## 2. Operating model

Use one assistant at a time as the primary executor for a task.

Recommended responsibilities:

### ChatGPT / planning workspace

- maintain product direction;
- prepare architecture and task context;
- review repository state;
- define acceptance criteria;
- decide the next bounded milestone.

### Codex or Claude Code

- inspect the repository within the issued scope;
- propose a small implementation plan;
- modify only allowed files;
- add and run tests;
- update task-specific documentation;
- produce a review summary and evidence.

### Human owner

- approve product and architecture decisions;
- provision cloud services and credentials;
- review pull requests;
- run or authorise deployments;
- accept or reject completed milestones.

Do not ask two coding agents to independently edit the same branch or task.
A second agent may review a completed pull request after the first agent stops.

## 3. Required task-context format

Every coding task must include:

- task title and objective;
- business purpose;
- approved requirements;
- relevant product and architecture documents;
- current repository state;
- exact allowed file scope;
- prohibited changes;
- interface or data contracts;
- acceptance criteria;
- required tests;
- commands to run;
- expected deliverables;
- stop conditions;
- open questions that must not be guessed.

Use `docs/10_prompts/TASK_CONTEXT_TEMPLATE.md` as the base format.

## 4. Delivery strategy

Build vertical product slices rather than all infrastructure first.

Each slice should create a visible user outcome while exercising the minimum
necessary parts of KAE, AWS, and CockroachDB.

```text
Product proof
  -> required behaviour
  -> interface contract
  -> architecture decision
  -> bounded implementation task
  -> tests and evidence
  -> demo checkpoint
```

## 5. Planning gates before implementation

### Gate A — Product experience approved ✔ passed

Approved 2026-07-27 by the product-experience documents in `docs/05_product/`:

- product identity;
- first target user;
- primary user journey;
- demo narrative;
- MVP screens;
- visible knowledge states;
- output package.

### Gate B — MVP requirements approved ◐ partially passed

Approved 2026-07-27 in
[`../02_requirements/MVP_REQUIREMENTS_BASELINE.md`](../02_requirements/MVP_REQUIREMENTS_BASELINE.md):

- project and session creation (FR-001, FR-002);
- raw-input persistence (FR-003);
- structured extraction (FR-004);
- confirmation and revision (FR-005);
- supersession without loss (FR-006);
- cross-session retrieval (FR-007);
- blueprint preview with traceability (FR-008).

Still required before the retrieval and demo milestones:

- gap-driven question selection;
- memory audit behaviour;
- export beyond Markdown;
- failure recovery and non-functional targets.

Deferred and not authorised: multi-agent runtime, MCP write operations, advanced
retrieval, document ingestion.

### Gate C — Architecture decisions approved ◐ partially passed

Recorded:

1. ✔ ADR-0001 — memory-first ordering;
2. ✔ ADR-0002 — application boundary and library-first modular shape;
3. ✔ ADR-0003 — SQLAlchemy, Alembic, and psycopg persistence.

Still required, in this order:

4. frontend technology choice (blocks Slice 1, OQ-011);
5. physical schema for projects, sessions, messages, and relationships
   (blocks Slice 2, OQ-010);
6. model provider, prompt contract, and output schema (blocks Slice 2, OQ-012);
   see also OQ-013 readiness model, which blocks Slice 9;
7. AWS deployment baseline;
8. embedding model and index strategy;
9. workflow orchestration and asynchronous jobs;
10. Managed MCP audit boundary;
11. authentication and tenant isolation;
12. observability and secrets;
13. demo fallback and seed-data strategy.

### Gate D — Service provisioning checklist ready

Before launching billable or externally accessible services, document:

- service purpose;
- region;
- cost-control settings;
- credentials and secret storage;
- network access;
- teardown procedure;
- local-development alternative;
- health check.

## 6. Implementation sequence

The sequence below was resequenced on 2026-07-27. Domain contracts and knowledge
persistence already exist, so persistence is no longer a greenfield slice — it is
an integration target.

```text
M4 Repository Realignment
  -> PX-01 UI Planning
  -> PX-02 Clickable Prototype
  -> Walking Skeleton
  -> Application Layer
  -> Persistence Integration
  -> Knowledge Lifecycle
  -> Retrieval
  -> AWS
  -> Demo Hardening
```

Slice numbers map to milestones M4–M10.

### Slice 0 — Repository realignment (M4)

**Goal:** make the repository describe itself accurately and pass its own quality
gate before new feature work starts.

Deliver:

- project model, README, requirements baseline, scope, brief, development plan,
  roadmap, and context index updated to the implemented state;
- `docs/00_project/CURRENT_PROJECT_STATE.md` as the first-loaded context;
- timezone normalisation fix on knowledge rehydration;
- ruff and formatting findings cleared;
- `alembic.ini` and `migrations/env.py` so revision 0001 is executable;
- committed `uv.lock`;
- tests for `run_transaction` retry and exhaustion.

**Exit condition:** `make check` is green on `main`.

**Assistant task boundary:** documentation plus the listed defect fixes. No new
features, tables, endpoints, or services.

### Slice 1 — Clickable product prototype (M5)

**Goal:** validate the user journey before backend implementation.

**Blocked by:** OQ-011 frontend decision and its ADR.

Deliver:

- start screen;
- discovery workspace;
- memory cards;
- readiness explanation;
- quality finding;
- blueprint viewer;
- seeded demo state;
- no production database or model dependency.

This may be a static or locally stateful prototype. It must demonstrate the
three-minute story and reveal missing product rules.

**Assistant task boundary:** UI prototype only. No cloud infrastructure, database
schema, or production agent framework.

### Slice 2 — Walking skeleton (M6)

**Goal:** prove the application workflow end to end with replaceable adapters.

**Blocked by:** OQ-010 physical schema, OQ-012 extraction contract.

Deliver:

- project and session creation;
- message submission;
- raw-input persistence;
- deterministic fake extraction adapter behind a port;
- candidate knowledge expressed with the **existing** domain contracts in
  `src/kae_memory/domain/` — do not define a parallel knowledge model;
- discovery workspace reading real API state;
- tests for input durability and idempotency.

Use the existing `KnowledgeRepository` protocol as the persistence port. A
temporary store, if used, must satisfy that protocol and must not define a new
schema shape.

### Slice 3 — Application layer and persistence integration (M6–M7)

**Goal:** connect the application workflow to the persistence layer that already
exists, and extend it to the entities it still lacks.

The knowledge item and version tables, the SQLAlchemy mapping, the repository,
and the CockroachDB serialization-retry policy are already implemented. This
slice integrates against them rather than rebuilding them.

Deliver:

- migrations for project, session, message, and relationship records, additive to
  revision 0001;
- application services wired to `SqlAlchemyKnowledgeRepository` and
  `run_transaction`;
- relationship persistence for traceability;
- source traceability from blueprint statement to message;
- integration tests against CockroachDB, not only SQLite;
- removal of any temporary store introduced in Slice 2.

**Constraint:** revision 0001 must remain valid. Rewriting it requires an
explicit decision, not an agent's judgement.

### Slice 4 — Bedrock extraction workflow (M6)

**Goal:** convert user input into validated candidate knowledge.

Deliver:

- Bedrock adapter;
- versioned structured prompt;
- schema validation;
- agent-run records;
- proposed knowledge UI;
- failure and retry path;
- deterministic test fixtures.

### Slice 5 — Confirmation and supersession (M7)

**Goal:** prove trustworthy knowledge evolution.

Deliver:

- confirm, reject, revise, and supersede operations;
- revision history UI;
- transactionally safe active-state changes;
- dependent-output review flags;
- audit records.

### Slice 6 — Semantic memory and return session (M8)

**Goal:** prove persistent recall across sessions.

Deliver:

- approved embedding model;
- vector columns and indexes;
- structured and semantic retrieval;
- project and status filters;
- source-aware search results;
- prepared return-session demo.

### Slice 7 — Gap-driven interview (M8)

**Goal:** ask the next purposeful question.

Deliver:

- gap records;
- question proposal contract;
- duplicate-question prevention;
- reason-for-asking UI;
- readiness updates;
- workflow tests.

### Slice 8 — Managed MCP Memory Auditor (deferred)

**Goal:** demonstrate a meaningful second CockroachDB AI tool.

Deliver:

- read-only MCP service account;
- approved query boundary;
- audit-agent workflow;
- structured findings;
- Quality view integration;
- audit logs and failure handling.

### Slice 9 — Blueprint and traceability (M9)

**Goal:** produce the customer outcome.

Deliver:

- section-by-section generation;
- grounded, derived, and assumption labels;
- traceability links;
- approval state;
- Markdown export;
- prepared demo blueprint.

### Slice 10 — AWS deployment and asynchronous processing (M9)

**Goal:** deploy the coherent product slice.

Deliver only the services justified by approved decisions, expected to include:

- ECS Fargate or approved runtime;
- Bedrock;
- S3;
- SQS if long-running work exists;
- Secrets Manager;
- CloudWatch;
- infrastructure-as-code;
- teardown documentation.

Do not provision every proposed AWS service before the application requires it.

### Slice 11 — Demo hardening (M10)

Deliver:

- resettable demo environment;
- stable sample project;
- seed and cleanup commands;
- fallback outputs;
- monitoring checks;
- three-minute rehearsal script;
- public README and architecture diagram;
- submission evidence.

## 7. Initial Codex or Claude task prompts

Do not issue all prompts at once. Issue the next prompt only after the previous
pull request is reviewed and the repository state is updated.

### Prompt RA-01 — Repository realignment ► current

Objective:

> Restore a green `make check` without adding features. Fix timezone
> normalisation when rehydrating knowledge from the database, clear the ruff and
> formatting findings, add `alembic.ini` and `migrations/env.py` so revision 0001
> can be applied and rolled back, commit `uv.lock`, and add tests for
> `run_transaction` retry, backoff, and exhaustion.

Prohibited: new tables, endpoints, services, UI, or model calls.

Expected evidence:

- `make check` output showing all four gates passing;
- `alembic upgrade head` and `alembic downgrade base` output.

### Prompt PX-01 — Product prototype planning

Issue after RA-01 merges and OQ-011 is decided.

Objective:

> Inspect the approved product-experience documents and produce a bounded UI
> prototype plan. Do not implement code. Define routes, components, UI states,
> seeded demo data, accessibility requirements, and a file-level implementation
> proposal. Identify product ambiguities rather than inventing rules.

Expected output:

- `docs/09_development/plans/PX_01_UI_PROTOTYPE_PLAN.md`

### Prompt PX-02 — Clickable prototype

Issue only after PX-01 review and technology approval.

Objective:

> Implement the approved clickable KAE-Memory prototype using only seeded local
> data. Cover the start, discovery, memory, quality, and blueprint views. Do not
> add cloud services, database migrations, authentication, or model calls.

Expected evidence:

- screenshots or recorded interaction;
- component tests;
- accessibility checks;
- demo script walkthrough.

### Prompt AR-01 — Architecture decision set

Objective:

> Convert the accepted requirements and three-system proposal into the minimum ADR
> set required for the first walking skeleton — the frontend choice (OQ-011), the
> physical schema for projects, sessions, messages, and relationships (OQ-010),
> and the extraction contract (OQ-012). Compare alternatives, record consequences,
> and leave unresolved choices explicit. Build on ADR-0001 to ADR-0003 rather than
> revisiting them. Do not scaffold code.

### Prompt DEV-01 — Walking skeleton

Issue only after relevant ADR approval.

Objective:

> Implement one vertical path from project creation to saved user message and
> deterministic candidate knowledge shown in the discovery workspace. Use ports
> for persistence and AI extraction so CockroachDB and Bedrock adapters can be
> introduced later without rewriting the application workflow. Reuse the existing
> domain contracts and `KnowledgeRepository` protocol in `src/kae_memory/`; do not
> introduce a second knowledge model.

## 8. Pull-request expectations

Every implementation PR should include:

- task-context reference;
- summary of behaviour added;
- files changed;
- architecture decisions followed;
- tests executed and results;
- screenshots for UI changes;
- migrations and rollback notes when applicable;
- operational impact;
- deferred items;
- explicit statement that prohibited scope was not changed.

Large mixed PRs should be rejected or split.

## 9. Review strategy

Use a second coding assistant as reviewer only after implementation is complete.
Review for:

- task-scope compliance;
- product-flow coherence;
- hidden invented requirements;
- architecture boundary violations;
- error and retry behaviour;
- security and tenant filtering;
- migration safety;
- test quality;
- demo regressions.

The reviewer should not automatically rewrite the implementation. Findings should
be returned as prioritised review comments or a separate remediation task.

## 10. When to launch services

Launch an external service only when all conditions are met:

1. a user-visible slice requires it;
2. its architecture decision is approved;
3. configuration and teardown are documented;
4. secrets are stored correctly;
5. cost controls are understood;
6. a local or fake adapter exists for tests;
7. acceptance tests are defined.

Likely service order:

1. CockroachDB development cluster and migration access
2. Bedrock model access
3. S3 bucket for source and export objects
4. Secrets Manager
5. application runtime
6. SQS when asynchronous work becomes necessary
7. CloudWatch dashboards and alarms
8. Managed MCP read-only service account

The exact order may change after ADR approval.

## 11. Definition of successful assistance

Codex or Claude is helping successfully when:

- each task advances one visible product proof;
- changes remain reviewable;
- tests demonstrate behaviour rather than only code coverage;
- architecture choices are not silently invented;
- cloud services are not launched prematurely;
- context remains traceable from product need to code;
- the three-minute demo becomes more complete after every accepted slice.
