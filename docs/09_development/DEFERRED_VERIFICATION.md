# Deferred verification gates

Work that cannot be verified yet, kept visible so it is not mistaken for work
that passed. Nothing here may be marked complete on the strength of the local
test database alone.

## CVG-1 — CockroachDB Cloud schema verification

**Status: blocked externally. Not waived. Scope narrowed 2026-08-04.**

**What changed.** PostgreSQL with pgvector is now a supported provider
(ADR-0022), the development dataset has been copied to it, and both the
application and the suite run there. So this gate no longer blocks any work.

It is not therefore closed. Whether that cluster's schema survived the
migration-test defect is still unknown, and a question does not stop having an
answer because the work moved elsewhere. What narrows is the consequence: the
cluster is no longer on the path of anything being built, so this is now a
question about a specific machine rather than a risk to current development.

The dataset it holds is no longer the only copy. 218 rows across 13 tables were
copied to PostgreSQL and verified table by table, so a total loss of that
cluster would cost the cluster and not the work.

**What happened.** The migration test fixture pointed Alembic at a throwaway
database, but `migrations/env.py` resolves `KAE_DATABASE_URL` *before* the
Alembic config, so with a developer environment loaded
`test_downgrade_removes_every_table` ran `downgrade base` against whatever that
variable named — the real database — and then passed, because it inspected the
empty throwaway database and found no tables. Fixed in `541121d`, with a
fail-closed guard in `b490267`.

The cloud cluster is currently disabled after exhausting its monthly Request
Unit allowance, and refuses connections outright ("the maximum number of allowed
connections is 0"). That is an infrastructure limit, **not an application
defect**. It is also the only reason no data was lost: the destructive test
failed at connection.

Whether that cluster's schema and data survived earlier runs is **unknown and
unverifiable** while it stays disabled.

**This must not be worked around.** Do not weaken a test, relax the guard, or
change a threshold to make this go away. Do not use `.env` cloud credentials in
migration tests. Do not record cloud schema verification as complete.

**The gate, in order:**

1. Restore or replace the CockroachDB Cloud cluster.
2. Confirm connectivity with a **read-only** check.
3. Inspect the current migration revision and schema.
4. Apply pending migrations deliberately — `0007`, `0008`, and `0009` are
   outstanding there. `0009` matters least on that engine and matters most as a
   record: it exists because CockroachDB and PostgreSQL compiled `Integer`
   differently, which is exactly the class of divergence this gate would surface.
5. Run the CockroachDB-specific integration tests against it.
6. Record the result here and in the Phase E completion report.

**Until then:** all migrations and tests run against isolated local test
databases, named so the destructive guard recognises them. Phase D and Phase E
continue, because neither needs cloud access. The Phase E completion report must
still carry this item as unresolved.

**Do not close this by pointing at the PostgreSQL migration.** That verifies
PostgreSQL. The claim this gate is about — that a specific CockroachDB Cloud
schema is intact — can only be settled against that cluster.

## CVG-2 — Retrieval threshold on a grown corpus

**Status: deferred by measurement, not blocked.**

`MAX_DISTANCE = 0.85` was fitted to twenty queries over thirty-two chunks. The
usable window between the worst genuine match (0.840) and the nearest noise
(0.847) is **0.005 wide**, and one weak query already leaks. Re-run
`scripts/development/evaluate-retrieval.py` when the corpus grows materially.
Hybrid ranking, not a better constant, is the durable answer.

## CVG-3 — Reviewer identity

**Status: accepted risk, recorded in [PHASE_C_DECISIONS.md](PHASE_C_DECISIONS.md).**

An agent that fabricates a `reviewer` name records a human decision nobody made.
Nothing in this layer detects it. Closing it needs identity MCP does not carry.

## CVG-4 — CockroachDB live integration breadth

**Status: partially verified 2026-08-04.**

CockroachDB passes the persistence and domain suites locally (73 tests,
including migrations through `0009` and the provider-aware vector DDL), which
is the coverage that matters most for portability. The full suite against it is
running at the time of writing.

Until that completes, the honest statement is: **CockroachDB code paths are
unit-tested for compilation, configuration, and strategy selection, and
live-integration-tested for persistence, migrations, and domain behaviour.**
That is not the same as the whole suite, and the difference should not be
rounded away.

CI runs CockroachDB as a job gated on `KAE_COCKROACHDB_CI_ENABLED`, so its
absence cannot fail the pipeline and its presence is a deliberate choice.
