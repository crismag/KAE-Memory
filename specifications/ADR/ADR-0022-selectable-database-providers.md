# ADR-0022 — Selectable database providers

**Status:** accepted, 2026-08-04. Supersedes the *exclusivity* of ADR-0003 and
ADR-0011; both remain historically valid for the phase they governed.

## Decision

> KAE-Memory supports selectable relational and vector database providers
> through a provider-independent persistence architecture. CockroachDB and
> PostgreSQL with pgvector are the initial supported providers.

Neither provider is the default production architecture. Neither is a fallback,
a degraded mode, or a transitional step away from the other. A deployment
selects the provider appropriate to its environment, and that selection is
configuration.

## What this supersedes, and what it does not

ADR-0011 retired SQLite after it produced two false passes — a timezone-aware
provenance defect SQLite hid by dropping offsets on read, and a migration it
rejected because it cannot add a `NOT NULL` column with a non-constant default,
which CockroachDB accepts.

**That reasoning is untouched and still governs.** Tests run against an engine
the product actually deploys on, at the same major version. What changes is that
"the engine" is now one of two rather than exactly one. Running the suite against
a third engine nobody deploys would reintroduce precisely the failure ADR-0011
was written about.

ADR-0003 (SQLAlchemy, Alembic, psycopg) is unaffected. All three remain the
shared mechanism.

## Why not treat this as a CockroachDB replacement

The immediate prompt was a CockroachDB Cloud trial expiring. Building a
temporary escape hatch would have produced a second-class code path that rots:
untested on one side, assumed on the other, and impossible to trust the first
time it is needed in earnest.

Portability is worth more than the incident that surfaced it. Recording it as an
architectural capability means both paths carry the same tests and the same
expectations.

## Architecture

```text
Domain and application services
            ↓
Provider-independent repository contracts
            ↓
SQLAlchemy persistence implementation
            ↓
Provider capability and query strategies
       ↙                         ↘
CockroachDB                 PostgreSQL/pgvector
```

Nothing above the repository boundary knows which engine it is talking to. The
moment a service asks, switching providers stops being configuration and becomes
a code change — which is the property this decision exists to protect.

## Capability, not identity

`DatabaseCapabilities` describes what a store can do; `DatabaseProvider` names
which one it is. They are related and deliberately not the same.

Code asks for capability. A third provider offering pgvector would share
PostgreSQL's behaviour without being PostgreSQL, and a check written against the
name would silently exclude it. The transaction strategy is selected from
`transaction_retry_required`, not from a provider name, for exactly this reason.

## Selection is explicit

`KAE_DATABASE_PROVIDER` must be set. There is no default and no inference from
the connection URL.

A default would let an unconfigured deployment start successfully against an
engine nobody chose, and the failure would appear later as missing data rather
than as a configuration error. Inference is worse: a URL is a connection string,
and reading provider identity out of one is how a deployment ends up pointed at
the right host with the wrong assumptions.

A configured provider that is unavailable is an error. Falling back to whichever
database answers would mean writing authoritative knowledge to an unintended
store.

## What varies, and what cannot

**Varies by provider:** connection URL, engine configuration, vector column
type, vector index DDL, transaction retry strategy, provider-specific migration
branches, capability diagnostics.

**Must not vary:** domain entities, lifecycle rules, knowledge semantics,
repository contracts, readiness, provenance, MCP tool contracts, application
service behaviour.

The vector surface is narrower than expected: both engines spell cosine distance
`<=>`, so only the column type and the index statement differ. That is
confinable to the adapter, and is confined there rather than assumed to be
permanent — a future provider may well differ, and the seam already exists.

## Migrations

One Alembic history. Provider-specific branches are confined to the vector
column and its index; the relational schema either side is identical, so two
histories would be two things to keep in step for no benefit.

Revision `0004` obtains its DDL from the provider adapter: `CREATE EXTENSION IF
NOT EXISTS vector` on PostgreSQL, nothing on CockroachDB; an HNSW index with
`vector_cosine_ops` on PostgreSQL, `CREATE VECTOR INDEX` on CockroachDB. The
PostgreSQL index names the operator class deliberately — an index built for a
different one is not merely slower, the planner will not use it.

## Transactions

CockroachDB runs serializable isolation and reports conflicts as SQLSTATE 40001,
expecting retries. PostgreSQL at its default isolation cannot raise that.

Each strategy is wrong for the other engine. Retrying where retries cannot
happen is dead code implying a guarantee never made; not retrying where they are
routine turns ordinary contention into a user-visible error. `TransactionRunner`
has one implementation per behaviour, chosen from capability.

A PostgreSQL deployment raising isolation to serializable should select the
retrying runner. That is a real difference and belongs in configuration.

## Data authority

One process, one authoritative provider.

Switchability is not data movement. There are no dual writes, no replication, no
failover, and no synchronisation in either direction. A deployment that changes
provider reads the dataset in the newly selected store — which will be empty
unless something put data there. Cross-provider export and import is a separate
capability, not implied by this decision.

## Consequences

`KAE_DATABASE_PROVIDER` becomes required. An existing deployment adds one
variable; `KAE_DATABASE_URL` continues to work once a provider is named.

The suite gains a provider dimension. `KAE_TEST_DATABASE_PROVIDER` selects the
engine under test, and contract tests take a provider fixture so one test body
runs against either. The unit suite requires neither database.

`docs/09_development/DEFERRED_VERIFICATION.md` carries CVG-1, which predates
this decision and asks whether a CockroachDB Cloud schema survived an earlier
migration-test defect. This ADR does not answer it. The question survives a
change of provider, and the gate stays open.
