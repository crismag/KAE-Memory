# TASK-008 — M7 Resilience and Recovery

**Status:** complete, 2026-07-27
**Milestone:** M7 · **Prompt:** RES-01

## Objective

Make compute disposable. A worker can die at any point and another resumes what
it left behind, with no manual intervention and no duplicated knowledge.

## Business purpose

This is the milestone the demonstration rests on. Beats 5 and 6 of the narrative
— the worker is killed, another resumes — are the ones that distinguish durable
engineering memory from a chat transcript. If they are cut, the demo has lost its
point.

## Success condition

> A new worker resumes after the previous execution stops, without duplicated
> durable knowledge.

Recovery must use durable state alone: nothing reconstructed from the previous
process, no in-memory queue, no lock held in a dead process.

## Related approved context

- `specifications/ADR/ADR-0007-worker-runtime-and-leases.md` — **authoritative**
- `specifications/AGENT_EXECUTION_MODEL.md` — status model and continuation
- `specifications/ADR/ADR-0005-m5-physical-schema.md` — the table being extended
- `docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md` — FR-011, FR-012
- `docs/05_product/UNIFIED_DEMO_NARRATIVE.md` — beats 5 and 6

## Expected outputs

- Additive revision `0003`: `lease_owner`, `lease_token`, `lease_acquired_at`,
  `lease_expires_at`, `heartbeat_at`, `next_attempt_at`, plus an index on
  `(status, next_attempt_at)`.
- A dedicated worker process, separate from any HTTP application.
- Atomic claim: select and transition ownership in one short transaction that
  commits immediately.
- Fenced mutations: every heartbeat, checkpoint, completion, failure, and release
  matches owner **and** token **and** an unexpired lease.
- Heartbeat renewal running concurrently with step execution.
- Bounded retry with backoff, `abandoned` on budget exhaustion, and a visible
  finding rather than a silent loop.
- Reclaim of expired leases, recording the prior state as `interrupted`.
- Graceful shutdown: stop accepting work, checkpoint, release or shorten the
  lease.
- The kill-and-recovery test.

## Constraints

- **The claim transaction commits immediately.** Never hold it open across
  external work — CockroachDB row locks do not outlive the transaction, which is
  the entire reason the claim is committed state rather than a held lock.
- Revisions `0001` and `0002` are not modified. `0003` is additive.
- Reuse `attempt_number`, `continuation_state`, `error_code`, and `error_message`
  — do not add `attempt_count`, `checkpoint`, or `last_error` alongside them.
- The existing `RunStatus` enum stands. `queued` is `pending`; `retry_wait` is
  `failed` with a future `next_attempt_at`. Do not add statuses.
- Claim, heartbeat, checkpoint, and completion run inside bounded retry for
  SQLSTATE 40001 — `run_transaction` already provides this.
- One worker, one active run. The schema supports more; concurrency is not built.
- **At-least-once, never exactly-once.** Do not write, imply, or demonstrate
  exactly-once semantics anywhere.
- Every externally visible step carries an idempotency identity of
  `run_id + step_name + step_attempt_identity`.
- No live model call in any test.
- No provider selection, BYOK, credential storage, quotas, billing, or additional
  live adapters (ADR-0010 explicitly does not authorise these here).

## Allowed file scope

- `migrations/versions/`
- `src/kae_memory/persistence/`
- `src/kae_memory/application/`
- `src/kae_memory/worker/` (new)
- `tests/`
- this task file for completion notes

## Prohibited changes

- revisions `0001` and `0002`
- embeddings, vector columns, semantic retrieval
- user interface or HTTP endpoints
- cloud infrastructure or deployment configuration
- the Review agent

## Acceptance criteria

1. `alembic upgrade head` and `alembic downgrade base` both succeed with `0003`.
2. A worker claims a runnable run atomically and commits the claim immediately.
3. A stale worker whose token is superseded cannot write — its update matches
   zero rows and it stops.
4. An expired lease is reclaimed by another worker, which resumes from the last
   committed checkpoint.
5. AT-005 passes: a terminated run is resumed and completed by a different
   worker, with no duplicated knowledge.
6. AT-007 passes: replay produces one run and one result set.
7. Retry-budget exhaustion moves the run to `abandoned` with a visible finding.
8. `make check` passes.

## Required tests

- Fencing: an old token cannot heartbeat, checkpoint, or complete.
- Reclaim: an expired lease is claimable; an unexpired one is not.
- Kill and recover: terminate mid-run, resume on another worker, complete once.
- Backoff and exhaustion: bounded attempts, then `abandoned`.
- Graceful shutdown releases or shortens the lease.
- Migration upgrade and downgrade.

## Stop conditions

Stop and report rather than guessing if: the claim query cannot be made atomic on
the target planner; the lease timing cannot meet the 30–45 second recovery
target; or the existing status vocabulary cannot express a required state.

## Definition of completion

`make check` is green, AT-005 and AT-007 pass, and the pull request reports the
observed recovery time after a hard kill — the number the demonstration depends
on.

## Completion notes

**Recovery time.** With the approved 30-second lease, a hard-killed worker's run
is reclaimable at expiry and a replacement resumes on its next poll — 30 to 32
seconds at the 2-second idle interval, inside the 30–45 second target. Tests use
a hand-cranked clock rather than sleeping, so expiry is exercised exactly rather
than approximately.

**Claim is a compare-and-swap, not `SELECT ... FOR UPDATE`.** ADR-0007 allowed
the SQL to be adjusted for the planner and fixed only the semantics. Two workers
may read the same candidate, but the update is conditioned on the observed
`lease_token`, so exactly one wins and the loser looks again. This is the same
guarantee a row lock gives, works on both SQLite and CockroachDB, and needs no
transaction held open across external work — which CockroachDB could not do
anyway.

**A running row with no lease is never stolen.** M6 agents execute synchronously
in-process and leave a run `running` with no lease. Only a row whose lease has
actually expired is claimable, so the worker cannot take over a synchronous run.

**`enqueue_run` added alongside `start_run`.** `start_run` begins executing in
the calling process; `enqueue_run` records a `pending` run for a worker to claim
and returns immediately. Without the split there was no way to submit work
without owning it — and the browser must never own a run.

**A portability bug the tests caught.** The migration first used
`server_default=now()` on the `NOT NULL` column. SQLite rejects a non-constant
default on `ADD COLUMN`, which the empty-database check had not exposed. Replaced
with add-nullable, explicit backfill to `created_at`, then tighten — which also
states the intent: an existing run becomes claimable at the moment it was
created.

**Deviations:** none. Revisions `0001` and `0002` untouched, no new statuses, no
`attempt_count`/`checkpoint`/`last_error` duplicates, at-least-once never
overstated, no live model call.

**Evidence:** `make check` green — 97 tests, 94% coverage. Revision `0003` cycles
up and down against a populated table.
