# AWS Demonstration Baseline

**Status:** approved scope, 2026-07-27.

**Amended by [`../../specifications/ADR/ADR-0013-portable-runtime-and-optional-aws.md`](../../specifications/ADR/ADR-0013-portable-runtime-and-optional-aws.md).**
Everything below describes the **optional AWS enhancement**. The *required* M10
profile is portable API and worker processes under Docker Compose or an
operating-system supervisor, against CockroachDB Cloud. AWS strengthens the
production story; it does not gate feature completion.

Defines the smallest AWS footprint that proves the deployment claim. This is a
**demonstration** baseline, not a production architecture.

## What deployment must prove

The same five claims apply to both acceptance levels. Only the platform differs.

1. The application is deployed and reachable.
2. Compute is disposable — killing the worker loses no project knowledge.
3. Agent work can restart on a different instance.
4. CockroachDB retains continuity across that restart.
5. Secrets and logs are managed properly.

If a service does not contribute to one of those five claims, it is out of scope.

## Shape

```text
Web UI
  |
  v
KAE Application API        deployed container, health endpoint
  |
  v
Agent worker               disposable; may be the same container or a second one
  |
  v
CockroachDB Cloud          durable, authoritative store
```

## Required components

| Component | Requirement |
| --- | --- |
| Application runtime | one container service (ECS Fargate or App Runner). One service, not a fleet. |
| Worker | one worker process, restartable. May start as a second container of the same image. |
| Secrets | AWS Secrets Manager or SSM Parameter Store. No credentials in images, environment files, or the repository. |
| Logs | CloudWatch Logs with structured output, including run identifiers so a run can be traced across restarts. |
| Health endpoint | `GET /health` — see below. |
| Deployment | reproducible from a documented command or committed infrastructure-as-code. No console click-paths. |
| Teardown | a documented procedure that removes billable resources. |

## Health endpoint

`GET /health` returns:

- overall status;
- database connectivity;
- the applied migration revision;
- application version or commit;
- worker liveness, if the worker is separately addressable.

It must not require authentication, must not leak credentials or connection
strings, and must be cheap enough to poll.

## Explicitly avoided

- Kubernetes;
- microservice decomposition;
- event buses and many Lambdas;
- multi-region or multi-AZ failover engineering;
- autoscaling policies;
- CDN, WAF, and custom domains beyond what the demo needs;
- production-grade observability stacks.

The demo proves the chain works. It does not prove the chain scales.

## Secrets management

### Local development

- Configuration comes from environment variables loaded from an untracked
  `.env`. `.env` is already gitignored; keep it that way.
- A committed `.env.example` documents every required variable with placeholder
  values and no real secrets.
- MCP credentials are developer-local editor configuration and are never
  committed or pasted into documents, issues, pull requests, or agent
  transcripts. See
  [`../06_architecture/MCP_ACCESS_POLICY.md`](../06_architecture/MCP_ACCESS_POLICY.md).
- A credential that appears in a shared transcript is compromised and must be
  rotated.

### Deployed

- Secrets live in Secrets Manager or Parameter Store and are injected at
  runtime. They are never baked into an image or committed to infrastructure
  code.
- The application database user is least-privilege and dedicated to the
  application: DML on domain tables and nothing more. Never `root`. Migrations
  run under a separate, more privileged credential.
- The Cloud API / MCP service-account key is never reused as the application
  database credential. They are separate credentials with separate blast radii —
  see [`../06_architecture/MCP_ACCESS_POLICY.md`](../06_architecture/MCP_ACCESS_POLICY.md).
- The connection URI is read from configuration at startup, so the credential can
  change without a code change and the application is restartable after the
  secret rotates.
- Manual rotation is documented. **Automated SQL credential rotation and
  zero-downtime secret refresh are deferred** to deployment hardening unless the
  demonstration requires them.
- Logs must not contain connection strings, bearer tokens, or full message
  content that could carry secrets.

## Cost control

Before any billable service is launched, record its purpose, region,
cost-control settings, credential storage, network access, teardown procedure,
local alternative, and health check — the Gate D checklist in
[`CODEX_CLAUDE_EXECUTION_ROADMAP.md`](CODEX_CLAUDE_EXECUTION_ROADMAP.md).

Development uses a CockroachDB Cloud cluster sized for the demo, not for load
testing.

## Acceptance

- **AT-008** — the deployed health endpoint reports healthy with the expected
  migration revision.
- **AT-009** — terminating the worker task and letting the platform restart it
  results in the interrupted run being resumed and completed, with no duplicated
  knowledge and no manual intervention.
