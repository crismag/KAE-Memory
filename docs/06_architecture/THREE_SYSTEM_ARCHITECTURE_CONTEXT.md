# KAE-Memory Three-System Architecture Context

**Status:** proposed architecture context; not yet approved for implementation.

## Purpose

This document records the proposed end-to-end architecture for the CockroachDB AI hackathon implementation of KAE-Memory. It is intended to guide requirements review, architecture decisions, task decomposition, implementation planning, and demo preparation.

It does not override the repository's controlled-bootstrap rules. Frameworks, service boundaries, schemas, APIs, and infrastructure become implementation-authoritative only after the related requirements and architecture decisions are approved.

## Project statement

KAE-Memory is an agentic knowledge-acquisition application that transforms incomplete project ideas, conversations, documents, corrections, and decisions into structured, searchable, validated, and reusable project memory.

The application should interview users, extract candidate knowledge, identify gaps and contradictions, retrieve relevant prior context, preserve revisions, and generate traceable project artefacts such as requirements, architecture plans, and development task contexts.

## Architecture objective

The hackathon design must meaningfully exercise three systems:

1. the KAE-Memory software application;
2. AWS services;
3. CockroachDB and its agent-oriented capabilities.

Each system must have a necessary, visible responsibility. CockroachDB must not be used only as a generic relational database, AWS must not be used only as static hosting, and the language model must not replace the application's business rules and workflow control.

```text
KAE-Memory
  owns product behaviour, orchestration, validation, and user experience

AWS
  supplies runtime, model inference, queues, files, secrets, and monitoring

CockroachDB
  supplies durable transactional, semantic, operational, and audit memory
```

## System context

```text
User
  |
  v
KAE-Memory Web Application
  |
  v
KAE API and Workflow Orchestrator on AWS
  |                         |
  |                         +--> Amazon Bedrock
  |                              reasoning, extraction, embeddings
  |
  +--> Amazon SQS
  |    durable asynchronous jobs
  |
  +--> Amazon S3
  |    uploaded documents and exported packages
  |
  +--> CockroachDB Cloud
       project state, messages, knowledge, vectors,
       workflow state, artefacts, provenance, and audit history
       |
       +--> Distributed Vector Indexing
       +--> Managed MCP Server
       +--> optional CockroachDB Agent Skills
```

## System 1: KAE-Memory application

KAE-Memory owns all product and workflow decisions.

### Responsibilities

- project and session management;
- guided interviews;
- message handling;
- workflow orchestration;
- agent routing;
- prompt and context construction;
- structured-output validation;
- knowledge lifecycle management;
- gap and contradiction workflows;
- user confirmation and correction;
- traceability;
- blueprint generation;
- readiness calculation;
- export and audit presentation.

### Non-responsibilities

KAE-Memory must not:

- treat raw model output as authoritative;
- delegate project-state ownership to an LLM;
- store durable workflow state only in process memory;
- bypass tenant and project filters during retrieval;
- delete historical knowledge when it is corrected;
- allow unrestricted agent writes to CockroachDB.

### Central orchestrator

The first implementation should use a deterministic central orchestrator rather than unrestricted autonomous agents.

The orchestrator should:

- persist raw input before model calls;
- select the next workflow step;
- load bounded context;
- invoke the correct specialist capability;
- validate structured responses;
- enforce state transitions;
- control retries and idempotency;
- persist execution history;
- require approval before authoritative state changes.

Agents may propose changes. The orchestrator validates and persists them.

## System 2: AWS

AWS provides active runtime and AI capabilities.

### Proposed services

#### Amazon ECS Fargate

Runs:

- the KAE API container;
- the KAE background-worker container;
- optionally the web frontend.

#### Amazon Bedrock

Provides:

- interview-question generation;
- knowledge extraction;
- gap analysis;
- contradiction analysis;
- requirements and architecture synthesis;
- embedding generation.

#### Amazon S3

Stores:

- original uploaded documents;
- exported Markdown packages;
- generated ZIP archives;
- supporting demo artefacts.

CockroachDB stores the corresponding metadata, processing state, source links, and object references.

#### Amazon SQS

Provides durable job delivery for:

- document ingestion;
- embedding generation;
- knowledge extraction;
- validation;
- blueprint generation;
- memory audits.

#### AWS Secrets Manager

Stores database credentials, MCP credentials, signing secrets, and external service secrets.

#### Amazon CloudWatch

Captures application logs, worker logs, model latency, queue failures, workflow errors, and operational metrics.

### AWS architectural contract

AWS performs computation and infrastructure functions, but it is not the authoritative project-memory system. Durable project state and knowledge remain in CockroachDB.

## System 3: CockroachDB

CockroachDB is the authoritative persistent-memory substrate.

### Memory responsibilities

CockroachDB should store:

