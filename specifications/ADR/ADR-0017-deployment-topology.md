# ADR-0017 — Deployment topology: EC2, static frontend hosting, CockroachDB Cloud

- **Status:** accepted
- **Date:** 2026-07-29
- **Closes:** OQ-018
- **Satisfies:** FR-016, FR-017, FR-018
- **Depends on:** [`ADR-0013`](ADR-0013-portable-runtime-and-optional-aws.md), [`ADR-0009`](ADR-0009-discovery-workspace-frontend.md), [`ADR-0014`](ADR-0014-http-api-contract.md)
- **Milestone:** M10

## Context

ADR-0013 made the API and worker portable processes, required an OS supervisor
or Docker Compose, and named ECS on Fargate as the *preferred optional* hosted
reference. OQ-018 asked whether EC2 with systemd should take that place instead.

The answer is now settled by what is actually being built: **one EC2 instance for
compute, static hosting for the frontend, CockroachDB Cloud for state.**

## Decision

```text
Browser
   |
   v
Static frontend hosting            built assets, no server runtime
   |  (HTTPS, cross-origin or proxied)
   v
EC2 instance                       nginx -> kae-api.service
   |                                       kae-worker.service
   v
CockroachDB Cloud                  authoritative for everything durable
```

### EC2 with systemd is the hosted reference

ECS on Fargate is no longer the reference. EC2 satisfies ADR-0013's **required**
profile directly — an OS process supervisor with automatic restart — so the
required and optional profiles collapse into one, which is a simplification
rather than a compromise.

`kae-api.service` and `kae-worker.service` are separate units, independently
restartable. The worker unit is what makes AT-009 real: `systemctl restart
kae-worker` is the recovery demonstration.

### The frontend is static assets, hosted anywhere

ADR-0009 already decided client-side rendering with no JavaScript server runtime,
so the build output is a directory of files. Hostinger is the first target; the
contract is generic — serve `dist/`, rewrite unknown paths to `index.html` for
the router, and point the client at an API base URL.

Nothing vendor-specific enters the source tree. A different host later consumes
the same output.

### CockroachDB Cloud stays authoritative

Unchanged, and load-bearing: the instance holds no durable state, so replacing it
loses nothing. That is what makes the recovery demonstration honest rather than
theatrical.

## The consequence that matters most: cross-origin exposure

Splitting the frontend onto a different host makes the browser call the API
**cross-origin**. Two things follow, and the second is a genuine risk.

**CORS becomes necessary.** The API must return `Access-Control-Allow-Origin` for
the frontend's origin. It is configured through `KAE_CORS_ORIGINS` and defaults
to **empty** — no origin allowed — so a misconfigured deployment fails closed.

**An unauthenticated API becomes reachable from a browser on the public
internet.** ADR-0014 recorded that the MVP defers authentication and that the API
is therefore *"unsafe to expose publicly"*. A cross-origin frontend is exactly
the shape that exposes it.

Two deployments satisfy this ADR, and they are not equally safe:

| Shape | Exposure | Use |
| --- | --- | --- |
| **Same-origin (recommended)** — nginx on EC2 serves the built frontend *and* proxies `/v1`; no CORS needed | One origin, no browser-reachable API surface beyond the proxy | Default |
| **Split-origin** — frontend on external static hosting, API on EC2 | The API is publicly reachable and unauthenticated | Only with an IP allowlist on the security group, and only for a bounded demonstration |

The same-origin shape is the default the deployment assets configure, and the
static-hosting path is documented as the deliberate exception. **Neither shape
makes an unauthenticated API safe to leave running.** The demonstration should be
torn down after it is given.

### Graceful shutdown becomes real

ADR-0013 deferred production signal handling to M10, and this is M10. The worker
now handles `SIGTERM` and honours `graceful_shutdown_seconds`: it stops accepting
work, lets the current step finish and checkpoint, and releases the lease so the
run is immediately claimable instead of waiting out its 30-second expiry.

Both paths stay correct. An ungraceful kill still recovers through lease expiry —
that is the case a real outage produces, and the recovery runbook keeps it.

## Secrets

`KAE_DATABASE_URL` carries the database password and never enters the repository,
an image, or a log. On EC2 it lives in a root-owned environment file outside the
application directory, read by systemd through `EnvironmentFile=`.

AWS access uses an **IAM instance role**, never stored keys. The instance
profile needs Bedrock invoke permission for the approved models and nothing else;
the example policy is in `deploy/aws/ec2/`.

## What this does not decide

- **SQS remains unused and unauthorised.** OQ-017 stays open. The worker polls
  CockroachDB, which is authoritative for runnable work (ADR-0007); a queue would
  be a second source of truth about work that already has one.
- **No container runtime.** No Docker, ECS, Fargate, or Kubernetes.
- **No infrastructure-as-code.** Shell scripts and a documented instance, because
  the first deployment should be manually reproducible.
- **No TLS termination decision** beyond "nginx with a certificate"; issuing and
  renewing it is an operational choice, not an architectural one.

## Consequences

**Positive.** One instance, two units, one managed database. The required and
optional profiles collapse into one shape. The frontend is portable across hosts
because it is a directory of files. Recovery is demonstrable with `systemctl`.

**Negative.** A single instance is a single point of failure, and nothing
autoscales. Acceptable because the durable state is elsewhere: the instance is
disposable and the demonstration is what it is for.

**Accepted risk.** The API has no authentication. Same-origin hosting hides it
behind a proxy; split-origin hosting does not, and relies on a security-group
allowlist that is easy to widen by accident. This is stated in the ADR, in the
deployment README, in the static-hosting README, and in the runbook — four
places, because it is the failure that would matter.

## Related

- [`ADR-0013-portable-runtime-and-optional-aws.md`](ADR-0013-portable-runtime-and-optional-aws.md) — the portable processes this deploys
- [`ADR-0014-http-api-contract.md`](ADR-0014-http-api-contract.md) — the API that has no authentication
- [`ADR-0009-discovery-workspace-frontend.md`](ADR-0009-discovery-workspace-frontend.md) — static assets, client-side rendered
- [`ADR-0007-worker-runtime-and-leases.md`](ADR-0007-worker-runtime-and-leases.md) — the graceful path this finally implements
