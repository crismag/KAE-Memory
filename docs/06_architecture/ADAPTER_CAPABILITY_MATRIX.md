# Adapter Capability Matrix — Services × MCP × HTTP

Status: **evidence, 2026-08-05.** Target **N1** of
[`NEXT_PHASE_CHECKLIST.md`](../09_development/NEXT_PHASE_CHECKLIST.md).
No implementation is proposed or authorised by this document.

Every row was established by reading the code — `application/`,
`mcp/server.py`, `api/routers/` — at `main` after `fca4b16`. Planning documents
were not used as evidence for any row, because the gap this file exists to
measure was invisible for exactly as long as documents described it.

It supersedes KAE-Studio's `docs/planning/CAPABILITY_MATRIX.md`, which is pinned
to KAE-Memory at `de37cc4` on 2026-08-01 — before Phases C, D, E, T24, and T25.
That document is not wrong so much as substantially understated.

## 1. The finding in one table

Nine application services exist. HTTP wires four.

Counted by how many handlers on each adapter reach the service, so a handler
using two services is counted under both.

| Application service | MCP | HTTP `/v1` |
| --- | --- | --- |
| `MemoryService` | ✔ 7 tools | ✔ 25 routes |
| `ReadinessService` | ✔ 9 tools | ✔ 11 routes |
| `ReviewService` | ✔ 2 tools | ✔ 1 route |
| `BlueprintService` | ✔ 1 tool | ✔ 3 routes |
| `RetrievalService` | ✔ 1 tool | ✗ **none** |
| `IngestionService` | ✔ 1 tool | ✗ **none** |
| `AssemblyService` | ✔ 1 tool | ✗ **none** |
| `ClarificationService` | ✔ 2 tools | ✗ **none** |
| `ClassificationService` | ~ indirect | ✗ **none** |

`ReembeddingService` is operational, reached by
`scripts/development/reembed-knowledge.py`, and is deliberately on neither
adapter.

Every capability built from Phase C onward landed on MCP alone. That was correct
while MCP was the target — ADR-0018 made it the agent access layer — and it
stops being correct the moment an HTTP client is the consumer.

## 2. Surfaces as they exist

**MCP** — 15 tools, 4 resources, 1 prompt.

`kae_list_projects` · `kae_create_project` · `kae_get_project_briefing` ·
`kae_get_module_context` · `kae_search_knowledge` · `kae_get_open_decisions` ·
`kae_get_readiness` · `kae_submit_observation` · `kae_confirm_knowledge` ·
`kae_reject_knowledge` · `kae_correct_knowledge` · `kae_get_clarifications` ·
`kae_answer_clarification` · `kae_ingest_document` · `kae_assemble_context`

**HTTP** — 28 routes under `/v1`, in three routers.

| Router | Routes |
| --- | --- |
| `workspace` | `POST,GET /projects` · `GET /projects/{id}` · `POST,GET /projects/{id}/sessions` · `POST /sessions/{id}/close` · `POST,GET /sessions/{id}/messages` · `GET /projects/{id}/knowledge` · `POST /knowledge/{id}/confirm` · `POST,GET /projects/{id}/runs` · `GET /runs/{id}` · `GET /runs/{id}/events` · `GET /runs/{id}/knowledge` |
| `readiness` | `GET /projects/{id}/readiness` · `POST …/calculate` · `GET …/history` · `POST …/areas` · `GET …/review` · `GET,POST …/blockers` · `POST …/blockers/{id}/resolve` · `POST …/contradictions` · `POST …/contradictions/{id}/resolve` |
| `blueprint` | `GET /projects/{id}/blueprint` · `GET …/blueprint.md` · `GET /knowledge/{id}/trace` |

## 3. Gap register

Classification per the focus file: **S** Studio-required · **A** agent-only ·
**I** internal · **D** deferred.

