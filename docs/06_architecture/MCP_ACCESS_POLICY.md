# MCP Access Policy

**Status:** approved, 2026-07-27. Recorded as ADR-0004.

## Rule

**CockroachDB MCP is for inspection and management only. All domain writes go
through KAE application contracts.**

There is no exception for convenience, demo pressure, or agent capability.

## Why

Domain invariants live in KAE, not in the database. Append-only version history,
provenance on every version, valid lifecycle transitions, and
supersession-without-deletion are enforced by the domain contracts in
`src/kae_memory/domain/`. A write that bypasses those contracts can produce
knowledge with no provenance, a version that overwrites history, or a lifecycle
state the domain considers impossible — and the audit trail that the product
sells would become untrustworthy.

An agent with raw SQL access is an agent that can silently corrupt the memory the
entire product depends on.

## Permitted MCP use

| Use | Allowed |
| --- | --- |
| Schema and index inspection | yes |
| Query plans and performance investigation | yes |
| Cluster health, sizing, and configuration | yes |
| Documentation lookup | yes |
| Read-only inspection during demo or audit | yes |
| Any `INSERT`, `UPDATE`, `DELETE`, or DDL against domain tables | **no** |
| Agent runtime paths reading domain data for product behaviour | **no** — use retrieval contracts |

Migrations are applied by Alembic through the documented workflow, not by MCP.

## Configured servers

Two MCP servers are used in development:

- **`cockroachdb-docs`** — documentation question answering. No cluster access.
- **`cockroachdb-cloud`** — cluster management and inspection. Authenticated with
  a service credential scoped to the development cluster.

Neither is a data-plane SQL server, which matches this policy by construction.

## Credential handling

- MCP credentials are **developer-local configuration**, not repository content.
  They must never be committed, pasted into documents, issues, pull requests, or
  agent transcripts.
- Cluster identifiers and bearer tokens are secrets. Treat any token that appears
  in a shared transcript as compromised and rotate it.
- The application's own database credentials are separate from MCP credentials
  and are managed as described in
  [`../09_development/AWS_DEMONSTRATION_BASELINE.md`](../09_development/AWS_DEMONSTRATION_BASELINE.md).
- If a read-only MCP service account is introduced for the audit path, it is
  provisioned with its own least-privilege role and documented before use.

## Consequence for the Review Agent

The Review Agent inspects knowledge through KAE retrieval contracts, not through
MCP. MCP may be used to *demonstrate* to judges that the data in CockroachDB
matches what the product claims — that is inspection, and it is exactly the use
this policy permits.
