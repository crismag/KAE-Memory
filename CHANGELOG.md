# Changelog

## Unreleased

### Added

- Durable `project-model.yaml` and repository context index.
- Project and problem definitions.
- Approved MVP requirements baseline and explicit MVP scope boundary.
- Product experience north star, MVP UI workspace, and demo story.
- Engineering specifications and ADR-0001 to ADR-0003.
- Three-system architecture context and architecture workplan.
- Domain contracts: identifiers, provenance, knowledge items and versions,
  lifecycle states and transitions, typed domain errors.
- Knowledge persistence: SQLAlchemy mappings, repository, CockroachDB
  serialization-failure retry, and the first Alembic revision.
- Python packaging, `make check` quality gate, and CI workflow.
- Milestone-driven development plan and Codex/Claude execution roadmap.
- `docs/00_project/CURRENT_PROJECT_STATE.md` as the authoritative project
  dashboard and first-loaded context.
- Apache-2.0 `LICENSE`.
- Canonical demo narrative, agent execution model with AgentRun and recovery
  contracts, MCP inspection-only policy (ADR-0004), AWS demonstration baseline,
  and public release checklist.

### Not added

Application services, HTTP interfaces, user interface, retrieval and embeddings,
agent execution, and cloud deployment are approved but not yet built. Persistence
covers knowledge items and versions only; project, session, message,
relationship, and AgentRun tables are not yet implemented.

Authentication, teams, billing, administration, agent roles beyond the three
authorised, general coding-agent hosting, production-scale retrieval, and
production-grade deployment remain out of scope.

### Fixed

- Timezone normalisation when rehydrating knowledge, which broke the persistence
  round trip.
- Executable Alembic environment: `alembic.ini` and `migrations/env.py`, with the
  database URL read from `KAE_DATABASE_URL`.
- Committed `uv.lock` for reproducible builds.
- Ruff and formatting findings cleared; `make check` passes all four gates.

### Added in RA-01

- Tests for `run_transaction` retry, backoff, exhaustion, and SQLSTATE 40001
  detection.
- `.env.example`, `make migrate`, and `make migrate-down`.
