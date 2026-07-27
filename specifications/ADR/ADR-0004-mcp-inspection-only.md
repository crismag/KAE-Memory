# ADR-0004 — CockroachDB MCP is inspection-only

- **Status:** accepted
- **Date:** 2026-07-27

## Context

CockroachDB MCP servers are configured in development and give an AI tool direct
access to the cluster. Agents in the KAE workflow also need to read and write
project knowledge. The tempting shortcut is to let agents use MCP as their data
path, since it is already authenticated and requires no application code.

Domain invariants — append-only versions, mandatory provenance, valid lifecycle
transitions, supersession without deletion — are enforced in
`src/kae_memory/domain/`, not in the database schema. The database cannot
reconstruct them.

## Decision

CockroachDB MCP is used for **inspection and management only**: schema review,
query plans, cluster health, documentation, and read-only demonstration or audit.

All domain writes go through KAE application contracts. Agents never hold raw
database credentials and never issue DML or DDL against domain tables.

## Consequences

**Positive**

- Every write passes the domain invariants, so provenance and history remain
  trustworthy.
- The audit trail the product sells cannot be silently corrupted by an agent.
- The write path is testable without a live cluster.

**Negative**

- Agent capabilities require application contracts to exist first, which is
  slower than granting SQL access.
- A second access path must be documented and enforced by review, since nothing
  in the tooling prevents an agent from being handed a connection string.

**Accepted risk**

Enforcement is by policy and review, not by a technical control. If a read-only
MCP service account is later introduced for the audit path, it is provisioned
with a least-privilege role and documented before use.

## Related

- [`../../docs/06_architecture/MCP_ACCESS_POLICY.md`](../../docs/06_architecture/MCP_ACCESS_POLICY.md)
- [`../AGENT_EXECUTION_MODEL.md`](../AGENT_EXECUTION_MODEL.md)
