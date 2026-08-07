# Implementation source map

What establishes each thing the documentation will claim. Every row names
current code, a test, or an accepted decision — **archived material appears only
as historical input and never as authority.**

## Evidence levels

| Level | Meaning | Publishable in 2B? |
|---|---|---|
| **E1** | Executably verified during Phase 2A | yes |
| **E2** | Established by current passing tests | yes |
| **E3** | Declared by current code contracts, schemas, or accepted ADRs | yes, accurately scoped |
| **E4** | Inferred from implementation structure | only with qualification, or after 2C |
| **E5** | Conflicting, stale, or missing authority | **no** |

Verified during Phase 2A, by running against the current tree: 43 capability
declarations (25 both / 12 HTTP-only / 5 MCP-only / 1 internal), 30 declared MCP
tools, 44 HTTP paths and 51 operations in the recorded contract, 4 lifecycle
states, 8 knowledge kinds, 3 detail levels, 4 prose levels, 4 response profiles,
21 migrations, 19 application services, 1,675 collected tests.

---

## 1. Product definition

| Claim | Authority | Evidence | Documentation |
|---|---|---|---|
| Headless — serves no UI | ADR-0026; no `package.json`; `make dev` starts db/migrations/API/worker | **E1** | index, system-context |
| Two adapters, peers | ADR-0023; `capabilities.py`; `tests/api/test_adapter_parity.py` | **E2** | capability-matrix |
| Studio owns product interaction | ADR-0026 | **E3** | system-context |
| Clients do not touch persistence directly | ADR-0027 | **E3** | access-and-mutation-policy |
| Confirmation is a person's act | `domain/lifecycle.py`; review routes require `reviewer` | **E2** | knowledge-lifecycle |

---

## 2. Capabilities

Status vocabulary: **supported** (declared + tested), **partial** (reachable on
one adapter by decision), **internal** (not advertised), **unverified**.

| Capability | Status | Interface | Authority | Tests | Evidence | Page | Caveat |
|---|---|---|---|---|---|---|---|
| Project create / list / get | supported | MCP + HTTP | `application/memory_service.py`; `kae_create_project`, `kae_list_projects` | contract + parity | **E2** | first-project | — |
| Project briefing | supported | MCP | `kae_get_project_briefing` | `tests/mcp_adapter/` | **E2** | mcp-tools | agent-only by decision |
| Sessions and messages | supported | HTTP | `api/routers/workspace.py` | `tests/api/test_conversation_extraction.py` | **E2** | workflows | a person's message queues extraction; an agent's does not |
| Submit observation | supported | MCP | `kae_submit_observation`; `ingestion_service.py` | `tests/mcp_adapter/` | **E2** | submit-observations | proposes, never confirms |
| Ingest document | supported | MCP | `kae_ingest_document` | `tests/mcp_adapter/test_ingest_document.py` | **E2** | submit-observations | — |
| Extraction | supported | worker | `worker/execution.py`; `agents/bedrock.py` | fixture-backed | **E2** | knowledge-lifecycle | **asynchronous**; falls back to a deterministic fixture without a model |
| Classification | supported | MCP + HTTP | `classification_service.py`; `kae_get_classifications` | contract | **E2** | concepts | — |
| Knowledge lifecycle | supported | MCP + HTTP | `domain/lifecycle.py` — `_ALLOWED_TRANSITIONS` | domain tests | **E1** | knowledge-lifecycle | `proposed→{validated,rejected}`, `validated→superseded`; rejected and superseded terminal |
| Confirm / reject / correct | supported | MCP + HTTP | `kae_confirm_knowledge`, `kae_reject_knowledge`, `kae_correct_knowledge` | contract + parity | **E2** | review-knowledge | reject requires `expected_version`; 409 on mismatch |
| Provenance and trace | supported | HTTP | `GET /v1/knowledge/{id}/trace` | contract | **E2** | provenance-and-evidence | — |
| Clarifications | supported | MCP + HTTP | `clarification_service.py` | contract | **E2** | answer-clarifications | listing **materialises** questions — POST, not GET (ADR-0023) |
| Assumptions | supported | MCP | `assumption_service.py`; `kae_record_assumption`, `kae_accept_assumption` | contract | **E2** | clarifications-and-unknowns | — |
| Semantic retrieval | supported | MCP + HTTP | `retrieval_service.py`; `chunk_repository.py` | retrieval tests | **E2** | retrieve-and-search | `MAX_DISTANCE = 0.85` — **VG-2 open** |
| Readiness | supported | MCP + HTTP | `readiness_service.py`; `capability_readiness_service.py` | `tests/domain/test_capability_readiness.py` | **E2** | readiness | advisory, never a gate |
| Context assembly | supported | MCP + HTTP | `assembly_service.py`; `kae_assemble_context` | assembly tests | **E2** | assemble-context | bounded; reports unresolved gaps |
| Modules and relationships | **partial** | MCP only | `module_service.py`; `kae_define_module`, `kae_relate_modules`, `kae_get_module_graph` | `tests/mcp_adapter/test_capability_gap.py` | **E2** | modules-and-dependencies | **MCP-only by decision (N12)** — Studio curation is unreconciled |
| Deliverables | supported | MCP + HTTP | `deliverable_service.py`, `render_service.py` | deliverable tests | **E2** | deliverables | — |
| Publication targets | supported | MCP + HTTP | `publication_service.py` | contract | **E2** | deliverables | targets listed; publication itself not wired from Studio |
| Blueprint | supported | HTTP | `blueprint_service.py` | blueprint tests | **E2** | concepts | — |
| Preliminary / setup context | supported | MCP + HTTP | `preliminary_context_service.py`, `setup_service.py` | contract | **E2** | first-project | for sparse projects |
| Re-embedding | **internal** | service | `reembedding_service.py` | — | **E4** | — | not exposed on either adapter — **do not advertise** |
| PostgreSQL + pgvector | supported | provider | `persistence/providers.py`; ADR-0022 | full suite | **E1** | persistence-and-providers | the deployed provider |
| CockroachDB | **unverified at head** | provider | ADR-0022; CI gated on `KAE_COCKROACHDB_CI_ENABLED` | parity at revision `0009` only | **E5** | persistence-and-providers | **VG-4.** Selectable, demonstrated at `0009`; head is `0021` |

