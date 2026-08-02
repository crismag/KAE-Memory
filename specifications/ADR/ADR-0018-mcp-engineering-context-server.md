# ADR-0018 — KAE MCP is an application adapter owned by KAE-Memory

- **Status:** accepted
- **Date:** 2026-08-01
- **Accepted:** 2026-08-02
- **Depends on:** [`ADR-0004`](ADR-0004-mcp-inspection-only.md), [`ADR-0005`](ADR-0005-m5-physical-schema.md), [`ADR-0014`](ADR-0014-http-api-contract.md)
- **Milestone:** MCP-M1

## Context

Coding agents — Claude Code, Codex, Cursor, VS Code — already speak the Model Context Protocol. KAE-Memory holds the project knowledge those agents need before they write code, and has no way to give it to them. Building a separate integration per agent would mean maintaining N adapters for one capability.

[`ADR-0004`](ADR-0004-mcp-inspection-only.md) already settled the adjacent question: the **CockroachDB** MCP server is inspection-only, because domain invariants — append-only versions, mandatory provenance, valid lifecycle transitions, supersession without deletion — live in `src/kae_memory/domain/`, not in the schema. It accepted a known weakness:

> Enforcement is by policy and review, not by a technical control. […] nothing in the tooling prevents an agent from being handed a connection string.

That weakness exists because agents have a real need and no sanctioned way to meet it. This ADR closes it by giving them one.

## Decision

**Build a KAE MCP server inside KAE-Memory, as an adapter over the application layer.**

### 1. MCP belongs to KAE-Memory

Every operation in the surface — project briefing, module context, knowledge search, open decisions, readiness, observation submission — reads or writes durable engineering knowledge. None is interaction, presentation, or configuration. Hosting it elsewhere would mean proxying Memory for the entire surface while owning none of its semantics.

The surface is **product-neutral**: it must serve a CLI, an IDE extension, or KAE-Studio equally. It is not a Studio backend.

### 2. It is an application adapter, never a database adapter

```text
MCP tool -> application service -> domain -> persistence
```

No MCP module imports `persistence` directly, constructs SQL, or holds a connection string beyond the session factory the application layer already uses. Every write passes the domain invariants, exactly as `ADR-0004` requires. MCP, REST, the worker, and the discovery frontend share one set of business behaviours.

This is the technical control `ADR-0004` said was missing. The CockroachDB MCP server remains inspection-only; KAE MCP becomes the sanctioned agent data path.

### 3. Initial transport is local STDIO

One process per client, started by the client, speaking over standard input and output. This defers remote deployment, HTTPS, OAuth, public endpoints, gateway configuration, and multi-user authorization — none of which are needed to answer the question this milestone asks.

**Configuration comes from the existing mechanism** (`KAE_DATABASE_URL`, `KAE_ENVIRONMENT`), the same resolution `api/dependencies.py` and `worker/__main__.py` already use. No second configuration format.

### 4. STDOUT is reserved for protocol messages; logs go to STDERR

Under STDIO transport, stdout *is* the wire. A stray `print`, a library banner, or a logging handler defaulting to stdout corrupts the JSON-RPC stream and the failure looks like a client bug rather than a stray write. The server configures logging to stderr explicitly at startup and does not rely on defaults.

### 5. Agent observations enter as proposed evidence

`kae_submit_observation` records what an agent found while inspecting or implementing. It creates a message and, where extraction applies, proposed knowledge — through existing application behaviour. It never confirms, overwrites, or supersedes.

**Observation text is untrusted input.** It is recorded as evidence, never followed as instruction, including when it is phrased as one. An agent's conclusion is evidence, not authority.

### 6. Retriable writes require database-enforced idempotency

A retried observation must not create a second record. In-process guards do not survive two clients, two processes, or a crash between insert and acknowledgement, so uniqueness is enforced by a CockroachDB constraint and the conflict is handled, not merely avoided.

Semantics:

| Case | Result |
| --- | --- |
| Same key, same payload | The original record is returned |
| Same key, different payload | `idempotency_conflict` |
| Concurrent retries | Exactly one record |

Sameness is decided by a payload fingerprint stored beside the key, not by comparing free text.

### 7. Module context returns a structured capability gap

`KnowledgeKind` has no `module` value, there is no general relationship write path, and nothing traverses the graph. `kae_get_module_context` therefore returns a structured `capability_unavailable` response naming the missing capabilities.

**It does not invent module records inside the adapter.** Doing so would place a second, unversioned project model outside the domain — the exact failure this architecture exists to prevent. An agent correctly declining to proceed on undefined ground is the product working, and the gap is part of the demonstration rather than something to hide before it.

### 8. Embedder honesty

Semantic search runs against real CockroachDB vectors, but the default `DeterministicEmbeddingAdapter` is hash-derived and has no notion of meaning — `TASK-009` measured recall at chance. Automated tests may use it. **Every response and every demonstration identifies the active embedder, and hash-derived ranking is never presented as semantic relevance.** Demonstrating real ranking quality is an optional live Titan run, and MCP-M1 does not block on it.

### 9. Explicitly deferred

Remote transport (Streamable HTTP), OAuth, tenancy and per-operation authorization, MCP Skills, first-class module modelling, publication recording, and KAE-Studio integration.

**Tenancy becomes blocking the moment a remote transport is introduced.** Local STDIO with locally supplied configuration is the entire reason this milestone can proceed before it is settled.

## Consequences

### Positive

- One integration serves every MCP-capable client.
- Agents receive current context on demand rather than a stale export.
- Discoveries return to Memory with provenance, closing the loop.
- The `ADR-0004` policy gap gains a technical control.
- Idempotent ingestion, needed by every client, lands as a platform capability rather than a Studio workaround.
- The platform claim is testable before any product UI depends on it.

### Negative

- A second delivery surface to version, secure, and contract-test.
- The MCP SDK becomes a dependency, in its own optional extra.
- STDIO's stdout discipline is easy to violate and must be enforced by test.
- A demonstration that surfaces a capability gap needs explaining rather than hiding.

### Accepted risk

The server runs with whatever database credentials its environment supplies, and local STDIO has no per-operation authorization. That is acceptable only while the transport is local and the operator configures it themselves. It stops being acceptable at the first remote deployment.

## Alternatives rejected

**Per-agent integrations.** N adapters for one capability, diverging over time.

**MCP server in KAE-Studio.** Every operation is durable engineering knowledge; Studio would proxy Memory for all of it and own none of the semantics, and agent access would depend on the product UI.

**Give agents SQL through the CockroachDB MCP server.** Rejected by `ADR-0004`. Domain invariants are not in the schema; the audit trail the product sells could be silently corrupted.

**Expose application methods one-to-one as tools.** Couples every client to internals and produces an unusable surface. Tools describe what an engineer wants to accomplish.

**In-process idempotency only.** Does not survive concurrency, multiple clients, or a crash mid-write. The guarantee has to be in the database.

**Add `module` to `KnowledgeKind` so the module tool returns data.** Rejected. A kind value alone gives no identity, edges, traversal, or scoped readiness — it would produce a module concept that answers none of the questions modules exist to answer, while making the gap invisible.

## Follow-up

- Remote Streamable HTTP transport, with tenancy and authorization settled first.
- First-class module support against the minimum capability contract, after which `kae_get_module_context` returns real context.
- Publication recording, once artifact records exist.
- Whether Studio's future client and this tool surface share a generated definition.
