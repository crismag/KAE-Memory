# Agent and MCP Functional Model

**Status:** proposed future product model. The current approved agent-role set and accepted ADRs remain authoritative for the MVP.

## 1. Objective

Define how specialised agents should collaborate through persistent KAE memory and how MCP servers may expose tools and external systems without bypassing KAE governance.

## 2. Agent collaboration principle

Agents do not own project truth and should not depend on private conversational handoffs. They collaborate through durable application contracts and shared project memory.

```text
Agent receives bounded task context
  -> Reads applicable memory
  -> Performs one defined responsibility
  -> Produces structured artifacts and findings
  -> Writes results through KAE services
  -> Checkpoints execution state
  -> Makes new knowledge available to later agents
```

Every agent must be replaceable without losing project continuity.

## 3. Current MVP roles

The current implementation authorises three roles:

- Requirements Agent;
- Architecture Agent;
- Review Agent.

These roles prove cross-run collaboration, quality findings, and durable project understanding. This document does not silently add runtime roles to the approved MVP.

## 4. Candidate future roles

The full KAE product may introduce the following roles after requirements, boundaries, and ADRs are approved.

### Discovery Agent

Purpose: guide product and business discovery.

Consumes:

- idea statements;
- conversations;
- documents;
- current unknowns and contradictions.

Produces:

- actors, goals, workflows, constraints, assumptions, questions, and source links.

### Requirements Agent

Purpose: produce testable functional and non-functional requirements.

Consumes:

- validated discovery knowledge;
- policies and constraints;
- prior requirements and changes.

Produces:

- versioned requirements;
- acceptance criteria;
- dependencies, conflicts, and coverage gaps.

### Architecture Agent

Purpose: define coherent system boundaries, interfaces, data responsibilities, and decisions.

Consumes:

- confirmed requirements;
- project constraints;
- repository and platform knowledge;
- active decisions and risks.

Produces:

- architecture context;
- ADR proposals;
- component and interface definitions;
- trade-offs and unresolved questions.

### Planning Agent

Purpose: convert approved requirements and architecture into executable slices.

Produces:

- milestones;
- dependency-aware tasks;
- bounded file scope;
- expected artifacts;
- acceptance and verification steps.

### Repository Understanding Agent

Purpose: inspect an existing repository and build structured implementation knowledge.

Produces:

- component inventory;
- dependency and ownership relationships;
- conventions and patterns;
- code-to-requirement mappings;
- risks, unknowns, and stale documentation findings.

### Implementation Agent

Purpose: perform one bounded code or configuration change.

Consumes:

- one issued task context;
- applicable directives;
- relevant requirements, architecture, interfaces, repository facts, and tests.

Produces:

- changed artifacts;
- implementation summary;
- discovered constraints;
- updated relationships;
- validation evidence;
- explicit deviations and open issues.

### Test Agent

Purpose: design and execute verification grounded in requirements and implementation facts.

Produces:

- test cases and fixtures;
- requirement coverage;
- failures and diagnostic evidence;
- candidate defects and regressions.

### Review Agent

Purpose: evaluate consistency, quality, traceability, risk, and readiness.

Consumes:

- requirements;
- decisions;
- implementation changes;
- tests and evidence;
- active project policies.

Produces:

- quality findings;
- contradictions;
- unsupported statements;
- missing coverage;
- release blockers and recommendations.

### Knowledge Curator Agent

Purpose: consolidate validated discoveries and improve memory quality without erasing evidence.

Produces:

- deduplication proposals;
- relationship enrichment;
- supersession proposals;
- stale-knowledge findings;
- summaries that retain provenance.

This role must not silently promote uncertain material to validated knowledge.

### Release and Operations Agent

Purpose: prepare deployment, runbooks, release evidence, and operational readiness.

Produces:

- deployment plans;
- environment and configuration requirements;
- health checks;
- rollback and recovery procedures;
- release reports.

## 5. Role boundaries

Each role requires:

- a defined purpose;
- permitted input memory classes;
- allowed tools;
- expected output schema;
- write-back obligations;
- approval gates;
- failure and retry semantics;
- measurable acceptance criteria.

A role must not be introduced only because a new prompt is convenient. New roles should represent a durable responsibility with distinct contracts and evidence.

## 6. Agent context contract

Every agent invocation should receive a context envelope containing:

- project, session, task, and AgentRun identifiers;
- role and objective;
- applicable instructions and authority ordering;
- retrieved knowledge with status and provenance;
- relevant evidence and artifacts;
- known contradictions and unresolved questions;
- tool permissions;
- expected structured output;
- completion and checkpoint rules;
- context budget and retrieval explanation.

