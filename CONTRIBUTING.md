# Contributing

KAE-Memory uses specification-led, task-bounded development.

## Before changing code

1. Identify the approved requirement and architecture decision that justify the change.
2. Work from one issued task context in `development/tasks/`.
3. Confirm the task's allowed file scope and prohibited changes.
4. Record unresolved decisions rather than silently choosing them.

## Local setup

```bash
uv sync --extra dev
make check          # starts the test database if it is not already running
```

**Tests run against an engine the product deploys on, never SQLite** (ADR-0011).
PostgreSQL with pgvector and CockroachDB are both supported (ADR-0022), and
`KAE_TEST_DATABASE_PROVIDER` selects which one a run exercises. PostgreSQL is
the default.

```bash
# PostgreSQL, the default
KAE_TEST_DATABASE_URL=postgresql+psycopg://kae:kae@localhost:5432/kae_memory_test pytest

# CockroachDB
KAE_TEST_DATABASE_PROVIDER=cockroachdb \
KAE_TEST_DATABASE_URL='cockroachdb+psycopg://root@localhost:26258/kae_memory_test?sslmode=disable' pytest

# no live database at all — provider-independent tests only
pytest -m "not database"
```

Test configuration is separate from the application's and never falls back to
it. `KAE_DATABASE_URL` is not read here: a suite that could reach the
application's database is one mistaken environment away from truncating it,
which has happened in this repository once already.

Without a test URL, live-database tests **skip with a reason** and the rest of
the suite still runs. A skip that names what is missing is honest; the failure
mode worth avoiding is a green run that tested nothing, which is why nothing is
skipped silently and why the reason is always printed.

Destructive tests refuse any target whose database name does not designate it as
disposable — `_test`, `test_`, or `testing`. Being on `localhost` is not enough:
a developer keeps real work there too.

### When to run CockroachDB

CockroachDB is in **maintenance verification**: supported and kept working, not
under active development. It is infrastructure now, not the product.

| Run | When |
|---|---|
| Offline schema parity and SQL compilation | every suite run — they need no database |
| Full CockroachDB suite | before a release, and after a change to persistence, migrations, or vector SQL |

Nothing contacts CockroachDB unless `KAE_TEST_DATABASE_PROVIDER=cockroachdb` is
set, so the everyday loop is the PostgreSQL suite and costs about three minutes.
The CockroachDB suite takes over seven hours, which is why it is reserved rather
than scheduled — and why the offline parity checks matter: they catch the class
of divergence that actually occurs, in milliseconds, on every run.

Do not optimise the CockroachDB suite, restructure the provider test tiers, or
pursue provider-specific improvements unless a provider-sensitive change
requires it.

`uv.lock` is committed. Use `uv sync` rather than `uv pip install` so the locked
versions are honoured, and commit the lockfile whenever dependencies change.

## Database and migrations

Configuration comes from the environment. Copy `.env.example` to `.env` and set
`KAE_DATABASE_URL`. `.env` is gitignored and must never be committed — no
credential belongs in the repository, an image, a log, a document, or an agent
transcript.

```bash
export KAE_DATABASE_URL='postgresql+psycopg://user:password@host:26257/kae?sslmode=verify-full'

make migrate         # alembic upgrade head
make migrate-down    # alembic downgrade base
uv run alembic current
uv run alembic revision -m "describe the change"
```

Migrations are additive. Revision `0001` is applied; editing it rather than
adding a new revision requires an explicit decision, not an implementer's
judgement.

The selected provider is the authoritative store, and a deployment selects it
(ADR-0022). SQLite is not used anywhere: it produced two false passes before
being retired, and it cannot express a vector column at all.

Migrations share one history. Provider-specific branches are confined to the
vector column and its index; everything else is identical on both engines. A
branch must be explicit, tested on both, and safe for the provider it does not
target.

Database MCP tooling is for inspection and management only. All domain writes go
through KAE application contracts — see ADR-0004.

## Pull request expectations

A pull request should include:

- requirement, ADR, and task identifiers;
- a concise description of behavioural change;
- tests for success, failure, and relevant boundaries;
- documentation updates when contracts or workflows change;
- a deviation report when implementation exposes a specification gap.

## Quality gate

All changes must pass Ruff linting and formatting checks, strict mypy checking,
and pytest. Passing automation does not replace review against the approved task
context and specifications.
