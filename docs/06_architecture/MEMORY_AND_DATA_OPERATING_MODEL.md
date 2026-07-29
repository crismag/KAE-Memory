# Memory and Data Operating Model

**Status:** proposed product architecture context. Existing domain contracts and accepted ADRs remain authoritative where this document is incomplete or conflicts.

## 1. Objective

Define how KAE captures, stores, governs, retrieves, applies, and evolves project memory so that knowledge is not lost when contexts, sessions, workers, providers, or agents change.

## 2. Four connected memory layers

### Event memory

Records what happened:

- conversations and messages;
- prompts and responses;
- uploaded sources;
- tool calls and outputs;
- repository observations and changes;
- reviews, tests, failures, retries, and approvals;
- agent and user actions.

Event memory is append-oriented evidence. It supports audit, replay, extraction, and explanation.

### Knowledge memory

Records what KAE currently understands:

- facts;
- requirements;
- actors, goals, workflows, and business rules;
- architecture and implementation knowledge;
- constraints, dependencies, risks, and assumptions;
- relationships among artifacts and concepts.

Knowledge is typed, versioned, provenance-aware, and lifecycle governed.

### Directive memory

Records what future work must follow:

- user instructions;
- organisation and project policies;
- approved architecture decisions;
- repository conventions;
- milestone constraints;
- task-specific acceptance criteria and prohibited changes.

Directives require explicit scope and precedence so that a historical suggestion cannot override a current approved instruction.

### Execution memory

Records what allows durable work to continue:

- plans and task state;
- AgentRun status;
- checkpoints and intermediate results;
- claims, leases, fencing tokens, attempts, and retries;
- pending approvals and blocked transitions.

Execution memory enables continuation after process death and prevents transient workers from owning project truth.

## 3. Core data path

```text
Source or project event
  -> Persist verbatim evidence
  -> Extract candidate items
  -> Attach provenance and scope
  -> Classify memory type
  -> Detect duplicates, conflicts, and possible supersession
  -> Validate automatically or request human review
  -> Relate to existing project entities
  -> Index for structured and semantic retrieval
  -> Make eligible for task context assembly
```

No extraction result should replace its source evidence.

## 4. Required memory metadata

Every durable memory item or version should be able to answer:

- What is it?
- Which project owns it?
- What memory class and knowledge type is it?
- Who or what produced it?
- Which source evidence supports it?
- During which session and AgentRun was it created?
- What scope does it apply to?
- What lifecycle state is it in?
- What authority level does it have?
- What confidence or validation evidence exists?
- What relationships connect it to other knowledge and artifacts?
- Is it current, rejected, conflicting, or superseded?
- Which later item replaces it?
- When was it created, reviewed, and last changed?

## 5. Authority and precedence

Retrieval must not rank memories using vector similarity alone. Candidate results should be evaluated using at least:

1. project boundary;
2. applicable scope;
3. lifecycle state;
4. directive authority;
5. explicit user confirmation;
6. decision status;
7. supersession status;
8. structured relationships;
9. semantic relevance;
10. recency where the domain requires it;
11. confidence and supporting evidence;
12. task context budget.

A useful precedence model is:

```text
Current explicit user instruction
  > approved project decision or policy
  > confirmed requirement or validated knowledge
  > current repository fact with evidence
  > proposed knowledge
  > hypothesis or model inference
  > superseded or rejected historical material
```

This is not a universal business rule; exact precedence must remain explicit and testable by memory type and scope.

## 6. Scope hierarchy

Directives and knowledge may apply at different levels:

```text
Organisation
  -> Workspace or tenant
  -> Project
  -> Repository
  -> Component or subsystem
  -> Milestone or release
  -> Task
  -> AgentRun
```

A task-context assembler should combine only applicable scopes and identify conflicts rather than silently choosing when authority is ambiguous.

## 7. Versioning and correction

KAE must not overwrite durable project understanding in place when meaning changes.

Required behaviours:

- preserve prior versions;
- create a new version for substantive changes;
- link superseding and superseded items;
- retain the original source and rationale;
- default retrieval to the active version;
- permit historical and audit queries;
- expose unresolved contradictions;
- avoid treating timestamps alone as correctness.

Example:

```text
K-142: API uses access tokens only
status: superseded
superseded_by: K-287

K-287: API uses short-lived access tokens and rotating refresh tokens
status: validated
source: security review SR-019
```

## 8. Retrieval products

KAE should support several distinct retrieval outputs.

### Evidence retrieval

Returns original conversations, documents, tool output, code excerpts, and other sources.

### Knowledge retrieval

Returns current typed project understanding with provenance and status.

### Directive retrieval

Returns the instructions, policies, decisions, conventions, and acceptance criteria that constrain an action.

### Relationship retrieval

Returns connected requirements, decisions, components, interfaces, tests, risks, and artifacts.

### Task-context assembly

Produces a bounded context package for one agent action. It should include:

- objective;
- applicable directives;
- confirmed requirements;
- relevant architecture and interfaces;
- repository facts;
- known risks, contradictions, and open questions;
- source evidence where needed;
- expected output schema;
- acceptance tests;
- memory-write obligations after completion.

### Explanatory retrieval

Answers questions such as:

- Why does this code exist?
- Which requirement caused this design?
- What changed this rule?
- What would be affected by removing this component?
- Which facts are uncertain or contradictory?

## 9. Memory write-back contract

Every agent that performs meaningful work should return a structured write-back envelope containing, as applicable:

- observations;
- candidate knowledge;
- confirmed repository facts;
- decisions proposed or made;
- artifacts created or changed;
- relationships discovered;
- assumptions introduced;
- conflicts found;
- risks and technical debt;
- tests and evidence;
- unresolved questions;
- execution checkpoint and next action.

Writes must pass through KAE application contracts. Agents and MCP servers must not directly mutate authoritative domain tables.

## 10. Data categories and retention

The system should distinguish:

- authoritative project data;
- raw source evidence;
- generated content;
- transient model context;
- secrets and sensitive data;
- operational telemetry;
- disposable caches.

Retention, export, deletion, and privacy policies are not yet fully defined. Until they are, the design must not assume that all raw prompts, tool outputs, or uploaded documents may be retained indefinitely or shared across projects.

## 11. Project isolation

Project is the minimum durable isolation boundary.

- no cross-project retrieval by default;
- every memory record must carry project ownership;
- semantic search must apply structured project filtering;
- task context must identify its project explicitly;
- future organisation-wide knowledge requires a separate approved model and access policy.

## 12. Quality controls

Memory quality should be measurable through:

- provenance completeness;
- source coverage;
- confirmation status;
- contradiction count and severity;
- stale or superseded retrieval rate;
- unsupported output rate;
- retrieval precision for task-relevant knowledge;
- cross-agent reuse evidence;
- number of user restatements avoided;
- correctness of downstream application.

## 13. CockroachDB role

CockroachDB is the authoritative durable substrate for transactional project state, memory versions, relationships, execution state, and vector-backed retrieval. The product must demonstrate why combined structured filtering, transactions, durability, and semantic indexing are necessary.

CockroachDB MCP remains an inspection and operational-management surface. Domain writes continue to flow through KAE contracts.

## 14. Acceptance proof

The operating model is demonstrated when:

1. a user instruction and its source conversation are persisted;
2. structured knowledge is extracted and validated;
3. a later independent agent retrieves the current validated item;
4. an older conflicting item remains queryable but is not applied as current;
5. the agent output cites or links the memory it used;
6. new implementation knowledge is written back;
7. another phase retrieves that new knowledge without user repetition;
8. a worker interruption does not lose committed memory or execution progress.