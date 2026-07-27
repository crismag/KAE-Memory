# KAE-Memory Demo Story and Script

**Status:** proposed hackathon demonstration baseline.

## 1. Demo objective

The demonstration must prove the product outcome first and the technology second.

The audience should understand that KAE-Memory:

1. acquires knowledge from incomplete input;
2. preserves and evolves that knowledge across sessions;
3. detects uncertainty and contradictions;
4. produces a traceable engineering blueprint;
5. uses CockroachDB and AWS as necessary parts of the product experience.

## 2. Demonstration project

Use one stable sample project throughout the demo:

> Replace a ministry reporting binder with a configurable web-based activity,
> reporting, and accountability system.

This scenario is concrete enough to understand quickly but contains realistic
ambiguity around users, reporting cycles, approvals, roles, evidence, and audit.

## 3. Three-minute narrative

### 0:00–0:20 — State the problem

Say:

> Software projects often begin as scattered ideas and conversations. Normal AI
> chats can generate documents, but they do not reliably preserve validated
> project knowledge, corrections, provenance, and workflow state across sessions.

Show the start screen with the prompt: **What are you building?**

### 0:20–0:45 — Start discovery

Enter:

> We want to replace a ministry reporting binder with a web application. Reports
> are normally collected every two weeks, but different reporting categories may
> eventually use different cycles.

Show KAE-Memory creating:

- the original source message;
- proposed product goal;
- proposed reporting rule;
- identified user or workflow gaps;
- initial readiness indicator.

Say:

> KAE does not only answer. It converts the conversation into structured project
> memory and shows what remains unknown.

### 0:45–1:10 — Answer a purposeful question

Show a question such as:

> Who submits a report, and who approves it?

Show the explanation:

> This resolves the approval-workflow gap required before access roles and state
> transitions can be defined.

Answer with a concise role description. Show new actors and workflow knowledge
appearing in the memory panel.

### 1:10–1:35 — Prove persistent memory

Switch to a prepared later session or reopen the project.

Show:

- last completed discovery area;
- prior confirmed reporting-cycle rule;
- next unresolved question;
- sources from the earlier session.

Say:

> This is not prompt history pasted back into a model. CockroachDB is the durable
> project-memory system for conversations, structured knowledge, workflow state,
> provenance, and semantic retrieval.

### 1:35–1:55 — Correct knowledge safely

Change the rule:

> Two weeks is only the current default. The cycle duration must be configured per
> reporting category.

Show:

- old rule marked superseded;
- new rule proposed or confirmed;
- revision relationship;
- dependent requirement flagged for review.

Say:

> KAE evolves memory without deleting history, so agents do not silently continue
> from stale assumptions.

### 1:55–2:15 — Search memory

Search for `reporting cycle`.

Show related:

- original conversation statement;
- corrected knowledge item;
- requirement;
- decision or architecture consequence;
- source link.

Say:

> CockroachDB vector search and structured filters retrieve relevant project
> memory while keeping it scoped to the correct project and status.

### 2:15–2:35 — Run memory audit

Open the quality or audit view and run the Memory Auditor.

Show an MCP-backed finding such as:

- a generated requirement without a confirmed source;
- an active knowledge item missing an embedding;
- a conflicting active rule.

Say:

> A controlled audit agent uses CockroachDB Managed MCP to inspect the memory
> system and returns findings to the application for review.

### 2:35–3:00 — Generate the outcome

Click **Generate Blueprint**.

Show:

- product definition;
- users and workflows;
- requirements;
- architecture summary;
- implementation phases;
- traceability links;
- export action.

Say:

> AWS runs the application and Bedrock-powered agent workflows. CockroachDB stores
> the durable transactional and semantic memory. KAE-Memory turns that foundation
> into a validated, reusable development blueprint.

## 4. Demonstration proof matrix

| Product claim | Visible proof | Enabling system |
| --- | --- | --- |
| KAE acquires knowledge | Structured facts appear from user input | KAE + Bedrock |
| Questions are purposeful | Gap and reason displayed | KAE orchestration |
| Memory persists | Later session resumes correctly | CockroachDB |
| Memory evolves safely | Supersession history is visible | KAE + CockroachDB transaction |
| Retrieval is semantic | Related evidence and outputs appear | Bedrock embeddings + CockroachDB vector index |
| Memory is auditable | MCP-backed finding appears | Managed MCP + KAE auditor |
| Output is useful | Blueprint can be reviewed and exported | KAE + Bedrock + CockroachDB + S3 |

## 5. Prepared demo data

The demo environment should contain:

- one clean project for the live opening flow;
- one prepared project with earlier and later sessions;
- one superseded reporting-cycle rule;
- one unresolved contradiction;
- one meaningful MCP audit finding;
- one generated blueprint with traceability;
- one uploaded source document;
- one export package.

Prepared data is allowed, but the demonstration must include at least one live
write, one live retrieval, and one live generated or audited result.

## 6. Interface language

Prefer user-facing terms:

- Project memory
- Confirmed knowledge
- Needs review
- Unknown area
- Source
- Revision history
- Project readiness
- Generate blueprint

Avoid leading with:

- embeddings;
- vector dimensions;
- SQL tables;
- model temperature;
- orchestration graph;
- queue internals.

These may appear in a technical inspection panel or architecture explanation
after the product value has been established.

## 7. Demo failure strategy

The demo must remain understandable if a live model call is slow or unavailable.

Prepare:

- deterministic seed data;
- cached sample agent outputs clearly identified as demo fallback;
- a retry action;
- visible workflow status;
- a prepared blueprint;
- a short architecture diagram.

Never fake a successful live operation. If fallback data is used, state that the
workflow result was precomputed for demonstration continuity.

## 8. Demo acceptance criteria

The demo is ready when:

- it completes within three minutes without explanation detours;
- the audience sees the user input become structured memory;
- persistence is shown across separate sessions;
- a correction preserves history;
- vector-backed retrieval returns linked evidence;
- Managed MCP produces a visible audit result;
- the final blueprint contains traceable output;
- the roles of KAE, AWS, and CockroachDB can be explained in one sentence each.
