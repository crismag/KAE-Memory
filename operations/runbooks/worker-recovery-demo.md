# Runbook — worker recovery demonstration

Proves **AT-009**: an interrupted run resumes and completes after a worker
restart, with no duplicated knowledge and no manual intervention.

ADR-0013 restates this against the portable profile — terminate the worker
*process*, let the *configured supervisor* restart it. An AWS task replacement is
one satisfying supervisor; systemd on a Linux host is another. The steps below do
not change between them, which is the point.

## What is actually being shown

Recovery is a **CockroachDB capability**, not a platform feature. The supervisor
only starts a new process. Everything that makes the run resume — the claim, the
fencing token, the checkpoint, the expiry — is durable state in the database.

Say which thing a given demonstration proves. A supervisor restarting a process
on one host proves the **recovery protocol**. Only a real hosted run proves the
**deployment**: image pull, IAM, networking, and cross-AZ placement are not
exercised locally.

## Status

**Runnable.** `python -m kae_memory.worker` runs as a process, the daemon loop
claims work, and `SIGTERM` is handled (ADR-0017). Run state is observable over
HTTP throughout — `GET /v1/runs/{id}` shows status, attempt, and continuation
state at every step below, and `GET /v1/runs/{id}/events` streams the changes.

Show **both** shutdown paths. They prove different things.

Until then, `test_a_killed_worker_is_replaced_and_the_run_completes` demonstrates
the same nine steps in-process, using only durable state — a second `Worker`
instance holding nothing from the first.

## Procedure

1. **Start a multi-step run.** Enqueue work for a project so a run exists in
   `pending`.
2. **Confirm a worker leased it.** The run is `running` with a `lease_owner`, a
   non-zero `lease_token`, and a `lease_expires_at` roughly 30 seconds ahead.
3. **Let it checkpoint.** Confirm `continuation_state` holds at least one durable
   checkpoint. Recovery resumes from persisted state, so there must be some.
4. **Terminate the worker.** `systemctl stop kae-worker`, or kill the process.
   Do not touch the database.
5. **Wait for the lease to expire.** Roughly 30 seconds. Nothing may reclaim the
   run before then — that wait *is* the safety property.
6. **Start a replacement.** `systemctl start kae-worker`, or let the supervisor's
   restart policy do it.
7. **Confirm reclamation with a higher fencing token.** The new `lease_owner`
   differs and `lease_token` has increased. The old worker, if it somehow
   returned, could no longer write: every write is fenced on owner *and* token.
8. **Confirm continuation.** Execution resumes from the checkpoint recorded in
   step 3, not from the beginning.
9. **Confirm the result is recorded once.** The run reaches `succeeded`, and its
   knowledge appears exactly once. No manual repair at any point.

## Verifying step 9

Duplication is the failure this design most needs to rule out, because execution
is **at-least-once, never exactly-once**. Check that the run produced one set of
knowledge items — `knowledge_produced_by` for the run — rather than one set per
attempt. Agents short-circuit on terminal runs for exactly this reason.

## If the run does not resume

- **Still `running` with an unexpired lease** — the old worker is alive. Its
  heartbeat is extending the lease, which is correct behaviour; find and stop it.
- **Nothing claims it after expiry** — the replacement worker is not polling.
  Check the service is running and that it reaches CockroachDB; a connection
  failure looks identical to an idle queue.
- **`abandoned`** — the run exhausted its retry budget. That is a terminal
  outcome, not a recovery failure. Read `error_code` and `error_message`.

## Two shutdowns, two proofs

**Ungraceful — `kill -9`, or the instance disappearing.** The lease is never
released, so the replacement waits out the ~30-second expiry before claiming.
This is the case a real outage produces, and the wait *is* the safety property:
nothing may reclaim a run whose owner might still be alive.

**Graceful — `systemctl restart kae-worker`.** `SIGTERM` reaches the worker, the
current step finishes and checkpoints, the lease is released, and the replacement
claims immediately. No wait.

Both are correct. Show the ungraceful one to prove the protocol and the graceful
one to prove the deployment. Saying which is which matters: a demonstration that
only shows the fast path has not shown recovery at all.