- users, organisations, projects, and versions;
- sessions and raw messages;
- document metadata and extracted chunks;
- candidate and confirmed knowledge;
- requirements, assumptions, decisions, constraints, and risks;
- questions, answers, gaps, and contradictions;
- vector embeddings;
- agent runs, tool calls, and workflow state;
- artefacts and artefact versions;
- provenance, traceability, supersession, and audit records;
- asynchronous job and outbox state.

### Transactional memory

Related authoritative changes should be committed atomically. Examples include:

- message persistence with creation of its processing work item;
- confirmation of knowledge with resolution of its source gap;
- supersession of an old fact with activation of its replacement;
- publication of an artefact version with its traceability links.

CockroachDB serialisable transaction conflicts must be handled with bounded retries.

### Semantic memory

CockroachDB Distributed Vector Indexing should support retrieval across:

- messages;
- document chunks;
- knowledge items;
- requirements;
- decisions;
- artefact sections.

Vector search must be combined with structured filters such as organisation, project, version, status, memory type, and permissions.

### Operational and audit memory

The database should preserve:

- current workflow step;
- retry count;
- last successful step;
- failed and dead-lettered jobs;
- model and prompt versions;
- memories retrieved for each run;
- tool calls;
- approvals, corrections, and state changes.

## Required CockroachDB capabilities

### Distributed Vector Indexing

Proposed retrieval flow:

```text
Current request
  -> Bedrock embedding
  -> CockroachDB project-filtered vector search
  -> structured and semantic ranking
  -> relationship and source expansion
  -> bounded context
  -> grounded Bedrock response
```

The purpose is to demonstrate that structured operational records and semantic memory can be stored and queried in one system.

### Managed MCP Server

The initial meaningful MCP use case should be a read-only Memory Auditor Agent.

The auditor should inspect the CockroachDB-backed memory system for:

- orphaned knowledge records;
- missing provenance links;
- duplicate active facts;
- missing embeddings;
- failed or incomplete workflow runs;
- unsupported generated requirements;
- conflicting active decisions;
- incomplete artefact traceability.

The KAE application should validate and store the auditor's findings before presenting them to the user. Controlled write access should be deferred until permission, validation, auditing, and rollback policies are approved.

### Optional Agent Skills

CockroachDB Agent Skills may later assist with schema review, query review, index analysis, and operational guidance. This is supplementary and must not delay vector and MCP integration.

## Primary end-to-end workflow

```text
Create project
  -> persist project, version, session, and workflow state

Submit incomplete idea
  -> persist raw message before model execution
  -> create outbox or processing work item
  -> publish asynchronous job

Retrieve memory
  -> load structured project state
  -> perform project-filtered vector search
  -> expand provenance and relationships
  -> build bounded agent context

Extract knowledge
  -> invoke Bedrock
  -> validate structured output
  -> store candidate knowledge with source and confidence

Analyse quality
  -> identify gaps, ambiguity, contradictions, and assumptions
  -> choose the next highest-value question

Confirm or correct
  -> user confirms, rejects, or revises candidate knowledge
  -> supersede prior records without deleting history

Generate blueprint
  -> use confirmed knowledge
  -> generate sections through Bedrock
  -> validate completeness and traceability
  -> store versioned artefacts in CockroachDB
  -> export package to S3

Audit memory
  -> invoke MCP-backed Memory Auditor
  -> persist and display findings
```

## Detailed behavioural flows

### Project creation

1. Validate project input.
2. Create project, initial version, owner membership, initial session, and workflow state in one transaction.
3. Return the project workspace only after commit succeeds.

### Message processing

1. Persist the raw user message.
2. Create an outbox or processing record in the same transaction.
3. Publish or process an SQS job.
4. Retrieve relevant project memory.
5. Invoke Bedrock.
6. Validate returned structured data.
7. Store candidate knowledge and execution history.
8. Determine the next workflow action.

A model failure must never cause loss of the original message.

### Guided interview

The interview must be gap-driven rather than only questionnaire-driven.

The Interview Agent may propose a question, but the orchestrator must validate it against:

- discovery stage;
- unresolved gaps;
- prior answers;
- duplicate-question history;
- contradiction state;
- user corrections;
- question priority.

Every question should reference the gap it addresses and the reason it is being asked.

### Knowledge extraction and lifecycle

Proposed lifecycle:

```text
Captured
  -> Extracted
  -> Proposed
  -> Validated
  -> Confirmed
  -> Superseded or Archived
```

No model confidence score may automatically promote a candidate to confirmed knowledge.

Every knowledge item should preserve:

- project and version;
- type and structured content;
- human-readable representation;
- source message or document chunk;
- extraction run;
- confidence;
- lifecycle status;
- revision and supersession links;
- embedding where applicable.

### Knowledge correction

