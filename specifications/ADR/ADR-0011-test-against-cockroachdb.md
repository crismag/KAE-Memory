# ADR-0011 — Tests run against CockroachDB, not SQLite

- **Status:** accepted
- **Date:** 2026-07-27
- **Amends:** ADR-0003 (adds the CockroachDB dialect) and ADR-0008 (removes its
  SQLite concession)

## Context

The suite ran on SQLite because it was fast, needed no service, and the ORM made
the substitution invisible. It was not invisible. SQLite produced **two false
passes** and was about to force a third capability to go unverified:

| Divergence | How it surfaced |
| --- | --- |
| SQLite drops the timezone offset on read from `DateTime(timezone=True)` | Green suite, then a failing round trip that RA-01 had to fix with `_as_aware` |
| SQLite rejects a non-constant default on `ADD COLUMN` | Revision `0003` passed against an empty database and failed against a populated one |
| SQLite has no `VECTOR`, no `<=>`, no vector index | ADR-0008 had to concede that M8's central capability could not be verified on the portable path |

The third is the one that forced the decision. A milestone whose headline
capability is untestable is a milestone that cannot be trusted, and the
workaround — skip the vector tests, report them as skipped — would have left the
demonstration's semantic-recall beat resting on code no test had executed.

The pattern is worse than the individual bugs. **A suite that passes on an engine
nobody deploys is not evidence.** Each divergence cost a debugging cycle at the
exact moment the code was supposed to be proven.

## Decision

**Tests run against CockroachDB at the same major version as production.**
SQLite is removed entirely: no fixture, no fallback, no portable variant.

- A single-node CockroachDB in Docker backs the suite locally and in CI —
  `cockroachdb/cockroach:v26.2.1`, in-memory store, insecure, on port 26258.
- `make test-db-up` starts it and `make test` depends on that target, so a fresh
  clone needs one command.
- `KAE_TEST_DATABASE_URL` points the suite at any other cluster.
- Each session creates a uniquely named database and drops it afterwards.
  Migration tests get one database each, since they cycle the whole schema.
- Isolation between tests is by `TRUNCATE`, not by wrapping each test in a
  transaction that is rolled back. The application opens its own sessions and
  **commits** them; rolling those commits back would test behaviour the
  application never exhibits — and durability is the product.

**The suite must fail loudly when no database is reachable**, with the command
that fixes it. It must never skip silently: a green run that tested nothing is
the failure mode this decision exists to eliminate.

### The dialect — an amendment to ADR-0003

ADR-0003 approved "SQLAlchemy 2.0 + Alembic + psycopg 3". Against a real cluster
that is not sufficient: SQLAlchemy's PostgreSQL dialect connects and then raises
`AssertionError: Could not determine version from string 'CockroachDB CCL
v26.2.1 …'`.

`sqlalchemy-cockroachdb` is added as a runtime dependency and the URL scheme is
**`cockroachdb+psycopg://`**, not `postgresql+psycopg://`. It is Cockroach Labs'
own dialect and also carries correct savepoint and retry semantics, so this is
not merely a version-string workaround.

### An amendment to ADR-0008

ADR-0008 required M8's tests to split into portable and CockroachDB-gated, with
the gated set reported as skipped when no cluster was present. **That split is
withdrawn.** Vector columns, the cosine operator, and the vector index are
verified like everything else, and the evaluation fixture runs in the ordinary
suite. All three were confirmed working on the local node before this decision
was recorded.

## Consequences

**Positive.** The engine under test is the engine in production. Whole classes of
divergence — type affinity, DDL restrictions, transaction semantics, JSONB,
`TIMESTAMPTZ`, serialization errors, vectors — are now exercised rather than
approximated. M8 needs no special handling. Migration tests catch what only a
real engine can reject, in both directions. The application required **no code
changes** to pass on CockroachDB, which is itself evidence the ports held.

**Negative.** The suite goes from about 1 second to about 35 seconds. Docker
becomes a prerequisite for running tests, and CI gains a container-start step.
Contributors without Docker must supply `KAE_TEST_DATABASE_URL`.

**Accepted risk.** A single-node in-memory node is not a distributed cluster: it
will not reproduce contention-driven `40001` serialization failures, cross-region
latency, or range-hotspot behaviour. Those remain reasoned about rather than
tested, and the retry path stays covered by the injected-error tests in
`test_transactions.py`. Verifying genuinely distributed behaviour needs a
multi-node cluster and is not attempted here.

## Related

- [`ADR-0003-sqlalchemy-alembic-psycopg.md`](ADR-0003-sqlalchemy-alembic-psycopg.md)
- [`ADR-0005-m5-physical-schema.md`](ADR-0005-m5-physical-schema.md)
- [`ADR-0008-embedding-model-and-vector-index.md`](ADR-0008-embedding-model-and-vector-index.md)
