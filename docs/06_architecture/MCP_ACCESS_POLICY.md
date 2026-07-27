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

## Two credentials, two rotation problems

These are routinely conflated. They are not the same, and they do not carry the
same urgency.

| | Cloud API / MCP bearer key | SQL application credential |
| --- | --- | --- |
| Grants | CockroachDB Cloud API — cluster management and inspection | SQL access to project data |
| Used by | developer tooling, MCP clients | the application and Alembic |
| Rotation | **immediate on exposure**, no deferral | safe storage required now; automated rotation deferred |

### Cloud API / MCP bearer key

An exposed key is revoked and replaced immediately. There is no acceptable
deferral, because the key grants cluster management.

A service account may hold multiple API keys, which supports overlap during
rotation:

1. Create a new key under the same least-privileged service account.
2. Put it in the local secret store.
3. Point the MCP client at an environment variable or injected secret rather than
   an inline token, where the client supports it.
4. Restart and test the MCP integration.
5. **Delete the exposed key.**
6. Record the key identifier and rotation date only — never the secret.

Use a dedicated, least-privileged service account per application rather than a
shared one.

### SQL application credential

Safe storage is required for M5. Automated periodic rotation is not.

- A dedicated application SQL user, granted only the privileges it needs on the
  database, schema, and tables it uses.
- **Never `root`.**
- The MCP service-account key is never reused as the application credential.
- The connection URI comes from `KAE_DATABASE_URL` at startup, never hardcoded,
  so the credential can change without a code change.
- Manual rotation is documented.
- Deployed, the URI lives in AWS Secrets Manager. The application must be
  restartable after the secret changes; zero-downtime refresh is not required.

Automated SQL credential rotation and zero-downtime secret refresh are deferred to
deployment hardening unless the AWS demonstration requires them. This keeps
security credible without turning it into a secrets-platform workstream.

### General

- MCP credentials are **developer-local configuration**, not repository content.
  They must never be committed, or pasted into documents, issues, pull requests,
  or agent transcripts.
- Cluster identifiers and bearer tokens are secrets. A token that appears in a
  shared transcript is compromised — revoke it, do not merely note it.
- If a read-only MCP service account is introduced for the audit path, it is
  provisioned with its own least-privilege role and documented before use.

## Consequence for the Review Agent

The Review Agent inspects knowledge through KAE retrieval contracts, not through
MCP. MCP may be used to *demonstrate* to judges that the data in CockroachDB
matches what the product claims — that is inspection, and it is exactly the use
this policy permits.
