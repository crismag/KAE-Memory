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

**Tests run against CockroachDB, not SQLite** (ADR-0011). `make test` starts a
single-node CockroachDB in Docker on port 26258; `make test-db-down` stops it.
Docker is therefore a prerequisite. To use a cluster you already have, set
`KAE_TEST_DATABASE_URL` instead.

The suite fails loudly when no database is reachable. It never skips silently — a
green run that tested nothing is worse than a red one.

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

CockroachDB is the authoritative store. SQLite is used in tests and is acceptable
for checking that a migration runs, but it is not a substitute for verifying
behaviour against CockroachDB.

CockroachDB MCP is for inspection and management only. All domain writes go
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
