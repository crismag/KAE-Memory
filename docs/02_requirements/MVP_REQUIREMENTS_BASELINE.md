# MVP Requirements Baseline

**Status:** approved for implementation, amended 2026-07-27 to authorise the
minimum hackathon capabilities.

This baseline approves the minimum set of requirements needed to authorise the
end-to-end product slice and its demonstration. It deliberately approves less
than the full product. Anything not listed under "Approved MVP requirements" is
not authorised, and a coding agent must not implement it.

**Amendment note.** The first version of this baseline deferred multi-agent
execution, semantic retrieval, workflow durability, MCP, and deployment. Those
deferrals contradicted the demonstration the project must produce and are
replaced below by **bounded** authorisations. The boundaries matter as much as
the approvals: three fixed agent roles, not arbitrary swarms; demonstration
deployment, not production.

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
project and status, with version and provenance returned alongside content. This
requirement covers structured retrieval; semantic similarity is FR-013.

*Acceptance:* AT-003.

### FR-008 — Blueprint preview

Confirmed knowledge can be rendered as a reviewable blueprint whose statements
link back to their supporting evidence. Statements are labelled grounded,
derived, or assumption. Export is Markdown.

*Acceptance:* AT-004. No blueprint statement lacks a label or a trace target.

### FR-009 — Bounded multi-agent execution

Exactly three predefined agent roles are authorised: Requirements, Architecture,
and Review. Each has a declared read scope, write scope, and prohibition set, as
specified in
[`../../specifications/AGENT_EXECUTION_MODEL.md`](../../specifications/AGENT_EXECUTION_MODEL.md).
Agents run behind the discovery workspace through KAE contracts. No agent
confirms knowledge; confirmation is a human act.

*Acceptance:* AT-006.

### FR-010 — Persistent AgentRun records

Every agent execution is recorded durably before work begins, with role, session,
status, input context, output summary, attempt, and timing. Knowledge produced by
a run resolves to that run through provenance. Knowledge writes and the
accompanying run status change commit in one transaction.

*Acceptance:* no knowledge exists without an accountable run, and no run reports
success without its outputs.

### FR-011 — Durable workflow continuation

A run interrupted by worker termination becomes eligible for resumption by a
different worker and continues from its last committed checkpoint. Recovery uses
only durable state — never in-process memory, local disk, or conversation.

*Acceptance:* AT-005.

### FR-012 — Idempotency, retry, and failure

Run submission is idempotent by caller-supplied key. Retry is bounded with
backoff; exhausting the budget moves the run to `abandoned` and raises a visible
finding rather than looping. Malformed model output fails validation before any
write. The failure table in the agent execution model is the authoritative
behaviour set.

*Acceptance:* AT-007.

### FR-013 — Semantic retrieval

Retrieval supports structured filters and semantic similarity over project
knowledge and source evidence, scoped to one project, returning provenance,
version, and status alongside each result, with an explanation of why a result
was included.

*Bounded:* one approved embedding model, one index strategy, single project
scope. Not production-scale RAG — no hybrid ranking tuning, reranking cascades,
or corpus-wide optimisation.

*Acceptance:* a concept search returns related evidence, requirements, and
decisions the user did not name exactly.

### FR-014 — CockroachDB MCP inspection

CockroachDB MCP is available for schema inspection, query plans, cluster health,
documentation, and read-only demonstration or audit.

*Bounded:* inspection and management only. All domain writes go through KAE
application contracts. Agents never hold raw database credentials. See ADR-0004.

### FR-015 — Review and quality reporting

The Review Agent produces quality findings — unresolved gaps, contradictions,
unsupported statements, and validation coverage. Reporting is generated from the
same operational data the workspace shows: project memory summary, agent
execution history, traceability, unresolved conflicts, validation coverage, and a
recovery demonstration report.

*Bounded:* reporting is a view over operational data, not a separate analytics
platform.

*Acceptance:* a reviewer can read what is unresolved without inspecting the
database.

### FR-016 — Demonstration deployment

*Amended by [`ADR-0013`](../../specifications/ADR/ADR-0013-portable-runtime-and-optional-aws.md).
This requirement originally read "deployed to AWS". AWS is now one satisfying
deployment rather than the definition.*

