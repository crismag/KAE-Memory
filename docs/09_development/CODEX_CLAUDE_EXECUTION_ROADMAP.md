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

The sequence was resequenced on 2026-07-27 and re-ordered again the same day when
the demonstration was confirmed as an agent-collaboration proof. Domain contracts
and knowledge persistence already exist, so persistence is an integration target,
not a greenfield slice. The interface comes **after** the chain it displays.

```text
M4  Repository Realignment
  -> RA-01 Restore Repository Readiness Gates
  -> M5  Persistent Memory Proof
  -> M6  Agent Collaboration
  -> M7  Resilience and Recovery
  -> M8  Semantic Retrieval
  -> M9  Workspace, Review Agent, and Reporting
  -> M10 AWS Demonstration
  -> M11 Demo Ready and Release
```

Memory before agents, agents before resilience, resilience before interface.
There is no point building a workspace to display a chain that has not been
proven.

Slice numbers below map to milestones M4–M11.

### Slice 0 — Repository realignment (M4) ✔ complete

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

### Slice 1 — Persistent memory proof (M5) ✔ complete

**Goal:** prove the memory claim end to end before any interface exists.

Delivered in revision `0002` and `src/kae_memory/application/`. The cross-run
proof is `tests/application/test_cross_run_proof.py`.

Deliver:

- migrations for project, session, message, and AgentRun records, additive to
  revision 0001;
- memory write and structured retrieval through application contracts;
- provenance that resolves to a real AgentRun;
- knowledge expressed with the **existing** domain contracts in
  `src/kae_memory/domain/` — do not define a parallel knowledge model;
- one end-to-end test in which one agent writes and another retrieves in a
  separate run.

**Success condition:** Agent A writes something and Agent B retrieves it in
another run.

**Assistant task boundary:** persistence and contracts only. No UI, no cloud, no
model provider.

### Slice 2 — Agent collaboration (M6) ► current

**Goal:** two agents collaborate through memory rather than conversation. The
persistence and run contracts already exist; this slice gives the roles
behaviour.

**Blocked by:** OQ-012 extraction contract.

Deliver:

- Requirements Agent and Architecture Agent per
  [`../../specifications/AGENT_EXECUTION_MODEL.md`](../../specifications/AGENT_EXECUTION_MODEL.md);
- deterministic extraction adapter behind a port, with fixtures;
- human confirmation, rejection, and revision;
- context assembly that gives the Architecture Agent **confirmed** requirements
  only;
- workflow state recorded on every run.

**Success condition:** the Architecture Agent uses validated requirements created
in an earlier session.

### Slice 3 — Resilience and recovery (M7)

**Goal:** compute becomes disposable. This is the slice the demo is built on.

**Blocked by:** OQ-015 worker runtime and lease mechanism.

Deliver:

- idempotency keys on run submission and knowledge writes;
- bounded retry with backoff, and `abandoned` on budget exhaustion;
- durable run status with lease expiry and reclaim;
- failure simulation in tests — kill the worker mid-run;
- continuation from the last committed checkpoint.

**Success condition:** a new worker resumes after the previous execution stops,
with no duplicated knowledge.

### Slice 4 — Real model extraction (M6)

**Goal:** replace the deterministic adapter with a real provider without changing
the workflow around it.

Deliver:

- provider adapter behind the existing extraction port;
- versioned structured prompt;
- schema validation before any write;
- failure and bounded-retry path per the agent execution model;
- deterministic fixtures retained for tests and demo fallback.

Confirmation, supersession, and AgentRun records are delivered in Slices 2 and 3
and are not repeated here.

### Slice 5 — Workspace, Review Agent, and reporting (M9)

**Goal:** make the proven chain visible as the product.

**Blocked by:** OQ-011 frontend decision and its ADR.

Deliver:

- the discovery workspace over real API state — start, discovery, memory
  explorer, quality, and blueprint views;
- Review Agent and its quality findings;
- revision history and superseded versions visible in the UI;
- project memory summary, agent execution history, traceability, unresolved
  conflicts, validation coverage, and the recovery demonstration report;
- screenshots and demo script captured as screens land, not retrospectively.

The workspace is the product. It is not an agent-control dashboard — the user
sees knowledge, not job queues.

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

### Slice 8 — CockroachDB MCP inspection (M9, optional)

**Goal:** let a judge verify that what the product claims is what the database
holds.

Deliver:

- read-only inspection of schema, plans, and cluster health;
- a scripted inspection sequence for the demonstration;
- least-privilege service account if one is introduced, documented before use.

**Hard boundary:** inspection and management only. No MCP path writes to project
memory, and no agent runtime reads product data through MCP. See ADR-0004 and
[`../06_architecture/MCP_ACCESS_POLICY.md`](../06_architecture/MCP_ACCESS_POLICY.md).

The audit-agent workflow itself is the Review Agent in Slice 5, which reads
through KAE retrieval contracts.

### Slice 9 — Blueprint and traceability (M9)

**Goal:** produce the customer outcome.

Deliver:

- section-by-section generation;
- grounded, derived, and assumption labels;
- traceability links;
- approval state;
- Markdown export;
- prepared demo blueprint.

### Slice 10 — AWS demonstration deployment (M10)

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

### Slice 11 — Demo ready and release (M11)

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

### Prompt RA-01 — Repository realignment ✔ complete

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

### Prompt MEM-01 — Persistent memory proof ✔ complete

Objective:

> Implement project, session, message, and AgentRun persistence additive to
> revision 0001, plus memory write and structured retrieval through application
> contracts. Reuse the existing domain contracts and `KnowledgeRepository`
> protocol in `src/kae_memory/`; do not introduce a second knowledge model.
> Deliver a test in which one agent writes knowledge and another retrieves it in a
> separate run.

Prohibited: UI, cloud services, real model calls.

### Prompt AGENT-01 — Agent collaboration ► next

Blocked on OQ-012, the extraction contract.

Objective:

> Implement the Requirements and Architecture agents per
> `specifications/AGENT_EXECUTION_MODEL.md`, a deterministic extraction adapter
> behind a port, human confirmation, and context assembly that gives the
> Architecture Agent confirmed requirements only. Prove that the Architecture
> Agent consumes requirements confirmed in an earlier session.

Prohibited: additional agent roles, real provider calls, UI.

### Prompt RES-01 — Resilience and recovery

Issue after AGENT-01 review and OQ-015 approval.

Objective:

> Implement idempotency keys, bounded retry with backoff, durable run status with
> lease expiry and reclaim, and continuation from the last committed checkpoint.
> Include a test that terminates a worker mid-run and proves a different worker
> completes it with no duplicated knowledge.

This is the milestone the demonstration rests on. Do not let it slip.

### Prompt AR-01 — Architecture decision set

Objective:

> Convert the accepted requirements into the ADRs the next milestones need — the
> physical schema including AgentRun (OQ-010), the extraction contract (OQ-012),
> the embedding model and index (OQ-014), the worker runtime and lease mechanism
> (OQ-015), the frontend choice (OQ-011), and the AWS runtime (OQ-016). Compare
> alternatives, record consequences, and leave unresolved choices explicit. Build
> on ADR-0001 to ADR-0004 rather than revisiting them. Do not scaffold code.

### Prompt UI-01 — Workspace and reporting

Issue only after the memory, collaboration, and resilience chain is proven and
OQ-011 is decided.

Objective:

> Implement the discovery workspace over real API state, the Review Agent and its
> findings, and reporting generated from operational data. The user sees knowledge
> appearing, questions being asked, and findings being raised — not an agent
> control dashboard.

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
