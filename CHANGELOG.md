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

Agent behaviour, semantic retrieval, HTTP interfaces, the user interface, and
cloud deployment are approved but not yet built. Agent roles are recorded on
every run; nothing executes them yet. The `knowledge_relationships` table exists
but is not yet wired to the domain.

Authentication, teams, billing, administration, agent roles beyond the three
authorised, general coding-agent hosting, production-scale retrieval, and
production-grade deployment remain out of scope.

### Added in M5

- Revision `0002`: `projects`, `sessions`, `agent_runs`, `messages`,
  `knowledge_relationships`, and `knowledge_provenance_links`. Additive; revision
  `0001` is unchanged.
- Domain contracts for sessions, messages, and agent runs, including the run
  status model with interruption, resumption, bounded retry, and terminal states.
- `MemoryService`, the application boundary every domain write passes through.
- Provenance links answering which run produced knowledge, which run used it, and
  which message it came from.
- The cross-run persistence proof: one agent writes, its process ends, another
  retrieves in a separate run and session.

### Added in M6

- `KnowledgeKind` domain enum — one authoritative vocabulary for what a knowledge
  item is, validated on construction.
- `ExtractionPort` with a deterministic fixture adapter and a Bedrock adapter,
  so no test contacts a provider and the demonstration has a documented fallback.
- Versioned per-role prompts, recorded on every run alongside the schema version.
- Source-quote verification: an item citing a quote absent from the source fails
  the run rather than producing knowledge that misstates its provenance.
- Requirements and Architecture agents. The Architecture Agent consumes confirmed
  knowledge only.
- Replaying a completed run returns its original output rather than extracting
  again.

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
