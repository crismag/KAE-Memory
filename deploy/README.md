# Deployment

Everything needed to install KAE-Memory onto a target system. **Nothing here is
application code.** The API and the worker are application components and live in
[`../src/kae_memory/`](../src/kae_memory/); this directory only installs and
supervises them.

This structure is **intentionally minimal**. It exists so that every file the
first working demonstration needs has one clear home — not to build a deployment
platform. Directories appear when a real file belongs in them, never to reserve a
name.

## Boundary

```text
KAE application code
    is independent from
generic Linux deployment          deploy/server/
    which is extended by
small AWS-specific integrations   deploy/aws/
    while secrets remain outside Git
```

| Responsibility | Location |
| --- | --- |
| Python business logic, API, worker | [`../src/kae_memory/`](../src/kae_memory/) |
| Frontend source | `frontend/`, when implementation begins (ADR-0009) |
| Safe committed defaults | [`../config/`](../config/) |
| Local credentials and overrides | ignored `.env`, `.local/`, `.secrets/` |
| Generic Linux installation, systemd, reverse proxy | [`server/`](server/) |
| EC2 bootstrap and IAM | `aws/ec2/`, when files exist |
| SQS creation and queue policy | `aws/sqs/`, when files exist |
| Local developer command | `scripts/`, when scripts exist |
| Deployment and recovery procedure | [`../operations/runbooks/`](../operations/runbooks/) |
| Architecture explanation | [`../docs/`](../docs/) |

The distinction between `scripts/` and `deploy/`: **`scripts/` operates the
project; `deploy/` installs it onto a target system.**

## Why this shape

ADR-0013 makes the API and worker **portable processes**. They must run unchanged
locally, under Docker Compose, under an OS process supervisor, or on a managed
container runtime. The runtime's only job is keeping a process alive; CockroachDB
stays authoritative for runnable work, leases, checkpoints, and recovery.

Organising by *responsibility* rather than by *hosting vendor* is what keeps that
true. `server/` holds files reusable on any conventional Linux host; `aws/` holds
only what is genuinely AWS-specific. EC2-specific files must not duplicate the
generic systemd or reverse-proxy configuration — they invoke it.

## What is deliberately absent

No Docker, no Kubernetes, no Terraform or CloudFormation, no per-provider source
trees, and no speculative AWS service directories. Shell scripts are acceptable
for the first deployment; automated rollback and release version management are
deferred.

These may become valid later. They are not part of the minimum current
architecture, and creating them now would imply decisions nobody has made.

## Blocking gaps

One of the two things this directory installs now exists. `python -m
kae_memory.api` serves the HTTP contract (ADR-0014) and answers `GET /health`.
The worker does not:

- `python -m kae_memory.worker` has no `__main__`;
- the worker is a library, not a process. It claims, checkpoints, and recovers,
  but has no daemon loop, no signal handling, and no environment configuration.
  `WorkerConfig.idle_poll_seconds` and `graceful_shutdown_seconds` are declared
  and never used.

That second one decides how well any of this works. systemd sends `SIGTERM`
before forcing termination, and ADR-0007's graceful path — stop accepting work,
checkpoint, release the lease — only runs if something catches it. Until it does,
every restart is a hard kill and the run waits out its full 30-second lease
expiry rather than being released immediately. Recovery still succeeds; it is
just slower and less deliberate than it should look in a demonstration.

Service files, install and deploy scripts, and reverse-proxy configuration are
added in M10, once the worker is a process too.

**The API has no authentication** (ADR-0014). The MVP defers it, so any
deployment must keep the API behind a network boundary. It binds to loopback
unless `KAE_API_HOST` says otherwise, which is a default, not a defence.
