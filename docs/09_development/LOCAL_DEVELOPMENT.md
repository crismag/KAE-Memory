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

**There is no UI, and that is the product.** KAE-Memory is headless (ADR-0026);
user interaction belongs to KAE-Studio. The complete local workflow is the API
on loopback, the worker behind it, and either `/docs` or an MCP client to drive
them — no browser required and none provided.

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
make openapi         # rewrite the recorded OpenAPI document (a test compares it)
make dev-db-down     # stop the development database, keep the data
make dev-db-reset    # destroy the development data — not undoable
make api             # the API alone
make worker          # the worker alone
```

`make check` uses a **different** database on port 26258, in memory and truncated
between tests, so running the suite never touches your development data.

## Running tests by changed area

The suite is fast enough to run whole (38s, 77s with coverage), but the loop
that matters during implementation is smaller. Run the narrowest set that could
detect what you just changed, expand once it passes, and run the whole gate once
when the target is complete.

| Changed | Run |
| --- | --- |
| A domain rule | `pytest tests/domain -q --no-cov` (~1s) |
| An application service | `pytest tests/domain tests/application -q --no-cov` (~6s) |
| An MCP tool | `pytest tests/mcp_adapter -q --no-cov` (~15s) |
| An HTTP route or schema | `pytest tests/api -q --no-cov` (~10s) |
| Either adapter's surface | add `tests/api/test_adapter_parity.py` — the registry fails on an unregistered tool or route |
| Persistence or a mapping | `pytest tests/persistence -q --no-cov` |
| A migration | `pytest -m migration -q --no-cov` |
| Anything, before committing | `pytest -q` — the full gate, with coverage |

Add `-p no:randomly` while iterating on one file; leave it off otherwise, since
order randomisation is what catches tests that depend on each other.

**Expensive suites run on demand, not in the loop.** CockroachDB parity takes
around seven and a half hours and is a release decision; see
[`DEFERRED_VERIFICATION.md`](DEFERRED_VERIFICATION.md).

### Why tests are fast now, and the one marker that opts out

Each test runs inside a transaction that is rolled back afterwards. Sessions the
application opens join it and their commits become savepoints, so commit
semantics are exactly what the application sees — the write lands, later reads
find it — while the work is discarded at the end without rewriting twenty tables.

A test whose subject is a write being visible **across connections** — a unique
index firing under concurrency, a worker reading in its own session — marks
itself:

```python
@pytest.mark.real_commits
def test_concurrent_retries_create_exactly_one_record(...):
```

That test truncates before and after instead. Reach for the marker when a test
fails with data it just wrote appearing absent, and not otherwise: it costs
roughly 270ms, which is what every test used to cost.

## When it does not start

| Message | Cause |
| --- | --- |
| `port 8000 is already in use` | Something else holds it — often a previous run. `pkill -f kae_memory` |
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