1. Retrieve the active record.
2. Create a proposed replacement.
3. Confirm the replacement through user approval or an approved validation policy.
4. In one transaction, supersede the old record, activate the replacement, link both records, create an audit event, and flag dependent artefacts for review.
5. Generate and store the replacement embedding.

The old and new values must remain visible.

### Hybrid retrieval

Retrieval should combine:

- exact project and permission filters;
- structured queries for active requirements, decisions, constraints, gaps, and workflow state;
- semantic vector search;
- relationship and provenance expansion;
- context-budget selection.

Ranking may consider semantic similarity, confirmation status, source reliability, recency, workflow-stage relevance, and explicit relationship strength.

### Document ingestion

1. Upload original file to S3.
2. Store attachment metadata in CockroachDB.
3. Publish an SQS ingestion job.
4. Extract and chunk text.
5. Generate embeddings with Bedrock.
6. Store chunks, vectors, and source relationships in CockroachDB.
7. Extract candidate knowledge.
8. Present uncertain interpretations for confirmation.

Every derived knowledge item must trace to its source document and chunk.

### Blueprint generation

The generated package may include:

- project and product definition;
- users and use cases;
- functional and non-functional requirements;
- constraints and exclusions;
- domain model and workflows;
- architecture and data model;
- API and security plans;
- implementation phases and test strategy;
- traceability links;
- task-specific agent contexts.

The generation workflow must use confirmed knowledge by default. Unconfirmed content must be clearly labelled as an assumption.

Every generated requirement must link to supporting knowledge or be marked for confirmation.

## Proposed specialist agents

- **Interview Agent:** proposes the next highest-value question.
- **Knowledge Extraction Agent:** produces structured candidate knowledge.
- **Gap Analysis Agent:** finds missing or incomplete information.
- **Contradiction Agent:** identifies incompatible active statements.
- **Validation Agent:** checks whether claims are supported.
- **Architecture Agent:** drafts and reviews architecture content.
- **Blueprint Synthesis Agent:** generates structured project artefacts.
- **Memory Auditor Agent:** uses Managed MCP to inspect persistent memory.

All agents must return structured output, identify supporting evidence, use bounded context, and record model, prompt, and retrieved-memory references.

## Proposed memory categories

- **Working memory:** temporary context for the current execution.
- **Episodic memory:** conversations and past agent interactions.
- **Semantic memory:** confirmed facts, rules, requirements, and definitions.
- **Decision memory:** accepted decisions, alternatives, and rationale.
- **Procedural memory:** prompts, workflows, schemas, and agent skills.
- **Artefact memory:** generated documents and versions.
- **Audit memory:** approvals, changes, retries, failures, and system actions.

## Proposed data domains

The exact schema remains an architecture decision, but the design must account for these ownership areas:

```text
Identity
  users, organisations, memberships

Projects
  projects, project members, project versions

Conversations
  sessions, messages, message parts, attachments

Knowledge
  knowledge items, relationships, sources, revisions

Discovery
  questions, responses, gaps, ambiguity, contradictions, assumptions

Requirements and decisions
  requirements, acceptance criteria, constraints, risks, decisions, options

Agent workflows
  agents, runs, steps, tool calls, workflows, events

Artefacts
  artefacts, versions, sections, traceability links

Operations
  audit events, outbox events, jobs, dead-letter jobs
```

## Proposed user interface

The hackathon MVP should visibly demonstrate the memory architecture through:

- a project dashboard;
- a guided interview screen;
- a memory explorer showing status, source, confidence, and revisions;
- a knowledge-quality screen for gaps, contradictions, assumptions, and audit findings;
- a blueprint viewer with traceability and export controls.

## Reliability constraints

- Persist raw user input before invoking a model.
- Use idempotency for user and worker requests.
- Store workflow state durably.
- Use an outbox pattern for state changes that trigger asynchronous work.
- Retry serialisable transaction conflicts safely.
- Retain failed asynchronous work for diagnosis and retry.
- Avoid duplicate messages, knowledge items, workflow runs, and artefact versions.

## Security and trust boundaries

Initial roles may include Owner, Editor, Reviewer, Viewer, and Service Agent.

Every project-owned query must apply organisation and project ownership filters.

Separate credentials should be used for:

- application runtime;
- database migrations;
- read-only MCP auditing;
- any future controlled-write maintenance agent.

Secrets belong in AWS Secrets Manager and must not be committed, logged, embedded, or exposed in demo material.

The system should record who initiated an action, which agent and model executed it, which memories were used, what changed, and why.

## Observability

Each agent execution should record:

- workflow and agent identity;
- model and prompt version;
- start, finish, and latency;
- token or usage metrics where available;
- retrieved memory IDs;
- tool calls;
- validation result;
- retries and errors.