| # | Capability | MCP | HTTP | Class | Note |
| --- | --- | --- | --- | --- | --- |
| 1 | Knowledge search | `kae_search_knowledge` | **absent** | **S** | Studio's projection and review views need filtered reads |
| 2 | Document ingestion | `kae_ingest_document` | **absent** | **S** | The acquisition step of the product journey |
| 3 | Ingestion processing state | in the ingest response | **absent** | **S** | Queued runs are visible only in the submission response |
| 4 | Clarification list | `kae_get_clarifications` | **absent** | **S** | Materialises questions — a write behind a `get_` name |
| 5 | Clarification answer | `kae_answer_clarification` | **absent** | **S** | |
| 6 | Context assembly | `kae_assemble_context` | **absent** | **S** | Revision-pinned; the package the product sells |
| 7 | Package description | in the assembly response | **absent** | **S** | Deterministic; not a durable deliverable — see 15 |
| 8 | Knowledge reject | `kae_reject_knowledge` | **absent** | **S** | HTTP has `confirm` only, so review is one-sided |
| 9 | Knowledge correct | `kae_correct_knowledge` | **absent** | **S** | |
| 10 | Project briefing | `kae_get_project_briefing` | `…/blueprint` | **S** | **Contract mismatch, not a gap.** The blueprint route predates the briefing and lacks readiness composition, tier filters, and the response policy |
| 11 | Classified observations | via briefing `tiers` only | **absent** | **S** | No independent, filterable, pageable read |
| 12 | Operational state | via briefing `tiers` only | **absent** | **S** | Same |
| 13 | Operational transitions | **absent** | **absent** | **S** | The domain models `ACTIVE`/`RESOLVED`/`REJECTED`; no adapter reaches them |
| 14 | Classifier supersession | **absent** | **absent** | **I** | `supersede_older_versions` exists with **no caller**; the versioning guarantee is currently theoretical |
| 15 | Durable deliverables | **absent** | **absent** | **D** | Needs a persistence decision. `package_id` is a fresh UUID per call and is not identity |
| 16 | Project-scoped messages | **absent** | session-scoped only | **S** | Studio's `listMessages(projectId)` has no route on either adapter |
| 17 | Project-scoped message write | `kae_submit_observation` | session-scoped | **S** | Studio's port is project-scoped; resolve in client or add a route |
| 18 | Interview session projection | **absent** | sessions exist | **S** | A projection, unless new durable semantics are approved |
| 19 | Module context | reports the gap honestly | **absent** | **D** | Blocked on N16 relationship vocabulary |
| 20 | Run submission and progress | **absent** | `POST /projects/{id}/runs`, SSE | **A** | The one capability HTTP has and MCP does not |
| 21 | Blockers and contradictions | read via briefing | full CRUD | **S** | Reverse asymmetry: MCP cannot record either |
| 22 | Readiness area assignment | **absent** | `POST …/readiness/areas` | **I** | Template administration |
| 23 | Knowledge trace | **absent** | `GET /knowledge/{id}/trace` | **S** | Provenance display; MCP surfaces provenance inside other payloads |
| 24 | Re-embedding | **absent** | **absent** | **I** | Script-driven, deliberately |

**Twelve of twenty-four are Studio-required and absent from HTTP.**

## 4. The asymmetry runs both ways

Rows 20–22 matter because they show this is drift rather than a one-directional
backlog. HTTP can start an agent run, stream its progress, record a blocker, and
resolve a contradiction; MCP cannot. MCP can search, ingest, assemble, clarify,
and classify; HTTP cannot.

Neither surface is a superset. Nothing tests the relationship, so each grew
toward whatever its last target needed — which is the argument for N6's
capability registry rather than for a one-time catch-up.

## 5. Contract mismatches, distinct from absences

Three rows are not "missing endpoint" and must not be treated as such:

- **Row 10 — briefing vs blueprint.** Both exist; they are different responses.
  Adding a briefing route is a contract decision, not a port.
- **Row 16/17 — session scope vs project scope.** Memory's conversation model is
  session-ordered. Studio's port is project-scoped. One of the two moves, and
  the choice belongs in the adapter ADR (N2).
- **Row 13/14 — reachable states with no command path.** The classification
  domain models transitions no adapter can perform, and a repository method no
  caller invokes. This is the clearest evidence that T24 shipped a write surface
  ahead of its read and review surface.

## 6. What this does not settle

Whether HTTP is a product interface or a legacy one. That is N2, and every route
decision below it is premature until it is answered.

## 7. Method

Reproducible. Services: `ls application/*_service.py` and their public methods.
MCP tools: `TOOL_DEFINITIONS` in `mcp/server.py`, cross-referenced against
`context.<service>` usage in each handler in `mcp/tools.py`. HTTP routes: the
`@router` decorators in `api/routers/` with their prefixes.

No row asserts a capability that was not read in code. Where a capability is
absent, the row says absent rather than assuming it exists elsewhere.