The envelope should allow the system to show exactly what the agent knew before acting.

## 7. Agent write-back contract

Every completion or checkpoint should return:

- status and progress;
- outputs and artifact references;
- knowledge candidates;
- validated observations with evidence;
- relationships created or changed;
- assumptions and confidence;
- conflicts and risks;
- tests or validation performed;
- next recommended action;
- safe continuation state.

Unstructured prose may be stored as event evidence, but operational use should depend on validated structured results.

## 8. Orchestration model

KAE orchestration should be state-driven rather than a fixed prompt chain.

```text
Project state
  -> Determine highest-value eligible action
  -> Assemble bounded context
  -> Run specialised agent
  -> Validate and persist output
  -> Recalculate project state, readiness, and blockers
  -> Select next eligible action or request human decision
```

Transitions should depend on durable state, not on one process retaining the conversation.

## 9. Human control points

Human approval should remain available for:

- confirming or rejecting requirements;
- accepting architecture decisions;
- resolving contradictory directives;
- approving destructive or high-risk repository changes;
- accepting security, privacy, or cost trade-offs;
- promoting uncertain knowledge to authoritative status;
- approving release readiness.

The eventual product may support configurable autonomy, but autonomy must not remove provenance, auditability, or safe interruption.

## 10. MCP purpose

MCP may provide standard tool interfaces between KAE agents and external systems. It should be treated as an integration protocol, not as the product's memory or governance layer.

Candidate MCP categories include:

- repository and source-control access;
- issue and project-tracking access;
- documentation and knowledge-source access;
- cloud and deployment inspection;
- database documentation and operational inspection;
- model-provider tools;
- test and build systems;
- local filesystem and development tools.

## 11. MCP access policy

MCP integrations should follow least privilege and explicit capability boundaries.

### Read and inspect

An MCP may read approved external information and return evidence to KAE.

### Propose

An MCP-backed agent may propose a change and store the proposal in KAE memory.

### Execute

An MCP may perform an external mutation only when the agent role, task, user approval, and connector contract explicitly authorise it.

### Domain writes

No MCP should directly write KAE authoritative domain tables. KAE memory writes must use application contracts so validation, provenance, versioning, lifecycle, and transaction rules are applied.

## 12. Candidate MCP integrations

### CockroachDB Docs MCP

Use for current product documentation, SQL features, operational guidance, and implementation research.

### CockroachDB Cloud MCP

Use for approved cluster inspection and operational management. Do not use as a bypass around KAE repositories and services.

### GitHub MCP or connector

Use for repository reading, branch and pull-request operations, issue context, commits, checks, and artifact links. Repository writes require bounded task scope and reviewable change sets.

### AWS documentation or operations MCP

Use for approved service inspection, deployment actions, logs, health evidence, and infrastructure operations. Credentials and destructive operations require explicit controls.

### Filesystem and development-tool MCP

Use for local inspection, builds, tests, formatting, static analysis, and bounded file changes. Results should be captured as execution evidence.

### Project-management MCP

Potentially use for Jira, Linear, GitHub Issues, or other work systems. KAE should preserve external identifiers and synchronisation provenance rather than treating an external task title as sufficient project knowledge.

## 13. Tool-result handling

Tool results should be persisted with:

- invocation identity;
- tool and connector version where available;
- input parameters with secrets redacted;
- timestamp and actor;
- success or failure state;
- raw or referenced output;
- extracted project knowledge;
- relationships to the task and AgentRun.

Large or sensitive results may require references, chunking, retention limits, or redaction rather than unlimited raw storage.

## 14. Security boundaries requiring later definition

Before broad agent execution, KAE needs explicit policies for:

- credential storage and rotation;
- connector permissions;
- code execution isolation;
- network access;
- untrusted repository content and prompt injection;
- sensitive-data classification;
- destructive operations;
- tenant and project isolation;
- audit retention;
- human approval and emergency stop.

## 15. Demonstration acceptance

The agent model is convincingly demonstrated when:

1. one agent acquires and persists knowledge from user input;
2. another agent in a separate run retrieves it through KAE services;
3. the second agent applies it to a real artifact or implementation task;
4. its retrieved context is visible and bounded;
5. its result writes new structured knowledge back;
6. a later review or test agent uses that new knowledge;
7. the system preserves evidence, versions, conflicts, and execution state;
8. no direct agent-to-database shortcut is required.