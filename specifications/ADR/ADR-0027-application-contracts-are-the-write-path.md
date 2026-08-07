# ADR-0027 — Application contracts are the write path

- **Status:** accepted
- **Date:** 2026-08-07
- **Supersedes:** [ADR-0004](ADR-0004-mcp-inspection-only.md) — *CockroachDB MCP is inspection-only*
- **Relates to:** [ADR-0022](ADR-0022-selectable-database-providers.md), [ADR-0023](ADR-0023-http-and-mcp-as-peer-adapters.md), [ADR-0024](ADR-0024-http-trust-boundary.md)

## Context

ADR-0004 said the right thing about the wrong noun. It was written when
CockroachDB was the only provider and a CockroachDB MCP server was configured in
development, and its title — *"CockroachDB MCP is inspection-only"* — has since
been read as a claim about KAE-Memory's own MCP adapter.

It is not. Two different things are called MCP here:

- **KAE-Memory's MCP adapter** — an application interface over the same services
  HTTP uses, and a peer to it (ADR-0023). It performs domain operations by
  design.
- **A database-provider MCP server** — a tool pointed at the cluster, speaking
  SQL, knowing nothing about KAE's domain.

Meanwhile the provider is no longer fixed. ADR-0022 made providers selectable;
PostgreSQL and CockroachDB are both supported, and a decision naming one of them
in its title cannot govern the other.

So the original decision needs restating in terms of what it was actually about:
not a product, but a boundary.

## Decision

**Agents and clients act on KAE-Memory through its supported application
contracts** — MCP, HTTP, the CLI, and approved service interfaces. Those
contracts perform domain operations, including writes.

**They do not reach the persistence schema directly** — not through raw SQL, not
through a database-provider MCP server, not through provider administration
interfaces — as part of any normal agent or product workflow.

Provider-neutral, deliberately. The boundary is between *application contract*
and *persistence schema*, and it holds whichever engine is configured.

### What this does not say

- **Not** that KAE-Memory's MCP is read-only. It registers 31 tools, 13 of which
  mutate: submitting observations, confirming, rejecting and correcting
  knowledge, answering clarifications, recording assumptions and deliverables,
  defining and relating modules, settling operational records, creating
  projects, ingesting documents.
- **Not** that operators may never touch the database. Migrations, backup and
  restore, capacity work, and incident recovery are operator activities and use
  database tooling directly. They are not product workflows and this decision
  does not govern them.
- **Not** that debugging is forbidden. Reading the schema to understand a fault
  is inspection, and inspection was never the problem.
- **Not** a claim about which provider to run.

The line is *normal operation* versus *administration*, not *read* versus
*write*.

## Why

The invariants that make this knowledge trustworthy are enforced in
`src/kae_memory/domain/`, not in the schema:

| Invariant | Where it lives |
|---|---|
| Valid lifecycle transitions | `domain/lifecycle.py` — `_ALLOWED_TRANSITIONS`, raising `InvalidLifecycleTransitionError` |
| Valid run-status transitions | `domain/execution.py` — the same shape |
| Append-only versions, supersession without deletion | domain services over the repositories |
| Mandatory provenance | the write paths that record it |
| Optimistic concurrency on review | `expected_version`, refused with a 409 |

A `UPDATE knowledge SET lifecycle='validated'` succeeds. It produces a statement
the project believes a person confirmed, with no reviewer, no version check, no
transition validation, and no trace. Nothing downstream can tell it apart from
one that went through the review surface — which is precisely the confusion this
system exists to prevent.

The database cannot reconstruct those rules, and asking it to would mean
duplicating the domain in schema constraints on every supported engine. ADR-0022
makes that a per-provider cost, and the engines already differ enough to need
their own migration (`0009` exists because CockroachDB and PostgreSQL compiled
`Integer` differently).

There is also a portability argument that outlives any of this: a write path
expressed as SQL against one schema is a write path that has to be rewritten
when the schema moves.

## Consequences

- An agent that needs an operation KAE-Memory does not expose gets **a new
  capability**, declared in `capabilities.py` and enforced on both adapters by
  `tests/api/test_adapter_parity.py` — not a SQL workaround.
- Capability gaps become visible rather than routed around. The twelve-capability
  divergence N1 measured was found because the registry made it findable.
- Operators keep full database access. Nothing here restricts what a person with
  credentials may do during maintenance; it says what the product does.
- Provider changes do not disturb this boundary, which is the point of restating
  it without a product name.

## Evidence

Executable, at the commit that carries this ADR:

- 31 MCP tools registered under `src/kae_memory/mcp/`, 13 of them mutations.
- 43 capabilities declared in `src/kae_memory/capabilities.py` — 25 on both
  adapters, 12 product-only, 5 agent-only, 1 internal.
- `tests/api/test_adapter_parity.py` fails the suite if a declared capability is
  missing from an adapter, or if a tool or route exists that the registry does
  not declare.
- `src/kae_memory/domain/lifecycle.py` and `domain/execution.py` hold the
  transition tables the schema does not.

## Historical note

ADR-0004 is preserved unedited apart from its status line. Its reasoning about
CockroachDB MCP was correct for the configuration it addressed, and rewriting it
to sound provider-neutral would erase the fact that the question first arose
because a specific tool was sitting in a development environment with cluster
credentials.
