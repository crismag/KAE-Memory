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

Every entry below this line is dated by its milestone, so this paragraph is
about **current** state rather than what was true when the first entries were
written. HTTP and MCP adapters, semantic retrieval, agent execution and a
deployed service all now exist; the sections from M5 onward record when.

Still absent: the user interface, which is Studio's. The
`knowledge_relationships` table exists and is not wired to the domain.

Authentication, teams, billing, administration, agent roles beyond the three
authorised, general coding-agent hosting, production-scale retrieval, and
production-grade deployment remain out of scope.

### Added, 2026-08-09 — Phase 2

Four slices against the ecosystem's `ADR-0001`. **Shipped and not deployed.**

- Review runs when extraction drains, in batches, and reports degradation
  instead of silently returning the fixture. Readiness recalculates afterwards.
- Knowledge can be confirmed as a set, all-or-nothing, in one revision bump.
- The knowledge listing returns each item's area links, so a problem statement
  can be shown at all.
- Extraction that abandoned chunks says so beside the coverage it undermines.
- A turn's ranked next action, reasoning and provenance are durable on the
  message that produced it — `Message.metadata`, exposed rather than added.
- Assumptions carry an `origin`; `user_stated` is refused from a route that
  cannot know it.
- Question candidates can be listed without asking them —
  `GET /v1/projects/{id}/clarifications/candidates`, which writes nothing.
- A project can be deleted, with everything scoped to it (T0.2, F-021).

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

### Added in M7

- Revision `0003`: lease ownership columns on `agent_runs` plus a claimable
  index, added additively over `0002`.
- `Lease` domain value object with a monotonically increasing fencing token, so
  a worker that recovers after its lease was reassigned cannot overwrite the
  newer owner's work.
- The durable worker: compare-and-swap claims, concurrent heartbeat renewal,
  a checkpoint after every step, bounded retry with backoff, `abandoned` on
  exhaustion, and graceful release on shutdown.
- `MemoryService.enqueue_run`, the counterpart to `start_run`, so work can be
  submitted without the submitter owning its execution.
- The kill-and-recovery proof: a worker dies mid-run and a replacement finishes
  it from durable state alone.

### Fixed

- Timezone normalisation when rehydrating knowledge, which broke the persistence
  round trip.
- Executable Alembic environment: `alembic.ini` and `migrations/env.py`, with the
  database URL read from `KAE_DATABASE_URL`.
- Committed `uv.lock` for reproducible builds.
- Ruff and formatting findings cleared; `make check` passes all four gates.
- Revision `0003` no longer uses a non-constant `ADD COLUMN` default, which
  SQLite rejects; the `NOT NULL` column is added nullable, backfilled, then
  tightened.

### Added in RA-01

- Tests for `run_transaction` retry, backoff, exhaustion, and SQLSTATE 40001
  detection.
- `.env.example`, `make migrate`, and `make migrate-down`.

### Added for artifact generation

The work that had to exist before another system could turn this knowledge into
files. Named by their control-register identifiers.

- **EM-1** — a projection names its project and its revision, so anything
  generated from it can say which knowledge produced it. A projection that could
  not be pinned was a projection nothing downstream could cite.
- **EM-2** — a message can be recorded without being interpreted. Ingestion and
  extraction were one operation, which meant no caller could store a transcript
  without paying for a model run over it.
- **EM-5** — the review pass can be asked for explicitly, rather than only
  happening as a side effect of extraction.
- **EM-6b** — review can be done by a model. `KAE_REVIEW=bedrock` selects it,
  and `KAE_REVIEW_MODEL` falls back to `KAE_EXTRACTION_MODEL` so a deployment
  authorised for one model is not silently asked to invoke another.
- **T0.2** — a project can be deleted with everything scoped to it. Every foreign
  key to `projects` is `NO ACTION` rather than `CASCADE` (F-021), so deletion has
  to walk the graph in dependency order; the order is derived from table metadata
  rather than hand-maintained, and the service refuses an empty request.
- **T0.5** — what four real projects found, registered as F-018 to F-022 rather
  than fixed quietly.
- **T0.6** — a test that fails when a capability exists and no adapter can reach
  it. Ten such capabilities were found. Reachability is transitive and the
  worker and agents count as callers; exemptions require a stated reason.

### Fixed for artifact generation

- The live reviewer returned nothing because the instruction was in the system
  prompt while the message carried only data. Repeating the instruction in the
  message fixed it — the classification is now correct on every statement it was
  given.
- Sign-in rate limiting was removed rather than loosened, and the reason is
  recorded so it is not reintroduced as a fix.
- Loopback was being read as a reason to skip authentication.
- Listing questions opened a session per question.