The application and one worker are deployed against CockroachDB Cloud such that
the application is reachable, compute is disposable, and an interrupted run
resumes after the worker process is replaced by its configured supervisor.

*Required:* portable API and worker processes, automatic worker replacement
through Docker or an operating-system supervisor, expiry-based reclamation,
checkpoint continuation, and no manual run repair.

*Optional enhancement:* ECS on Fargate with ECR, a load balancer, IAM task roles,
and CloudWatch. Preferred for production and for the demonstration; it does not
gate feature completion.

*Bounded:* single region, one service, one worker. Not production-grade — see
[`../09_development/AWS_DEMONSTRATION_BASELINE.md`](../09_development/AWS_DEMONSTRATION_BASELINE.md).

*Acceptance:* AT-009.

### FR-017 — Health and observability

A `GET /health` endpoint reports overall status, database connectivity, applied
migration revision, and application version, without authentication and without
leaking credentials. Logs are structured and carry run identifiers so a run can
be traced across worker restarts.

*Acceptance:* AT-008.

### FR-018 — Secrets management

Credentials are supplied by environment in local development from an untracked
`.env` with a committed `.env.example`, and by AWS Secrets Manager or Parameter
Store when deployed. No credential appears in the repository, an image, a log, a
document, or an agent transcript. The application database user is
least-privilege; migrations use a separate credential.

*Acceptance:* a repository scan finds no credential, and the deployed application
reads every secret from the secret store.

## Deferred — not authorised for the MVP

These are recognised as product direction but must not be implemented under this
baseline:

- **Arbitrary agent swarms.** Agent roles beyond the three in FR-009, dynamic
  role creation, agent-to-agent negotiation, or many agents on one project at
  once.
- **General coding-agent hosting.** Executing generated code, running a coding
  agent runtime, or automatic merging and deployment of agent output.
- **Unrestricted autonomous orchestration.** Self-directed planning, unbounded
  agent chains, scheduling without human initiation, or agents confirming their
  own knowledge.
- **MCP write operations.** No MCP path may write to project memory. Inspection
  and management only, per FR-014 and ADR-0004.
- **Production-scale RAG.** Hybrid ranking, reranking cascades, corpus-wide
  optimisation, cross-project retrieval, and relevance tuning beyond the single
  approved model and index in FR-013.
- **Production-grade deployment.** Multi-region, autoscaling, SLAs, failover
  engineering, and operational hardening beyond the demonstration baseline in
  FR-016.
- **Enterprise administration.** Tenancy, user management, roles, audit consoles,
  and configuration surfaces.
- **Document ingestion.** File uploads, parsing, chunking, and document-derived
  evidence.
- **Authentication, teams, billing, marketplace.** Unchanged; see the MVP scope
  boundary.

Adding any of these requires a new approved requirement and an architecture
decision.

## Requirement dimensions still to be defined

Approval of the capabilities above does not approve their non-functional
envelope. The following must be defined before the deployment (M10) and release
(M11) milestones, and no figures may be invented in the meantime:

- **Actors and permissions** — who may read, write, confirm, supersede, and
  reject each knowledge class. The MVP assumes a single trusted human owner per
  project and no authentication.
- **Failure behaviour** — the run-level failure table in the agent execution
  model is approved. Still undefined: stale-retrieval semantics, conflicting
  concurrent confirmations, and user-facing error presentation.
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
- OQ-014 — embedding model, vector column type, and index strategy (FR-013).
- OQ-015 — worker runtime, lease mechanism, and lease duration (FR-011).
- OQ-016 — AWS runtime choice, ECS Fargate or App Runner (FR-016).

## Proof scenario

The baseline is satisfied by the ten-beat sequence in
[`../05_product/UNIFIED_DEMO_NARRATIVE.md`](../05_product/UNIFIED_DEMO_NARRATIVE.md):
a project created from a paragraph, requirements extracted by one agent and
confirmed by a human, architecture derived by a second agent from those confirmed
requirements, a worker terminated mid-run and resumed by another, a Review Agent
in a new session reporting gaps from knowledge written by earlier agents,
structured and semantic recall across the session boundary, a correction that
supersedes rather than deletes, and a blueprint whose statements trace back to
confirmed memory.

Recovery is the proof. A demonstration that omits the interruption and resumption
beats does not satisfy this baseline.