---

## 3. Interfaces

| Surface | Count | Authority | Evidence |
|---|---|---|---|
| MCP tools | 30 declared | `capabilities.declared_mcp_tools()` | **E1** |
| — of which mutations | 13 | tool registration | **E1** |
| HTTP paths / operations | 44 / 51 (28 GET, 23 POST) | `specifications/openapi.json`, guarded by `test_recorded_contract.py` | **E1** |
| CLI entry points | 1 — `kae-memory-mcp` | `pyproject.toml [project.scripts]` | **E1** |
| Worker | `kae_memory.worker` — claims runs, leases, retries | ADR-0007 | **E2** |
| Capability declarations | 43 | `capabilities.py` | **E1** |

**Parity means the registry decides.** `tests/api/test_adapter_parity.py` fails
if a capability declared `both` is missing from an adapter, *and* if a tool or
route exists that the registry does not declare. It does not mean every
operation appears on both surfaces — 17 of 43 are deliberately single-adapter.

**Response tiers:** `DetailLevel` = summary / standard / diagnostic;
`ProseLevel` = none / minimal / concise / standard; `ResponseProfile` = economy /
regular / detailed / custom. Source `mcp/response_policy.py`. **E1.**

---

## 4. Lifecycle and invariants

| Invariant | Enforced in | Evidence |
|---|---|---|
| Lifecycle transitions | `domain/lifecycle.py` → `InvalidLifecycleTransitionError` | **E1** |
| Run-status transitions | `domain/execution.py` | **E1** |
| Optimistic concurrency on reject | `expected_version` → 409 | **E1** — exercised this session |
| Append-only versions, supersession without deletion | domain services over repositories | **E3** |
| Mandatory provenance | write paths | **E3** |
| Idempotency | `idempotency_key` on messages, runs, reviews | **E2** |
| Project isolation | project-scoped repositories | **E4** — no cross-project test found |
| Dependency-cycle prevention | `module_service.py` | **E4** — needs confirmation in 2C |
| Direct DB access bypasses the domain | — | **E4** — reasoned, not tested; transitions live in Python, not the schema |

Knowledge kinds (8): `actor`, `goal`, `rule`, `constraint`, `requirement`,
`decision`, `unknown`, `assumption`. **Kind and lifecycle are orthogonal** — an
assumption can be proposed or confirmed, and `unknown` is a kind, not a status.
**E1.**

---

## 5. Operations

| Topic | Authority | Evidence | Caveat |
|---|---|---|---|
| Local development | `Makefile`, `scripts/development/run-local.sh` | **E3** | verify in 2C |
| Server install | `deploy/server/install.sh`, `deploy.sh`, `services/`, `reverse-proxy/` | **E3** | the only public deployment assets |
| Migrations | `migrations/versions/` — 21, head `0021` | **E1** | — |
| Health check | `GET /health` → `status`, `database`, `migration_revision`, `version` | **E1** | observed on the deployed instance |
| Trust boundary | ADR-0024 — refuses to start off-loopback without tokens | **E3** | token configuration has **no procedure** — gap |
| AWS provisioning | none in this repository since `05fb320` | **E1** | private |

---

## Historical input only

May inform Phase 2B writing; **never cited as authority.** All held as archived
development context, referenced by name without location:
`docs/user-guide/*` (5 files — closest to reusable), `LOCAL_DEVELOPMENT.md`,
`MCP_ACCESS_POLICY.md` (superseded by ADR-0027), `ADAPTER_CAPABILITY_MATRIX.md`
(superseded by `capabilities.py`), `MCP_RESPONSE_POLICY.md` (superseded by
`response_policy.py`), `AWS_DEMONSTRATION_BASELINE.md`.
