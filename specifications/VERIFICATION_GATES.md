# Verification gates

Claims this repository does not yet have the evidence to make. Each one is open
because something is unverified, not because someone forgot to close it.

A gate here is a current engineering obligation. It is not a development
worklog, and nothing enters it because it was once planned — only because a
supported property of KAE-Memory is asserted somewhere and not demonstrated.

**Nothing here may be closed against the local test database alone.** Each gate
names the evidence that would settle it; anything less leaves it open.

Established 2026-08-07 from the four obligations carried in the development
register that preceded it. Two were re-checked against current code and are
unchanged, one has widened, and one can no longer be settled here.

---

## VG-1 — CockroachDB Cloud schema state

**Status: retired by architectural decision, 2026-08-07. Not proven.**

The historical CockroachDB Cloud environment is no longer an active operational
dependency, and recreating it solely to answer a historical question is not
required. The gate closes because the question stopped mattering, **not because
the schema was verified** — that distinction is the whole reason this entry
stays rather than being deleted.

Any future CockroachDB compatibility claim must be verified against a currently
available, intentionally provisioned environment. This retirement transfers to
no such claim.

The record of what was at risk follows.

**The claim at risk.** That a specific CockroachDB Cloud cluster's schema and
data survived a migration-test defect, since fixed. The defect: the migration
test pointed Alembic at a throwaway database, but `migrations/env.py` resolved
`KAE_DATABASE_URL` before the Alembic config, so with a developer environment
loaded a downgrade ran against whatever that variable named — and then passed,
because it inspected the empty throwaway and found no tables.

**Why it could not be answered.** The cluster is disabled after exhausting its request
allowance and refuses connections outright. Whether its schema survived earlier
runs is unknown and unverifiable while it stays that way. A question does not
stop having an answer because the work moved elsewhere.

**Why it no longer blocks anything.** KAE-Memory runs on PostgreSQL. The dataset
that cluster held is not the only copy — 218 rows across 13 tables were copied
and verified table by table. A total loss of that cluster would cost the
cluster, not the work.

**What would have been required to answer it:** connectivity restored, a
read-only inspection of the migration revision and schema, pending migrations
applied deliberately, and the provider-specific integration tests run against
it. None of this was done, and the entry does not claim otherwise.

**This cannot be closed by pointing at PostgreSQL.** That verifies PostgreSQL.

**Decided 2026-08-07:** the cluster is not restored. The guard that prevented
the loss is in place regardless (`tests/conftest.py` requires `test` in the
database name), and the dataset was copied and verified before this was taken.

---

## VG-2 — Retrieval threshold on a grown corpus

**Status: open. Deferred by measurement, not blocked.**

**The claim at risk.** That `MAX_DISTANCE = 0.85` separates genuine matches from
noise at corpus sizes beyond the one it was fitted to.

**Current state, verified 2026-08-07:** still `0.85`, in
`src/kae_memory/domain/chunks.py:37`, unchanged since it was set.

It was fitted to twenty queries over thirty-two chunks. The usable window
between the worst genuine match (0.840) and the nearest noise (0.847) is
**0.005 wide**, and one weak query already leaked at fitting time. A constant
that narrow does not survive a corpus that grows.

**Evidence required to close:** re-run `scripts/development/evaluate-retrieval.py`
against a materially larger corpus and record the separation. Hybrid ranking,
not a better constant, is the durable answer — closing this by widening the
number would be closing it by making it wrong less visibly.

---

## VG-3 — Reviewer identity is unattested

**Status: open. Accepted risk.**

**The claim at risk.** That a `reviewer` recorded against a confirmation
identifies the person who made it.

An agent that supplies a `reviewer` name records a human decision nobody made.
Nothing in this layer detects it: the field is free text on the review routes,
and no adapter attests it.

**Current state, verified 2026-08-07:** unchanged. `reviewer` remains
caller-supplied on the confirm and reject paths.

**Evidence required to close:** an identity KAE-Memory can verify rather than
accept. MCP does not carry one, so this stays open until an authenticated
identity reaches the review path.

**Consequence of leaving it open:** confirmation provenance is trustworthy about
*what* was confirmed and *when*, and only as trustworthy as the caller about
*who*.

---

## VG-4 — CockroachDB integration breadth

**Status: open. Conditional release gate, 2026-08-07.**

Cross-provider parity matters only where CockroachDB compatibility is claimed.
The suite is therefore run **before**, and not otherwise:

- claiming support for a new CockroachDB-compatible release;
- changing provider-specific behaviour;
- publishing or renewing a CockroachDB compatibility guarantee;
- shipping a change that could affect cross-provider behaviour.

It is not run for documentation work, and was not run for Phase 2A planning.

**What this means for what may be written:** documentation may say CockroachDB
is a *selectable provider* (ADR-0022) and that parity was demonstrated at
revision `0009` on 2026-08-04. It may not describe CockroachDB as verified at
the current schema head. The wider the gap below grows, the more carefully that
sentence has to be written.

**The claim at risk.** That "both providers are supported" (ADR-0022) holds for
the current schema, not only for the one it was measured against.

**Last full parity run: 2026-08-04, at revision `0009`.** The same 675 tests
passed on both engines — PostgreSQL in 1m 46s, CockroachDB in 7h 30m. That
250× difference is why re-running it is a release decision rather than a routine
one, and why CockroachDB is a CI job gated on `KAE_COCKROACHDB_CI_ENABLED`
rather than a default.

**Current state, verified 2026-08-09: the schema head is `0022`.** Thirteen
revisions have landed since the last parity run, against three at the previous
review of this gate. The suite has also grown from the 675 tests the parity run
covered to 1885, so the gate is now stale in two dimensions at once: newer
schema, and a far larger body of behaviour never exercised on CockroachDB.
CockroachDB tests are additionally deselected by default (`-m "not cockroachdb"`,
ecosystem `RUN-D2`), which makes the drift silent rather than merely known. Engine-specific behaviour sits behind every one that adds a
unique or check constraint — the class of divergence that produced revision
`0009` in the first place, when CockroachDB and PostgreSQL compiled `Integer`
differently.

**Evidence required to close:** a full suite run on CockroachDB at the current
head, with the count and revision recorded here.

**Treat the 2026-08-04 result as the record of a run, not a standing guarantee.**

---

## What this file is not

Not a roadmap, not a milestone list, and not a place for work that is merely
unfinished. A gate belongs here only while KAE-Memory asserts something it
cannot currently demonstrate.

When a gate closes, the evidence goes in the ADR or specification that carries
the claim, and the gate is removed rather than annotated. A register of closed
gates is a worklog.
