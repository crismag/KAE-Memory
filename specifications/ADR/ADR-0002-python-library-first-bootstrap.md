# ADR-0002 — Python Library-First Bootstrap

- **Status:** accepted
- **Date:** 2026-07-26
- **Accepted:** 2026-07-27

## Context

KAE-Memory needs an executable repository foundation before domain and persistence
implementation. The project must support rapid AI-assisted development, strong
testing, type checking, CockroachDB integration, and future service or CLI
interfaces without committing prematurely to a deployable service topology.

## Decision

Bootstrap the repository as a Python 3.12 `src`-layout package.

Use:

- `uv` for environment and dependency management;
- Hatchling as the minimal build backend;
- pytest and pytest-cov for tests;
- Ruff for linting and formatting checks;
- mypy in strict mode for static type checking;
- GitHub Actions for pull-request and `main` quality checks.

Do not add FastAPI, SQLAlchemy, Alembic, an agent framework, or a concrete
CockroachDB driver until the task that owns the corresponding contract is
approved.

## Rationale

Python has broad AI, database, testing, and integration support and is suitable
for a library-first domain core. A library-first layout keeps domain contracts
independent from transport, orchestration, and deployment choices.

## Consequences

- The initial executable code contains no product behaviour.
- Domain logic can be tested without a running database or service.
- Future transport and persistence adapters remain replaceable.
- Python runtime performance may require later measurement for specific
  workloads; no performance claim is made by this decision.

## Alternatives considered

- TypeScript service-first scaffold: strong application tooling, but would
  prematurely favour a network-service boundary.
- Go service-first scaffold: operationally simple, but less aligned with the
  expected AI integration ecosystem and rapid domain experimentation.
- Polyglot monorepo: deferred because it adds coordination cost before a proven
  need exists.
