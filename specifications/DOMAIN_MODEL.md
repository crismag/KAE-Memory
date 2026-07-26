# Domain Model

**Status:** proposed conceptual model; physical persistence is not approved.

## Core entities

### Project
Durable boundary for one software initiative. Owns project identity, status, participants, policies, and references to its knowledge graph.

### KnowledgeItem
Generic durable unit of project knowledge. Carries type, content reference, provenance, lifecycle state, confidence where applicable, version, and relationships.

### Evidence
Observed source material supporting or contradicting a claim. Evidence is append-oriented and should not be rewritten to match later interpretations.

### Requirement
A testable business, user, functional, non-functional, data, integration, or security expectation.

### Decision
An approved choice with context, alternatives, rationale, consequences, owner, and status.

### Task
A bounded unit of implementation or analysis work linked to requirements and architecture.

### Artifact
A file, document, code change, test result, diagram, or external reference produced or consumed by project work.

### Agent
A registered AI or human-controlled agent identity with role, capabilities, permissions, provider metadata, and version.

### Execution
One invocation of an agent or workflow, including input context, outputs, tool actions, status, and failure details.

### ContextBundle
A bounded, reproducible selection of project knowledge assembled for a declared consumer and purpose.

### Relationship
A typed edge between domain entities, such as supports, contradicts, derives-from, implements, validates, supersedes, or blocks.

### Snapshot
A reproducible view of selected project state at a meaningful boundary or release point.

## Key invariants

1. Every durable item belongs to exactly one project.
2. Every agent-produced item identifies the agent and execution that created it.
3. Engineering history is not silently overwritten.
4. Supersession identifies both the old and replacement item.
5. Validation state is explicit and separate from confidence.
6. Evidence and interpretation remain distinguishable.
7. Trace relationships are typed and independently auditable.
8. A context bundle records the query, policy, selected items, versions, and assembly time.

## Ownership boundaries

- Project owns project-level policy and identity.
- Knowledge lifecycle management owns KnowledgeItem versions and state transitions.
- Traceability owns Relationship validity.
- Agent registry owns Agent identity and capabilities.
- Execution tracking owns Execution records.
- Context assembly owns ContextBundle construction, not source truth.

## Open modelling decisions

- Whether specialised entities inherit from or reference KnowledgeItem
- Aggregate and transaction boundaries
- Immutable versus mutable fields
- Multi-tenancy boundary
- Retention and deletion semantics
- Granularity of versions and snapshots
- Representation of large artefacts and external content
