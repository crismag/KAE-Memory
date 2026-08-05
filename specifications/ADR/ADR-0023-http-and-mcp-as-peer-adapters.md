# ADR-0023 — HTTP and MCP as peer adapters

**Status:** proposed, 2026-08-05. Target **N2** of
`docs/09_development/NEXT_PHASE_CHECKLIST.md`. Extends ADR-0018; supersedes
nothing.

## Decision

> HTTP is KAE-Studio's transport. MCP is the coding agent's transport. Both are
> **adapters over the same application services**, and neither owns domain
> behaviour. A capability required by both and exposed by only one is a defect,
> not a roadmap item — unless it is a declared exception.

The browser does not become an MCP client.

## Context

ADR-0018 made MCP the agent access layer, and it succeeded: fifteen tools, a
response policy, honesty guarantees, and every capability from Phase C onward.

The unintended consequence is measured in
[`ADAPTER_CAPABILITY_MATRIX.md`](../../docs/06_architecture/ADAPTER_CAPABILITY_MATRIX.md).
Nine application services exist and HTTP wires four. Retrieval, ingestion,
assembly, clarification, and classification are reachable only through MCP.
**Twelve of twenty-four registered capabilities are Studio-required and absent
from HTTP.**

The asymmetry runs both ways, which is what makes it drift rather than backlog:
HTTP can start an agent run, stream progress, record a blocker, and resolve a
contradiction, and MCP cannot. Neither surface is a superset of the other, and
nothing tested the relationship, so each grew toward whatever its last target
needed.

Studio is a browser application. It cannot speak stdio MCP, and making the
browser an MCP client would put a protocol designed for a trusted local process
behind a public origin.

## What "adapter" commits us to

**Application services own behaviour.** Lifecycle transitions, validation,
readiness effects, idempotency, and revision semantics live in
`application/`. A router that re-implements any of them has moved a rule out
of the place both adapters share, which is how two surfaces start disagreeing
about what the product does.

**Adapters own their transport.** Serialisation, pagination envelopes, error
shape, authentication, and the response policy are adapter concerns and may
differ. MCP's `{total, page, cursor, results}` wrapper (ADR-0021) is an MCP
convention, not a domain one; HTTP may use a different envelope.

**Parity is behavioural, not textual.** The test is whether the same call
reaches the same application behaviour, not whether two payloads look alike.

## Declared exceptions

Not every capability belongs on both adapters, and pretending otherwise would
produce endpoints nobody wants.

| Capability | Exposed on | Why |
| --- | --- | --- |
| Re-embedding | neither | Operational, script-driven, long-running |
| Readiness area assignment | HTTP | Template administration, not a product action |
| Agent run submission and SSE progress | HTTP | Studio shows progress; an agent that *is* the work does not submit runs to itself |
| Prompt and resource surfaces | MCP | Protocol features with no HTTP analogue |

An exception is a decision recorded in the capability registry (N6). Anything
not listed as an exception and required by both is a defect.

## What this does not decide

**Whether the conversation model moves.** Memory orders messages by session;
Studio's port is project-scoped. Both are defensible and the choice is a
separate contract decision (N13, N14). This ADR only says that whichever is
chosen, both adapters get it.

**Whether the blueprint route becomes the briefing.** They are different
responses, not a missing endpoint (matrix row 10).

**Durable deliverables, modules, publication.** Absent domain concepts. A router
must not invent one to satisfy the current Studio prototype; that is how a
prototype's convenience method becomes an accidental durable schema.

## Consequences

**Accepted.** HTTP grows substantially. Twelve capabilities need contracts,
each with bounded responses, pagination where data grows, explicit revision
identity, and honest queued and partial states.

**Accepted.** A trust boundary becomes mandatory (N5). Today the HTTP API has no
authentication of any kind — CORS origins are the only control, and CORS is not
authentication. That is tolerable for a local demo and not for a remote Studio.
Remote deployment fails closed.

**Accepted.** The parity registry is ongoing cost. It is cheaper than the
alternative, which is discovering the next twelve-capability gap by writing a
document about it months later.

**Rejected: making MCP the only adapter and having Studio proxy through an
agent.** It would put a model in the path of every read, make the product's
latency and cost depend on inference, and give a browser action no deterministic
contract.

**Rejected: letting HTTP diverge deliberately as a "simplified" surface.** A
simplified surface is how the current gap was reached. Simplification that is
wanted can be a declared exception; simplification that is unstated is drift.

## Evidence

The matrix is reproducible from code: `application/*_service.py`,
`TOOL_DEFINITIONS` in `mcp/server.py`, and the `@router` decorators in
`api/routers/`. No row in it asserts a capability that was not read in code.
