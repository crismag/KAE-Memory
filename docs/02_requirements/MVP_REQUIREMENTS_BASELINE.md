# MVP Requirements Baseline

**Status:** approved for implementation, 2026-07-27.

This baseline approves the minimum set of requirements needed to authorise the
first end-to-end product slice. It deliberately approves less than the full
product. Anything not listed under "Approved MVP requirements" is not authorised,
and a coding agent must not implement it.

## Established constraints

- The platform must address persistent, long-term AI engineering collaboration.
- Human owners retain requirements validation, architecture approval, final
  technical decisions, and quality assurance.
- Development proceeds incrementally in vertical, independently verifiable
  slices.
- The `crismag/KAE-Memory` repository is the implementation target.
- The first release must prove persistent shared memory as the foundation for
  multi-agent engineering collaboration.

## Approved MVP requirements

Each requirement below is authorised for implementation. Identifiers match
`project-model.yaml`.

### FR-001 — Project

A user can create a durable project from an incomplete idea and reopen it later
by stable identifier. A project owns all knowledge, sessions, and outputs derived
within it. No cross-project reads.

*Acceptance:* a project created in one session is retrievable in another with its
identity and creation provenance intact.

### FR-002 — Session

Work is grouped into sessions belonging to a project. A new session resumes from
durable project state and shows what was previously established, what changed,
and what remains uncertain.

*Acceptance:* AT-003.

### FR-003 — Message

Every user submission is persisted verbatim as source evidence before any
interpretation occurs. The stored text is never rewritten by extraction.

*Acceptance:* AT-001. A stored message is byte-identical to what was submitted.

### FR-004 — Knowledge

Submitted input produces typed candidate knowledge items. Every knowledge version
carries provenance identifying its source, actor, and execution. History is
append-oriented; prior versions are never overwritten.

*Acceptance:* AT-001. Each candidate resolves to the message that produced it.

### FR-005 — Confirmation

A human can confirm, reject, or revise candidate knowledge. Status is visible in
the interface using the labels proposed, confirmed, needs review, conflicting,
and superseded. Model confidence may be shown as supporting information but never
substitutes for confirmation.

*Acceptance:* AT-002. Invalid lifecycle transitions return a typed error.

### FR-006 — Supersession

Correcting knowledge marks the prior version superseded and keeps it retrievable.
Deletion is not part of the MVP correction path.

*Acceptance:* AT-002. Both the superseded and active versions remain visible.

### FR-007 — Retrieval

Confirmed project knowledge can be retrieved in a later session, filtered by
project and status, with version and provenance returned alongside content.
Retrieval in the MVP is structural. Semantic retrieval is deferred.

*Acceptance:* AT-003.

### FR-008 — Blueprint preview

Confirmed knowledge can be rendered as a reviewable blueprint whose statements
link back to their supporting evidence. Statements are labelled grounded,
derived, or assumption. Export is Markdown.

*Acceptance:* AT-004. No blueprint statement lacks a label or a trace target.

## Deferred — not authorised for the MVP

These are recognised as product direction but must not be implemented under this
baseline:

- **Multi-agent autonomy.** Concurrent specialised agents acting without human
  confirmation. The MVP proves durable memory with a single extraction workflow
  and a human in the loop.
- **MCP write operations.** A read-only audit boundary may be explored later; no
  MCP path may write to project memory.
- **Full workflow orchestration.** Multi-step agent workflows, scheduling,
  asynchronous job graphs, and autonomous progression between discovery stages.
- **Advanced retrieval.** Embeddings, vector indexes, hybrid ranking, and
  relevance tuning.
- **Production deployment.** Multi-region operation, scaling, SLAs, and
  operational hardening beyond the demonstration.
- **Enterprise administration.** Tenancy, user management, roles, audit
  consoles, and configuration surfaces.
- **Document ingestion.** File uploads, parsing, chunking, and document-derived
  evidence.

Adding any of these requires a new approved requirement and an architecture
decision.

## Requirement dimensions still to be defined

Approval of the capabilities above does not approve their non-functional
envelope. The following must be defined before the AWS integration (M9) and
demo-ready (M10) milestones, and no figures may be invented in the meantime:

- **Actors and permissions** — who may read, write, confirm, supersede, and
  reject each knowledge class. The MVP assumes a single trusted human owner per
  project and no authentication.
- **Failure behaviour** — unavailable database, partial writes, duplicate
  submissions, conflicting updates, stale retrieval, malformed content, and model
  provider failure. Serialization-failure retry is implemented; the rest is not.
- **Non-functional requirements** — scale, latency, availability, durability,
  consistency, portability, observability, privacy, security, auditability, and
  maintainability.
- **Data sensitivity and retention** — what may be stored, for how long, and what
  a deletion request means given supersession-without-loss.

## Open decisions

Tracked in `project-model.yaml`:

- OQ-010 — physical schema for projects, sessions, messages, and relationships.
- OQ-011 — frontend technology for the prototype and workspace.
- OQ-012 — extraction model provider, prompt contract, and output schema.
- OQ-013 — readiness model gating blueprint generation.

## Proof scenario

The baseline is satisfied when a reviewer can watch a project created in one
session, see knowledge extracted from a submitted paragraph and confirmed by a
human, return in a separate session to find that knowledge intact with its
provenance, correct one item so the prior version becomes superseded rather than
lost, and generate a blueprint whose statements trace back to confirmed memory.
