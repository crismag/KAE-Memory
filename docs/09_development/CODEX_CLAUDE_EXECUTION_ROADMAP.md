# Codex and Claude Execution Roadmap

**Status:** proposed development-control plan. This document does not authorise
implementation before the corresponding requirements and architecture decisions
are approved.

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

### Gate A — Product experience approved

Approve:

- product identity;
- first target user;
- primary user journey;
- demo narrative;
- MVP screens;
- visible knowledge states;
- output package.

### Gate B — MVP requirements approved

Requirements must cover:

- project and session creation;
- raw-input persistence;
- structured extraction;
- confirmation and revision;
- cross-session retrieval;
- gap-driven questions;
- blueprint generation;
- memory audit;
- export and traceability;
- failure recovery.

### Gate C — Architecture decisions approved

At minimum, record ADRs for:

1. application boundary and modular shape;
2. backend and frontend technology choices;
3. CockroachDB ownership and memory model;
4. AWS deployment baseline;
5. Bedrock model and embedding integration;
6. workflow orchestration and asynchronous jobs;
7. Managed MCP audit boundary;
8. authentication and tenant isolation;
9. observability and secrets;
10. demo fallback and seed-data strategy.

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

### Slice 0 — Clickable product prototype

**Goal:** validate the user journey before backend implementation.

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

### Slice 1 — Local walking skeleton

**Goal:** prove the application workflow with replaceable adapters.

Deliver:

- project creation;
- message submission;
- raw-input persistence in a local development store;
- deterministic fake extraction adapter;
- discovery workspace reading real API state;
- tests for input durability and idempotency.

The local store is temporary and must not define the final CockroachDB schema.

### Slice 2 — CockroachDB transactional memory

**Goal:** make CockroachDB the authoritative store for the first product slice.

Deliver:

- approved migrations;
- project, session, message, workflow, and knowledge records;
- transaction retry behaviour;
- source traceability;
- integration tests against CockroachDB;
- replacement of the temporary persistence adapter.

### Slice 3 — Bedrock extraction workflow

**Goal:** convert user input into validated candidate knowledge.

Deliver:

- Bedrock adapter;
- versioned structured prompt;
- schema validation;
- agent-run records;
- proposed knowledge UI;
- failure and retry path;
- deterministic test fixtures.

### Slice 4 — Confirmation and supersession

**Goal:** prove trustworthy knowledge evolution.

Deliver:

- confirm, reject, revise, and supersede operations;
- revision history UI;
- transactionally safe active-state changes;
- dependent-output review flags;
- audit records.

### Slice 5 — Semantic memory and return session

**Goal:** prove persistent recall across sessions.

Deliver:

- approved embedding model;
- vector columns and indexes;
- structured and semantic retrieval;
- project and status filters;
- source-aware search results;
- prepared return-session demo.

### Slice 6 — Gap-driven interview

**Goal:** ask the next purposeful question.

Deliver:

- gap records;
- question proposal contract;
- duplicate-question prevention;
- reason-for-asking UI;
- readiness updates;
- workflow tests.

### Slice 7 — Managed MCP Memory Auditor

**Goal:** demonstrate a meaningful second CockroachDB AI tool.

Deliver:

- read-only MCP service account;
- approved query boundary;
- audit-agent workflow;
- structured findings;
- Quality view integration;
- audit logs and failure handling.

### Slice 8 — Blueprint and traceability

**Goal:** produce the customer outcome.

Deliver:

- section-by-section generation;
- grounded, derived, and assumption labels;
- traceability links;
- approval state;
- Markdown export;
- prepared demo blueprint.

### Slice 9 — AWS deployment and asynchronous processing

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

### Slice 10 — Demo hardening

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

### Prompt PX-01 — Product prototype planning

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
> set required for the first walking skeleton. Compare alternatives, record
> consequences, and leave unresolved choices explicit. Do not scaffold code.

### Prompt DEV-01 — Walking skeleton

Issue only after relevant ADR approval.

Objective:

> Implement one vertical path from project creation to saved user message and
> deterministic candidate knowledge shown in the discovery workspace. Use ports
> for persistence and AI extraction so CockroachDB and Bedrock adapters can be
> introduced later without rewriting the application workflow.

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
