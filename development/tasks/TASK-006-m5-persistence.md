# TASK-006 — M5 Persistent Memory Proof

**Status:** complete, 2026-07-27
**Milestone:** M5 · **Prompt:** MEM-01

## Objective

Implement revision `0002` and the application contracts needed to prove that
durable engineering memory survives the death of the process that wrote it.

## Business purpose

This is the central product claim and the main judging criterion. Everything
after it — agent collaboration, recovery, retrieval, the workspace — assumes this
works. Nothing above it is worth building until it does.

## Success condition

> A project is created, a user interaction is recorded, one AgentRun writes
> confirmed knowledge, that process ends, and a later AgentRun retrieves the
> knowledge from CockroachDB.

Stated as a test: **Agent A writes something and Agent B retrieves it in another
run**, with no shared process state.

## Related approved context

- `docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md` — FR-001 to FR-004, FR-007,
  FR-010
- `specifications/ADR/ADR-0005-m5-physical-schema.md` — the schema, authoritative
- `specifications/AGENT_EXECUTION_MODEL.md` — AgentRun fields and status model
- `specifications/ADR/ADR-0004-mcp-inspection-only.md` — write boundary
- `docs/05_product/UNIFIED_DEMO_NARRATIVE.md` — beats 1 to 4

## Expected outputs

- Alembic revision `0002` creating `projects`, `sessions`, `agent_runs`,
  `messages`, `knowledge_relationships`, and `knowledge_provenance_links`, with
  the indexes listed in ADR-0005, and a working `downgrade`.
- SQLAlchemy mappings in `src/kae_memory/persistence/`.
- Domain contracts for `Project`, `Session`, `Message`, and `AgentRun`, following
  the existing frozen-dataclass style with invariants in `__post_init__`.
- Repositories for each, following the existing `KnowledgeRepository` protocol
  shape.
- Application contracts for: create project, open session, record message, start
  run, complete run, write knowledge, retrieve confirmed knowledge.
- Reconciliation of the `RelationshipType` vocabulary — see constraints.
- Tests, including the cross-run retrieval proof.

## Constraints

- **Revision `0001` is not modified.** `0002` is additive. Changing `0001`
  requires an explicit decision, not an implementer's judgement.
- Reuse the existing domain contracts and `KnowledgeRepository` protocol. Do not
  introduce a second knowledge model.
- Every new primary key is an application-generated `UUID`. No autoincrement
  integer keys.
- All timestamps `TIMESTAMPTZ` and timezone-aware in Python. Rehydration
  normalises through the existing `_as_aware` helper or an equivalent.
- No cascading deletion of knowledge or run history.
- No database enums. Vocabularies are validated in the domain layer.
- **No vector columns, embeddings, or semantic indexes.** That is M8.
- Knowledge writes and the accompanying AgentRun status change commit in one
  transaction, through `run_transaction`.
- No credential in code or configuration; the URL comes from `KAE_DATABASE_URL`.

## Known decision the implementer must surface, not silently resolve

ADR-0005 permits relationship types `depends_on`, `refines`, `conflicts_with`,
`supports`, `derived_from`, `implements`, `reviews`. The domain's existing
`RelationshipType` enum defines `supports`, `contradicts`, `derives_from`,
`implements`, `validates`, `supersedes`, `blocks`.

These overlap but disagree. Pick one vocabulary, apply it in both places, and say
which in the pull request. Do not let both survive.

## Allowed file scope

- `src/kae_memory/domain/`
- `src/kae_memory/persistence/`
- `migrations/versions/`
- `tests/`
- this task file for completion notes

## Prohibited changes

- revision `0001`
- user interface or frontend of any kind
- real model-provider calls
- cloud infrastructure or deployment configuration
- embeddings, vector columns, or semantic retrieval
- agent roles beyond recording which role a run had

## Acceptance criteria

1. `alembic upgrade head` and `alembic downgrade base` both succeed.
2. A project, session, message, and AgentRun can be created and retrieved.
3. Knowledge written by one run is retrieved by a different run in a separate
   session, with provenance, version, and lifecycle intact.
4. The retrieval path uses no in-process state carried over from the writing run.
5. Each ADR-0005 approval query is answerable relationally, without parsing JSONB.
6. Knowledge writes and run status changes are transactionally atomic.
7. `make check` passes.

## Required tests

- Cross-run, cross-session retrieval — the success condition above.
- AgentRun status transitions, including a terminal state.
- Message ordering and the `(session_id, sequence_number)` uniqueness constraint.
- Provenance links resolving knowledge to both its producing run and its
  originating message.
- Migration upgrade and downgrade.

## Stop conditions

Stop and report rather than guessing if: the relationship vocabulary cannot be
reconciled without changing published behaviour; the schema cannot answer an
approval query; or `0001` appears to need modification.

## Definition of completion

`make check` is green, the cross-run proof passes, and the pull request states
which relationship vocabulary was adopted and why.

## Completion notes

Delivered as specified, with one decision surfaced rather than resolved silently.

**Relationship vocabulary — decision.** The existing domain `RelationshipType`
enum was adopted as the single authoritative vocabulary: `supports`,
`contradicts`, `derives_from`, `implements`, `validates`, `supersedes`, `blocks`.
ADR-0005's alternative list (`depends_on`, `refines`, `conflicts_with`,
`derived_from`, `reviews`) was not adopted.

Reasoning: the enum is already implemented, exported, tested, and cited by the
domain and retrieval specifications, while ADR-0005's list was illustrative and
written alongside the physical schema. Changing published domain behaviour to
match an illustration would be the more disruptive choice. Because
`knowledge_relationships.relationship_type` is a plain string, adding values
later needs no migration — so nothing is foreclosed.

**Beyond the strict scope, and why:**

- `migrations/script.py.mako` — `alembic revision` could not run without it.
  RA-01 added the environment but never exercised revision generation.
- `file_template` in `alembic.ini`, so revisions are named consistently.
- `src/kae_memory/persistence/timestamps.py` — the `_as_aware` helper from RA-01
  moved out of the knowledge repository so the new repositories share it.
- `SqlAlchemyKnowledgeRepository.save` and `list_for_project` — confirmation and
  project-scoped retrieval need them.

**Deviations:** none. Revision `0001` is unchanged, no vector columns were added,
and no agent behaviour was implemented — roles are recorded, not executed.

**Evidence:** `make check` green — 62 tests, 95% coverage. `alembic upgrade head`
and `alembic downgrade base` verified, including that `0001` still stands alone.