Useful metrics include queue depth, processing latency, vector-search latency, workflow failure rate, model failure rate, proposed-to-confirmed knowledge ratio, unresolved contradiction count, and artefact validation failures.

## Provisional technology mapping

The following is a proposed mapping, not an approved implementation decision:

| Area | Proposed technology |
| --- | --- |
| Web frontend | React or Next.js |
| Backend API | Python FastAPI |
| Worker | Python worker consuming Amazon SQS |
| Orchestration | Deterministic application state machine |
| Model runtime | Amazon Bedrock |
| Embeddings | Amazon Bedrock embedding model |
| Durable memory | CockroachDB Cloud |
| Semantic retrieval | CockroachDB Distributed Vector Indexing |
| Agent database access | CockroachDB Managed MCP Server |
| Binary files | Amazon S3 |
| Runtime | Amazon ECS Fargate |
| Secrets | AWS Secrets Manager |
| Monitoring | Amazon CloudWatch |
| Infrastructure | Terraform |

Each selection requires approval through the repository's requirements and ADR process.

## Implementation milestones

### Milestone 1: three-system foundation

Prove a browser request can reach KAE on AWS, invoke Bedrock, and persist authoritative state in CockroachDB.

### Milestone 2: persistent semantic memory

Prove a fact captured in one session can be retrieved in a later session with its source.

### Milestone 3: structured knowledge lifecycle

Prove candidate knowledge can be confirmed, rejected, revised, and superseded without losing history.

### Milestone 4: guided discovery

Prove the next interview question is selected from unresolved project gaps and is not a generic duplicate.

### Milestone 5: MCP memory audit

Prove a read-only Memory Auditor uses Managed MCP and displays a validated finding in KAE.

### Milestone 6: document ingestion

Prove an S3 document is processed asynchronously, embedded through Bedrock, stored and retrieved through CockroachDB, and traced to its source chunk.

### Milestone 7: blueprint generation

Prove generated requirements and architecture artefacts are versioned and traceable to confirmed knowledge.

### Milestone 8: demo hardening

Provide resettable sample data, deployment documentation, error handling, monitoring, public setup instructions, and a concise demonstration script.

## MVP boundary

The initial hackathon release should include:

- project creation;
- guided interview;
- durable message storage;
- Bedrock reasoning and embeddings;
- structured knowledge extraction;
- confirmation, correction, and supersession;
- hybrid and cross-session retrieval;
- memory explorer;
- gap or contradiction analysis;
- MCP-backed memory audit;
- blueprint generation;
- S3 export;
- AWS deployment.

The initial release should exclude unrestricted autonomy, direct repository modification, billing, mobile applications, broad external integrations, multi-region deployment, local-model support, and advanced knowledge-graph visualisation.

## Demo scenario

Use one consistent project idea:

> Replace a ministry reporting binder with a configurable web-based activity, reporting, and accountability system.

The demo should show:

1. project creation;
2. an incomplete initial description;
3. targeted interview questions;
4. structured knowledge extraction;
5. persistent memory records and sources;
6. cross-session recall;
7. correction of the reporting-cycle rule;
8. visible supersession history;
9. gap or contradiction detection;
10. an MCP-backed memory audit;
11. generation of a traceable project blueprint;
12. export to S3.

## Definition of done for this architecture direction

The design is successfully exercised when:

- KAE business logic remains separate from infrastructure adapters;
- AWS performs application execution and model inference;
- CockroachDB holds durable transactional, semantic, operational, and audit memory;
- vector retrieval returns relevant project-scoped memories;
- Managed MCP performs a meaningful audit workflow;
- raw input survives model and worker failure;
- knowledge can be corrected without deleting history;
- generated artefacts are traceable to source knowledge;
- a new session can retrieve prior confirmed knowledge;
- the deployed demo visibly exercises all three systems.

## Non-negotiable rules

1. Persist user input before model execution.
2. Never treat model output as automatically authoritative.
3. Require structured agent outputs.
4. Preserve provenance and traceability.
5. Preserve revision and supersession history.
6. Apply tenant and project filters to every retrieval.
7. Keep workflow state durable.
8. Use transactions for related authoritative changes.
9. Record agent and tool activity.
10. Keep KAE central to workflow control.
11. Keep AWS central to runtime and AI execution.
12. Keep CockroachDB central to persistent agent memory.

## Required follow-on architecture decisions

Before implementation tasks are issued, create or approve ADRs for at least:

- system and trust boundaries;
- application language and framework;
- deployment topology;
- synchronous and asynchronous workflow split;
- CockroachDB data and tenancy model;
- knowledge provenance and supersession model;
- retrieval and embedding model;
- Bedrock model selection;
- MCP permissions and audit policy;
- S3 document-handling and retention policy;
- API contracts and typed errors;
- transaction, idempotency, retry, and outbox strategy;
- observability and sensitive-data policy.
