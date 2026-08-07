# Configuration

Two kinds, and the distinction is deliberate.

**Environment configuration** — what a deployment must supply: where the
database is, what tokens are valid, which providers to use. Never committed.

**Governed settings** — values with a contract: what they mean, their units,
sane ranges, who may override them. Deliberately few. The contract lives in
`src/kae_memory/settings/catalog.py`; the values live in `defaults.toml`.

> Under active development. Names below describe the current implementation and
> carry no backward-compatibility guarantee.

---

## Environment

### Database

| Variable | Required | Notes |
|---|---|---|
| `KAE_DATABASE_URL` | yes | `postgresql+psycopg://…` |
| `KAE_DATABASE_PROVIDER` | when ambiguous | Names the provider explicitly |
| `KAE_POSTGRESQL_URL` | no | Per-provider form |

**Never committed.** A connection string is not a product default, and the
settings catalog says so explicitly — it is why these are not governed settings.

PostgreSQL with pgvector is the target, hosted on Amazon RDS. See
[persistence and providers](../architecture/persistence-and-providers.md).

The codebase also carries a CockroachDB provider and its `KAE_COCKROACHDB_URL`
and `cockroachdb+psycopg://` forms. That integration is deferred and its
compatibility with the current schema is unverified; the page above is the only
place this documentation covers it.

### API

| Variable | Required | Notes |
|---|---|---|
| `KAE_API_HOST` | no | Interface to bind. Defaults to loopback |
| `KAE_API_PORT` | no | |
| `KAE_API_TOKENS` | **off-loopback: yes** | See below |
| `KAE_CORS_ORIGINS` | no | Defaults to empty — an unconfigured deployment fails closed |

#### `KAE_API_TOKENS`

Semicolon-separated entries, each `name:token` or
`name:token:project,project`:

```
studio:REPLACE_ME;agent:REPLACE_ME_TOO:proj-a,proj-b
```

`name` identifies the caller in logs. A third field scopes the token to named
projects; without it the token reaches every project the deployment can read.
Clients send the **bare token** as a bearer credential.

A malformed entry raises `InsecureDeploymentError` and the process does not
start. Binding off-loopback with no tokens does the same
([ADR-0024](../../specifications/ADR/ADR-0024-http-trust-boundary.md)) — a
refusal to start is a deployment that does not happen, where a warning is a log
line something scrolls past.

> **Read [security boundaries](../architecture/security-boundaries.md) before
> exposing this service.** Those two guards do not cover every deployment shape,
> and the gap is stated there. Do not assume a reverse-proxy deployment is
> authenticated because the process started.

### Worker

| Variable | Notes |
|---|---|
| `KAE_WORKER_ID` | Identifies the worker holding a lease |
| `KAE_WORKER_POLL_SECONDS` | How often the queue is polled |
| `KAE_LEASE_DURATION_SECONDS` | How long a claimed run is held before it can be reclaimed |

### Extraction and embedding

| Variable | Notes |
|---|---|
| `KAE_EXTRACTION_MODEL` | Model id for extraction. Newer Claude models on Bedrock need an inference-profile id (`global.` or `us.` prefix); a bare id fails validation |
| `AWS_REGION` | Region for Bedrock |

**Without model access, extraction falls back to a deterministic fixture.** The
pipeline completes and runs report `"model": "deterministic-fixture"`. Useful
for offline development, and worth checking before concluding a model produced
what you are reading — see
[#84](https://github.com/crismag/KAE-Memory/issues/84).

### MCP response shaping

`KAE_MCP_PROFILE`, `KAE_MCP_DETAIL`, `KAE_MCP_PROSE`, `KAE_MCP_MAX_TOKENS`,
`KAE_MCP_MAX_ENTITIES` — see [response policy](response-policy.md).

### Operational

| Variable | Notes |
|---|---|
| `KAE_LOG_LEVEL` | |
| `KAE_ENVIRONMENT` | Names the deployment |

### Testing

`KAE_TEST_DATABASE_URL`, `KAE_TEST_DATABASE_PROVIDER`,
`KAE_TEST_POSTGRESQL_URL`. Provider-specific test variables exist for the
deferred provider and are not part of the normal loop.

The test database name must contain `test`. That is a safety guard, not a
convention: it is what stops a destructive migration test from running against a
real database, and it exists because that once happened.

---

## Governed settings

Three, with contracts in `settings/catalog.py` and values in `defaults.toml`.

| Setting | Environment | Unit | Range |
|---|---|---|---|
| `response.default_page_size` | `KAE_DEFAULT_PAGE_SIZE` | count | 1–100 |
| `response.max_page_size` | `KAE_MAX_PAGE_SIZE` | count | — |
| `clarification.limit` | `KAE_CLARIFICATION_LIMIT` | count | — |

Each carries a rationale and an implication, not just a number. For
`default_page_size`:

> Large enough to answer most questions in one call, small enough that a project
> with hundreds of statements does not arrive as a single unreadable response.
> **A larger page costs tokens on every read that does not name a limit.**

### Why so few

The catalog is deliberately small, and it records what is excluded and why:

- **Protocol and mathematical constants** stay near the code. Chunking
  `MAX_TOKENS` is a property of the tokeniser, not a knob.
- **Absolute security ceilings** stay in code. A deployment able to raise
  `MAX_BODY_BYTES` has removed a protection rather than tuned it.
- **Secrets and provider selection** stay in the environment and never appear in
  a committed defaults file.

A setting that can be overridden without a contract is a string somebody typed.

---

## Related

- [Security boundaries](../architecture/security-boundaries.md)
- [Deployment](../operations/deployment.md)
- [Errors](errors.md)
