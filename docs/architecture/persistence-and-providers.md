# Persistence and providers

**KAE-Memory targets PostgreSQL, including deployment on Amazon RDS for
PostgreSQL.**

---

## PostgreSQL with pgvector

The database KAE-Memory is developed, tested and deployed against.

| | |
|---|---|
| Engine | PostgreSQL 16 or later |
| Extension | `pgvector`, for semantic retrieval |
| Hosted environment | Amazon RDS for PostgreSQL |
| Local development | Container, started by `make dev` |

**16 is the minimum**, not the target. Later versions are expected to work and
are what the deployed environment runs.

### pgvector

Embeddings are stored in a vector column and searched by distance. The extension
must be available before migrations run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

On RDS it is available and enabled per-database. Without it, migrations that
create vector columns fail — which is the correct failure, in the right place,
rather than a retrieval layer that silently returns nothing.

## Amazon RDS

The hosted environment. Nothing in KAE-Memory requires RDS; it requires
PostgreSQL, and RDS is a PostgreSQL deployment profile rather than a distinct
provider. There is no `rds` adapter and there should not be one.

What matters operationally:

- The instance holds no public address in the supported shape. The application
  reaches it privately.
- `pgvector` is enabled per-database, not per-instance.
- Credentials reach the application through the environment. They are never
  committed, and the settings catalog records that as a rule rather than a habit.

Provisioning is deliberately not documented here. **This repository ships no
cloud provisioning automation**, and describing infrastructure it does not
create would be describing something you cannot reproduce from it. Generic
PostgreSQL instructions work on RDS, on a managed instance elsewhere, or on a
container.

## Schema

| | |
|---|---|
| Migrations | Alembic, `migrations/versions/` |
| Revisions | 21, head `0021` |
| Applied by | `alembic upgrade head` |

`/health` reports the applied revision, so a deployment can be checked without
opening the database:

```json
{"status": "ok", "database": "up", "migration_revision": "0021", "version": "0.1.0"}
```

A null revision means migrations have not run. `"database": "down"` means the
connection failed.

### A guard worth knowing about

Test database names must contain `test`. That is not a naming convention — it is
what stops a destructive migration test from running against a real database,
and it exists because that once happened. Do not work around it.

## The deferred provider

A CockroachDB provider integration remains in the codebase from earlier
development. **Compatibility with the current schema has not been reverified,
and CockroachDB deployment and parity testing are deferred.**

It is not abandoned, and it is not currently verified. Parity was demonstrated
at schema revision `0009`; the head is `0021`. Returning it to supported status
needs intentional compatibility and parity testing, tracked as
[#81](https://github.com/crismag/KAE-Memory/issues/81).

Until then, **do not treat KAE-Memory as multi-database or vendor-portable.**
Provider selection exists in the code
([ADR-0022](../../specifications/ADR/ADR-0022-selectable-database-providers.md));
a current guarantee does not.

This page is the only place this documentation covers it.

## What the persistence layer holds

Durable structured knowledge, and not much else:

| Stored | Not stored |
|---|---|
| Projects, sessions, messages | Rendered artifact bytes |
| Knowledge items with versions and provenance | Model responses beyond what became knowledge |
| Classifications, clarifications, assumptions | Client state |
| Modules and relationships | Credentials |
| Agent runs, leases, idempotency keys | |
| Readiness snapshots | |
| Embeddings, for retrieval | |
| Deliverable records and manifests | |

**A deliverable record is not the deliverable.** The manifest, hashes and
provenance are durable knowledge; the produced bytes are an artifact, and where
those live is a rendering and publication concern rather than a persistence one.

## Where the rules live

Domain invariants are enforced in application code, not in schema constraints
([ADR-0027](../../specifications/ADR/ADR-0027-application-contracts-are-the-write-path.md)).
The schema stores; it does not adjudicate.

That is why direct database writes sit outside supported workflows: a write that
does not pass through the domain produces state no rule ever checked. See
[access and mutation policy](../reference/access-and-mutation-policy.md).

## Related

- [Configuration](../reference/configuration.md)
- [Security boundaries](security-boundaries.md)
- [ADR-0022](../../specifications/ADR/ADR-0022-selectable-database-providers.md)
