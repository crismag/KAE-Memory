# ADR-0013 — Portable runtime and optional AWS deployment

- **Status:** accepted
- **Date:** 2026-07-27
- **Closes:** OQ-016
- **Blocks:** M10 — AWS Demonstration
- **Depends on:** [`ADR-0007`](ADR-0007-worker-runtime-and-leases.md)
- **Amends:** FR-016, and the AWS demonstration baseline

## Decision

The API and durable worker are **portable, independently executable Python
processes**:

```text
python -m kae_memory.api
python -m kae_memory.worker
```

Core functionality must not depend on ECS, Fargate, or any particular process
supervisor. Both must run **without code changes** under direct local processes,
Docker Compose, a conventional OS process supervisor, and ECS on Fargate.

CockroachDB stays authoritative for runnable work, leases, fencing tokens,
checkpoints, retry state, and recovery. **The deployment runtime's only job is
keeping a process alive.**

That separation is the point. ADR-0007 deliberately deferred this decision until
M7's recovery behaviour was observable, precisely so the compute platform could
not quietly define the recovery model. Recovery is a CockroachDB capability that
happens to run on AWS, not an AWS feature.

### Required profile

Docker Compose or an OS process supervisor, API and worker as separate services,
worker configured for automatic restart.

The recovery demonstration:

1. start a multi-step run;
2. persist at least one durable checkpoint;
3. terminate the active worker process;
4. let the supervisor start a replacement;
5. let the previous lease expire;
6. reclaim with a higher fencing token;
7. resume from the latest checkpoint;
8. complete with no manual run repair;
9. verify authoritative outputs were not duplicated.

This satisfies durable continuation **without a paid managed container runtime**.

### AWS reference deployment — preferred, not required

ECS on Fargate is the preferred production reference and **optional for feature
completion**. When enabled: one load-balanced ECS service for the API, one
non-public service for the worker, desired count one each, IAM task roles, and
CockroachDB as the authoritative orchestration store.

ECS task replacement supplies process availability. **It does not replace or
modify the lease and checkpoint protocol.**

### Portability requirements

No ECS-specific run ownership, restart, or recovery logic in application code.
Runtime concerns arrive through configuration and deployment adapters: process
commands, environment variables, secret injection, health checks, shutdown
signals, logging destinations, restart policies. **The same worker implementation
runs everywhere.**

### Lambda

Not the durable worker runtime. It may later handle bounded event work — webhooks,
object-upload reactions, scheduled maintenance triggers, short integrations — and
may *create* AgentRun records, but the portable worker executes their workflows.

## Amendment to FR-016 — the requirement said AWS

FR-016 as approved reads: *"The application, one worker, and CockroachDB Cloud are
**deployed to AWS** such that the application is reachable, compute is
disposable, and an interrupted run resumes after a worker restart."*

This decision makes AWS optional, so the requirement no longer matches. Rather
than let the two disagree silently, FR-016 is **amended**: the mandatory
obligation is *a deployed API and worker with automatic worker replacement and
durable recovery against CockroachDB Cloud*; AWS is one satisfying deployment,
not the definition.

The acceptance tests move with it:

| Test | As approved | Amended |
| --- | --- | --- |
| **AT-008** | the *deployed* health endpoint reports healthy with the expected migration revision | unchanged in substance; "deployed" means the required profile, AWS or otherwise |
| **AT-009** | terminating the worker **task** and letting **the platform** restart it results in the interrupted run resuming and completing, with no duplicated knowledge and no manual intervention | terminating the worker **process** and letting **the configured supervisor** restart it — same nine steps, same guarantee, no AWS dependency |

What is *not* weakened: automatic replacement, expiry-based reclamation,
checkpoint continuation, no manual repair, and no duplicated output all remain
mandatory. Only the hosting platform becomes a choice.

## Three things this needs that do not exist yet

### 1. Neither entrypoint exists

`python -m kae_memory.worker` does not run: the package contains `runner.py` and
`__init__.py`, with no `__main__.py`. `kae_memory.api` does not exist at all —
M9 builds it.

M10 must add both, and the worker entrypoint is the larger piece.

### 2. The worker is a library, not a process

`Worker` claims, executes, checkpoints, and recovers — all verified in M7. But it
has **no daemon loop, no signal handling, and no configuration from the
environment**. Two `WorkerConfig` fields are declared and never used:

- `idle_poll_seconds` (2.0) — nothing polls; `run_until_idle` stops when the queue
  empties rather than waiting for more work;
- `graceful_shutdown_seconds` (25.0) — nothing handles `SIGTERM`.

Both matter for this decision specifically. A supervisor and ECS both signal
`SIGTERM` before forcing termination, and ADR-0007's graceful path — stop
accepting work, checkpoint, release the lease — only happens if something catches
it. Without that, every shutdown is a hard kill and the run waits out its full
30-second expiry instead of being released immediately.

M10 must supply: the poll loop honouring `idle_poll_seconds`, a `SIGTERM` handler
calling `request_stop()` within `graceful_shutdown_seconds`, and configuration
read from the environment.

### 3. Health endpoint depends on M9

FR-017's `GET /health` — status, database connectivity, applied migration
revision, version — belongs to the API, which M9 delivers. AT-008 therefore
cannot pass before M9, regardless of deployment choice.

## Consequences

**Positive.** Full functionality is developable and demonstrable without
continuous Fargate cost. Local and hosted deployments exercise the same
persistence and recovery code. ECS can be added late without redesigning the
worker. Recovery stays a CockroachDB capability. A credible production path
remains. AWS can be enabled for judging and torn down afterwards.

**Negative.** Two acceptance levels means "M10 complete" is ambiguous unless the
level is stated — every claim about deployment must say which. The optional AWS
path risks going untested until late, when it is most expensive to debug.

**Accepted risk.** A supervisor restarting a process on one host is not
equivalent to a scheduler replacing a task in a cluster: it does not exercise
image pull, IAM, networking, or cross-AZ placement. The required profile proves
the *recovery protocol*; only the optional AWS run proves the *deployment*. That
distinction should be stated plainly in the demonstration rather than blurred.

## Related

- [`ADR-0007-worker-runtime-and-leases.md`](ADR-0007-worker-runtime-and-leases.md) — the lease protocol this must not duplicate
- [`../../docs/09_development/AWS_DEMONSTRATION_BASELINE.md`](../../docs/09_development/AWS_DEMONSTRATION_BASELINE.md)
- [`../../docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md`](../../docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md) — FR-016, amended here
