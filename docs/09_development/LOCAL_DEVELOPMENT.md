# Running KAE-Memory locally

One command starts everything. Nothing is deployed, nothing needs AWS, and no
credentials are required.

```bash
make install     # once
make dev
```

Then open **<http://localhost:5173>**.

`Ctrl-C` stops the three processes and **leaves the database running**, on
purpose: it holds your projects, and wiping them on every restart would make
"persistent memory" a claim rather than something you can watch.

## What starts

| Process | Address | Notes |
| --- | --- | --- |
| PostgreSQL + pgvector | `localhost:5432` | The default provider. `kae_memory` for development, `kae_memory_test` for the suite — never the same database |
| CockroachDB | `localhost:26259`, console on `8081` | Also supported (ADR-0022). Docker, **persistent volume** — separate from the disposable test database on 26258 |
| API | `127.0.0.1:8000` | Loopback only. It has no authentication (ADR-0014) |
| Worker | — | Claims and executes queued runs |
| Workspace | `localhost:5173` | Vite, proxying `/v1` and `/health` to the API |

The workspace proxies the API, so the browser sees **one origin** — the same shape
ADR-0017 recommends for a real deployment, which is why there is no CORS to
configure here.

## Walking the product

1. **Create a project.** It is the durable boundary; nothing is read across
   projects.
2. **Discovery tab** — write an incomplete idea and submit. That records your
   words verbatim as evidence and enqueues a Requirements run. The response is a
   `202` with a run identifier: the browser never owns the run, so closing the tab
   cannot lose it.
3. **Runs tab** — watch it go `pending → running → succeeded`, streamed over
   Server-Sent Events.
4. **Knowledge tab** — the candidates it extracted. Confirm the ones that are
   right; confirmation is a human act and no agent does it. Assign each to a
   discovery area. An area only accepts kinds it declares, so a mismatch is
   rejected rather than silently ignored.
5. **Readiness tab** — the percentage, with every area's contribution beside it.
   Confirming moves it; generating more unconfirmed candidates does not.
6. **Review tab** — run the Review agent, then read what is unresolved.
7. **Blueprint tab** — every statement is a confirmed knowledge item's own text,
   labelled `grounded`, `derived`, or `assumption`. **Trace** any statement back
   through project, session, source message, producing run, and version.

### What you will see, honestly

Offline, extraction uses a **rule-based sentence fixture**, not a model. It
quotes your text verbatim so provenance is real, but it does not understand
anything: it classifies by surface cues. Run summaries say
`"model": "deterministic-fixture"` when this is what produced a result.

Offline classification also only handles two of eight knowledge kinds — the two
that exactly one area accepts — so a review run will often report
`areas_assigned: 0` and you will assign most areas by hand. That is the review
path declining to invent judgement, not a defect (ADR-0015).

**Live extraction needs AWS.** See
[`../../operations/runbooks/enablement-sequence.md`](../../operations/runbooks/enablement-sequence.md).

## Other commands

```bash
make check           # ruff, ruff format, mypy strict, pytest against the selected provider
make openapi         # regenerate the OpenAPI document and the typed client
make dev-db-down     # stop the development database, keep the data
make dev-db-reset    # destroy the development data — not undoable
make api             # the API alone
make worker          # the worker alone
make frontend        # the workspace alone
```

`make check` uses a **different** database on port 26258, in memory and truncated
between tests, so running the suite never touches your development data.

## When it does not start

| Message | Cause |
| --- | --- |
| `port 8000 is already in use` | Something else holds it — often a previous run whose Vite child survived. `pkill -f kae_memory` and `pkill -f vite` |
| `the api exited during startup` | Read the log above it; usually the database is unreachable |
| `"database": "down"` from `/health` | The container is not running: `docker ps | grep kae-crdb-dev` |
| `migration_revision` is `null` | Migrations have not run; `make dev` runs them, or `uv run alembic upgrade head` |
| Runs stay `pending` | The worker is not claiming. A connection failure looks exactly like an idle queue — read the worker log rather than the queue |

## Regenerating the client

The TypeScript client is generated from the API's OpenAPI document and checked
in. After changing an endpoint or a schema:

```bash
make openapi
```

CI regenerates and diffs both files, so skipping this fails the build rather than
surfacing in a browser as a runtime error.
