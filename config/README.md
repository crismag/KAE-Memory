# Committed configuration

Non-secret application configuration that belongs in version control.

Empty by design for now. Every runtime value KAE currently needs arrives through
environment variables — see [`../.env.example`](../.env.example) — and the
defaults that exist live beside the code that uses them, as typed constants
rather than untyped YAML:

| Default | Where |
| --- | --- |
| Lease duration, heartbeat interval | `domain/execution.py` |
| Worker poll and shutdown timing | `worker/runner.py` (`WorkerConfig`) |
| Retry policy for serialization failures | `persistence/transactions.py` |
| Embedding model, dimensions, version | `agents/embedding.py`, `domain/chunks.py` |
| Readiness template, weights, draft threshold | `domain/readiness.py` |

A file appears here when a value must be changed **without a code change** —
plausibly `defaults.yaml` and `logging.yaml`. Moving a constant here purely to
have configuration would trade a type-checked default for an untyped one and gain
nothing.

## What may live here

Default runtime behaviour, logging configuration, feature defaults, queue names
as overridable logical names, retry defaults, worker lease defaults, application
limits, and other safe environment-independent settings.

## What may never

Passwords, API keys, connection strings containing credentials, AWS access keys,
bearer tokens, private certificates, or production host addresses that should
stay environment-controlled. Those belong in the ignored `.env`, `.local/`, or
`.secrets/` — never in Git.

No `development/`, `staging/`, or `production/` subdirectories until meaningful
differences actually exist between them. Environment-specific values are supplied
through environment variables first.
