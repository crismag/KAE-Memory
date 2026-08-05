# Focus Action — Studio Provider Contract

## Repository ownership

This file describes only **KAE-Memory's provider-side responsibilities** for
KAE-Studio. Studio's port reconciliation, UI workflow, client adapters,
interview provider, and publication execution belong in KAE-Studio.

## Outcome

Provide the smallest stable, versioned HTTP contract needed for one real Studio
vertical slice without adding frontend behavior or Studio-specific domain logic
to KAE-Memory.

## First vertical slice supported by Memory

1. Create or select a project.
2. Record a message or bounded document as durable evidence.
3. Expose queued/running/completed processing state honestly.
4. Return proposed knowledge with provenance.
5. Accept confirmation, rejection, or correction of one item.
6. Return readiness, blockers, and clarifications.
7. Accept one clarification answer and expose its resulting transitions.
8. Assemble context pinned to an exact knowledge revision.
9. Return a deterministic package description.

## Provider contract rules

- HTTP is the Studio transport; MCP remains the coding-agent transport.
- Studio supplies an explicit `project_id` or resolves a stable
  `project_key`; Memory holds no implicit active-project state.
- A recorded source, queued run, proposed item, confirmed item, and readiness
  change are distinct states.
- Memory owns durable projects, sessions, ordered messages, knowledge,
  provenance, revisions, clarifications, readiness, and findings.
- Studio never writes Memory tables or reimplements lifecycle rules.
- Responses are bounded and include pagination/filtering where collections grow.
- Remote access requires authentication and project/tenant authorization.
- Artifact rendering and destination writes are outside this provider contract.

## Contract dependencies requiring decisions

Do not silently implement provisional Studio assumptions:

- project-scoped message reads and an interview-session projection;
- decision deferral semantics;
- module decisions, pending a first-class module domain;
- confirmation of a computed finding versus confirmation of its underlying
  knowledge;
- durable deliverable identity and listability;
- publication records and their relationship to external publisher actions.

Each must be accepted as a Memory-owned durable concept or removed/reframed by
the Studio client contract.

## Coordination contract

The KAE-Studio repository owns the consumer-side task context and the canonical
mapping from its ports to versioned HTTP operations. KAE-Memory owns the
provider-side API specification and implementation.

Shared contracts may be mirrored, but each repository must identify which copy
governs its implementation. A Memory API change is complete only when its
provider contract tests pass; Studio integration is complete only when its
client contract tests pass against a real Memory service.

## Acceptance criteria

- The vertical slice uses real HTTP contracts rather than mock-only assumptions.
- Refresh or reconnect can reconstruct authoritative state from Memory.
- Every displayed knowledge claim can reach its provenance.
- Failure and partial states cannot be presented as success.
- Unsupported Studio port methods are not simulated inside Memory.
- No frontend implementation is added to KAE-Memory.

## First implementation instruction

Complete the backend capability matrix in
`BACKEND_INTERFACE_READINESS.md`, agree the smallest consumer contract with
KAE-Studio, then implement project creation through first proposal review before
expanding the slice.
