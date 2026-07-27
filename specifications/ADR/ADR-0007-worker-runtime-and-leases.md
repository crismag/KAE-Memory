# ADR-0007 — Durable worker runtime and renewable run leases

- **Status:** accepted
- **Date:** 2026-07-27
- **Closes:** OQ-015
- **Scope:** the M7 recovery mechanism. Implementation is M7; this decision does
  not authorise it to begin before the record exists.

## Context

Recovery after worker death is the demonstration's central proof (AT-005,
AT-009). It depends entirely on how a run is claimed and how a dead worker's
claim is released. M5 built the durable run record; nothing yet claims one.

The constraint that shapes the whole decision: **CockroachDB row locks last only
for the transaction.** A long-running model call therefore cannot be protected by
holding `SELECT ... FOR UPDATE` open. The durable claim must be committed
database state, not an open transaction.

## Decision

### 1. Worker runtime

A dedicated, long-running Python worker process, **separate from the HTTP
application**. It polls CockroachDB for runnable or reclaimable runs, atomically
claims one, executes one durable workflow step at a time, persists the result and
next checkpoint after every step, renews its lease while work is active, and
resumes from the latest committed checkpoint after failure.

The first demonstrable release runs **one worker process with one active run at a
time**. The persistence design supports multiple workers; concurrency is not
required for the proof and is not built.

**Explicitly rejected:**

- in-process API background tasks;
- an in-memory queue as the authoritative owner;
- a lease represented only by a process lock;
- a CockroachDB transaction held open for the duration of AI work.

### 2. Lease mechanism — fencing token

A CockroachDB-backed renewable lease with a **monotonically increasing
`lease_token`**. On every acquire or reacquire, `lease_token = lease_token + 1`.

Every heartbeat, checkpoint, completion, failure, and release must match owner
**and** token **and** an unexpired lease:

```sql
WHERE run_id = :run_id
  AND lease_owner = :worker_id
  AND lease_token = :lease_token
  AND lease_expires_at > now()
```

The token is the load-bearing part. A worker identifier alone is insufficient: the
original worker can recover *after* its lease has been reassigned, and would
otherwise write over the newer owner's work. With fencing, its update matches zero
rows and it must stop.

Claiming is one short atomic transaction that commits immediately:

```sql
UPDATE agent_runs
SET status = 'running',
    lease_owner = :worker_id,
    lease_token = lease_token + 1,
    lease_acquired_at = now(),
    lease_expires_at = now() + INTERVAL '30 seconds',
    heartbeat_at = now(),
    attempt_number = attempt_number + 1
WHERE agent_run_id = (
    SELECT agent_run_id FROM agent_runs
    WHERE status IN ('pending', 'running', 'failed')
      AND next_attempt_at <= now()
      AND (status <> 'running' OR lease_expires_at < now())
    ORDER BY created_at
    LIMIT 1
    FOR UPDATE
)
RETURNING *;
```

Exact SQL may need adjustment for the planner. The semantic requirement is
absolute: **select and transition ownership atomically, commit immediately, and
never hold the claim transaction open while executing external work.**

CockroachDB is serializable and returns SQLSTATE 40001 under contention. Claim,
heartbeat, checkpoint, and completion all run inside bounded client-side retry —
the existing `run_transaction` helper already provides this.

### 3. Schema — additive revision `0003`

`agent_runs` (revision `0002`) has `status`, `attempt_number`,
`continuation_state`, `error_code`, and `error_message`. The lease fields do not
exist and are added in an **additive revision `0003`**:

| New column | Type | Purpose |
| --- | --- | --- |
| `lease_owner` | `STRING` nullable | worker identifier holding the claim |
| `lease_token` | `INT8` not null, default 0 | fencing token |
| `lease_acquired_at` | `TIMESTAMPTZ` nullable | when the current claim began |
| `lease_expires_at` | `TIMESTAMPTZ` nullable | reclaim eligibility boundary |
| `heartbeat_at` | `TIMESTAMPTZ` nullable | last renewal |
| `next_attempt_at` | `TIMESTAMPTZ` not null, default `now()` | retry backoff gate |

Index `(status, next_attempt_at)` to support the claim query.

**Reuse rather than duplicate** — this reconciliation is part of the decision:

