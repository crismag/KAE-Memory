# Generic Linux application host

Files here must be reusable on **any conventional Linux server** — an EC2
instance today, a different VPS later — with no change. Nothing in this directory
may assume a hosting provider.

This is the **required** deployment profile under ADR-0013: an OS process
supervisor running the API and the worker as independently restartable services
against CockroachDB Cloud. It satisfies durable continuation without a paid
managed container runtime.

## Layout

```text
deploy/server/
├── README.md
├── install.sh
├── deploy.sh
├── services/
│   ├── kae-api.service
│   └── kae-worker.service
└── reverse-proxy/
    └── kae.conf.example
```

### `install.sh`

Prepares a host: validate or install the supported Python runtime, create the
service user, prepare the application directory and virtual environment, install
dependencies, create writable log and runtime directories, install the service
definitions.

It must **not** install Docker, assume a provider, embed credentials, create AWS
resources, or silently modify unrelated host configuration.

### `deploy.sh`

Updates a release: install code and dependencies, run migrations, restart both
services, and health-check the result. The first version may be simple.
Automated rollback and release version management are deferred.

### systemd services

Two units, `kae-api.service` and `kae-worker.service`, **independently
restartable**. Each runs as a non-root user, loads runtime variables from a
host-managed environment file outside the repository, restarts on unexpected
failure, uses an explicit working directory, and invokes a supported repository
entrypoint. No credentials in unit files.

`kae-worker.service` is what makes the recovery demonstration real: killing it
and letting systemd restart it is exactly AT-009, restated by ADR-0013 as
terminating the worker *process* and letting the *configured supervisor* restart
it.

`TimeoutStopSec` on the worker unit is 35 seconds, deliberately longer than the
worker's 25-second `graceful_shutdown_seconds`. Were it shorter, systemd would
`SIGKILL` a worker still checkpointing and turn a graceful handover back into a
thirty-second expiry wait — the exact behaviour the handler exists to avoid.

### Reverse proxy

**One** example configuration for the proxy actually chosen for the first
deployment — not parallel Nginx, Apache, and Caddy variants. It should forward to
the API, be HTTPS-ready, route health checks, and
set a reasonable request-size limit.

## Constraints

Strict error handling where practical (`set -euo pipefail`). Never log secret
values. Environment-specific values arrive through environment variables. Keep
the first deployment understandable and manually reproducible.
