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

**Not yet runnable end to end.** The protocol below is implemented and covered by
`tests/worker/test_recovery.py`, but there is no worker process to kill:
`python -m kae_memory.worker` has no `__main__`, and the worker has no daemon
loop or `SIGTERM` handler (ADR-0013). M10 adds all three. The API entrypoint
already exists, so run state is observable over HTTP while the demonstration
runs — `GET /v1/runs/{id}` shows the status, lease owner, and continuation
state at every step below.

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

## Expected timing

The lease expiry wait in step 5 is ~30 seconds. Today it is unavoidable: with no
`SIGTERM` handler, stopping the worker is a hard kill, so the lease is never
released deliberately and must time out.

Once M10 honours `graceful_shutdown_seconds`, a clean stop releases the lease
immediately and the replacement claims it at once. Both paths are correct;
the graceful one is faster and demonstrates better. Keep an ungraceful kill in
the demonstration too — that is the case a real outage produces.
