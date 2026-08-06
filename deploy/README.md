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
| Safe committed defaults | [`../config/`](../config/) |
| Local credentials and overrides | ignored `.env`, `.local/`, `.secrets/` |
| Generic Linux installation, systemd, reverse proxy | [`server/`](server/) |
| EC2 bootstrap and IAM | [`aws/ec2/`](aws/ec2/) |
| SQS creation and queue policy | `aws/sqs/`, if OQ-017 is ever decided |
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

## The one thing to keep in mind

Both entrypoints now exist and both run as supervised processes. `python -m
kae_memory.api` serves the HTTP contract (ADR-0014); `python -m
kae_memory.worker` claims and executes queued runs and handles `SIGTERM`
(ADR-0017). It claims, checkpoints, and recovers,
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

**The API authenticates with bearer tokens** (ADR-0024), and refuses to start
if it would listen off loopback without `KAE_API_TOKENS` set. Superseded the
MVP's deferred-authentication position. Any
deployment must keep the API behind a network boundary. It binds to loopback
unless `KAE_API_HOST` says otherwise, which is a default, not a defence.
