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

### Not added

Application services, HTTP or MCP interfaces, user interface, retrieval and
embeddings, agent orchestration, authentication, and cloud deployment remain
deferred until their dependent requirements and architecture decisions are
approved. Persistence covers knowledge items and versions only; project, session,
message, and relationship tables are not yet implemented.

### Known defects

`make check` does not currently pass. See
`docs/00_project/CURRENT_PROJECT_STATE.md` for the current gate results and the
RA-01 remediation task.
