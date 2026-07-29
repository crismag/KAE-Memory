# Runbook — restarting services

```bash
sudo systemctl restart kae-api        # stateless; safe at any time
sudo systemctl restart kae-worker     # drains first, see below
sudo systemctl status kae-api kae-worker
journalctl -u kae-worker -f
```

## What happens when the worker restarts

`SIGTERM` reaches the worker, which stops claiming, lets the current step finish
and checkpoint, and **releases its lease** — so the run is immediately claimable
rather than waiting out its thirty-second expiry (ADR-0017).

The unit allows 35 seconds for this, deliberately more than the worker's
25-second `graceful_shutdown_seconds`. If `TimeoutStopSec` were the shorter of
the two, systemd would `SIGKILL` a worker that was still checkpointing and turn a
graceful handover back into an expiry wait.

A run in flight is **not lost** either way. The difference is how long the
handover takes, and whether the lease is released or expires.

## When a restart does not help

| Symptom | Cause | Action |
| --- | --- | --- |
| API restarts in a loop | `KAE_DATABASE_URL` unset or wrong | `journalctl -u kae-api -n 30`; fix the environment file |
| `/health` reports `database: down` | Cluster unreachable, or the IP allowlist excludes the host | Check CockroachDB Cloud networking |
| `migration_revision` is null | Migrations never ran | `alembic upgrade head` |
| Runs stay `pending` | Worker not running, or cannot reach the database | A connection failure looks exactly like an idle queue — check the logs, not the queue |
| A run is `abandoned` | Retry budget exhausted | Terminal, not a restart problem. Read `error_code` and `error_message` |

## Full restart

```bash
sudo systemctl restart kae-worker kae-api nginx
curl -s localhost:8000/health
```

Order matters slightly: the worker drains first, and restarting the API under it
would not have helped it finish.