| ADR-0007 draft name | Existing column, reused |
| --- | --- |
| `attempt_count` | `attempt_number` |
| `checkpoint` | `continuation_state` |
| `last_error` | `error_code` + `error_message` |

Likewise the status vocabulary. The draft used `queued` and `retry_wait`; the
domain's `RunStatus` already defines `pending`, `running`, `interrupted`,
`succeeded`, `failed`, `cancelled`, `abandoned`. **The existing enum stands** —
`queued` maps to `pending`, and `retry_wait` is expressed as `failed` with a
future `next_attempt_at` rather than a new status. Two vocabularies for one
concept is the drift the terminology table forbids, and the domain enum is already
implemented, exported, and tested.

`interrupted` remains meaningful and is now precisely defined: a run whose lease
expired without a reported outcome. A reclaiming worker may find a run in
`running` with an expired lease and record it as `interrupted` before resuming.

### 4. Lease timing

| Parameter | Value |
| --- | --- |
| Lease duration | 30 seconds |
| Heartbeat interval | 10 seconds |
| Reclaim eligibility | immediately after `lease_expires_at` |
| Idle polling interval | 2 seconds |
| Graceful shutdown allowance | up to 25 seconds |
| Maximum work between durable checkpoints | one workflow step |

Thirty seconds gives three heartbeat opportunities before expiry, and keeps the
worker-death demonstration fast enough that an audience is not waiting minutes for
recovery.

**The lease does not require the model call to finish within 30 seconds.** The
worker renews concurrently while the step executes. The external operation carries
its own bounded timeout.

Demonstration targets:

- ordinary recovery: **30–45 seconds** after hard worker death;
- graceful termination: stop accepting work, attempt a checkpoint, release or
  shorten the lease;
- hard kill: the lease expires and a replacement worker reclaims it with no
  manual action.

### 5. Processing guarantee

> **At-least-once step execution with fenced ownership, durable checkpoints, and
> idempotent step effects.**

**Exactly-once is not claimed and must not be implied anywhere in the product or
the demonstration.** A worker can complete an external call and die before
recording the result; the system tolerates replay.

Every externally visible step carries an idempotency identity of
`run_id + step_name + step_attempt_identity`. Where a provider supports
idempotency keys, that identity is passed through. Where it does not, request and
response boundaries are recorded and the reconciliation behaviour is stated
explicitly rather than assumed.

## Interaction with OQ-016

This decision favours **ECS Fargate** — API as one service, worker as a separate
service, worker desired count 1 — because a stopped ECS task is replaced by the
scheduler to maintain desired count, which maps directly onto AT-009: the
replacement worker starts, sees the expired lease, and resumes. A stopped task
receives SIGTERM before forced termination, so the worker supports both graceful
release and hard-death recovery.

App Runner suits the HTTP application but fits a dedicated polling worker poorly
and gives less direct control over the task-lifecycle demonstration.

**OQ-016 is not decided here.** It is recorded formally at M10, informed by the
M7 local kill-and-recovery test. The ordering matters: **CockroachDB owns recovery
semantics; AWS merely supplies replacement compute.** Deciding the runtime first
would let the compute platform silently dictate the recovery model.

## Consequences

**Positive.** Worker death loses no run and needs no manual intervention. Recovery
normally begins within 30–45 seconds. Slow external operations stay owned through
concurrent renewal. A stale worker cannot overwrite a newer one — its token is no
longer current. Compute replacement and run ownership stay separate concerns.

**Negative.** Steps and external effects must tolerate replay, which constrains
how they are written. One worker with one active run means no throughput story for
the demonstration. Six columns and an index are added to `agent_runs`.

**Accepted risk.** At-least-once means a duplicate external side effect is
possible where a provider offers no idempotency key. The mitigation is recorded
request and response boundaries plus explicit reconciliation — not a claim that it
cannot happen.

## Related

- [`../AGENT_EXECUTION_MODEL.md`](../AGENT_EXECUTION_MODEL.md) — run status model and continuation
- [`ADR-0005-m5-physical-schema.md`](ADR-0005-m5-physical-schema.md) — the `agent_runs` table this extends
- [`ADR-0006-extraction-contract.md`](ADR-0006-extraction-contract.md) — bounded external timeouts and idempotency identities
