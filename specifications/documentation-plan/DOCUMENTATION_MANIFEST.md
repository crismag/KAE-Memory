# Documentation manifest

Every proposed page. **34 pages** — 20 in Phase 2B, 6 in 2C, 8 in 2D.

Markdown rather than YAML: nothing parses this, and the repository's planning
records are prose. A machine-readable manifest would need a consumer to justify
the format.

Audiences: **A1** MCP user · **A2** integrator · **A3** evaluator ·
**A4** developer · **A5** operator · **A6** ecosystem maintainer.
Evidence levels are defined in [SOURCE_MAP.md](SOURCE_MAP.md).

Validation: **gen** generated from code · **exec** executed in 2C ·
**link** link-checked · **rev** manual review.

---

## Phase 2B — MCP-first core

In dependency order. Vocabulary first, then reference, then workflows, then the
quickstart that compresses them.

| # | Path | Title | Aud. | Answers | Sources | Ev. | Valid. | Depends on |
|---|---|---|---|---|---|---|---|---|
| 1 | `docs/glossary.md` | Glossary | all | What do these words mean here? | `domain/models.py`, `domain/lifecycle.py`, `capabilities.py` | E1 | rev | — |
| 2 | `docs/concepts/knowledge-lifecycle.md` | Knowledge lifecycle | A1 A2 | How does something become known? | `domain/lifecycle.py` `_ALLOWED_TRANSITIONS` | E1 | gen, rev | 1 |
| 3 | `docs/concepts/provenance-and-evidence.md` | Provenance and evidence | A1 A3 | How do I know where this came from? | `/v1/knowledge/{id}/trace`, ADR-0006 | E2 | rev | 2 |
| 4 | `docs/reference/capability-matrix.md` | Capability matrix | A2 | Which adapter exposes what? | `capabilities.py`, `test_adapter_parity.py` | E1 | **gen**, link | 1 |
| 5 | `docs/reference/mcp-tools.md` | MCP tools reference | A1 A2 | What can I call? | 30 declared tools, schemas | E1 | **gen**, exec | 4 |
| 6 | `docs/reference/response-policy.md` | Response policy | A2 | Why did I get this shape back? | `mcp/response_policy.py` | E1 | gen | 4 |
| 7 | `docs/reference/access-and-mutation-policy.md` | Access and mutation policy | A2 A5 | What may a client do directly? | **ADR-0027** (canonical), VG-3 | E3 | rev | — |
| 8 | `docs/reference/http-api.md` | HTTP API | A2 | What are the routes? | `specifications/openapi.json` — 44 paths | E1 | **gen**, link | 4 |
| 9 | `docs/reference/errors.md` | Errors | A2 | What does this failure mean? | `domain/errors.py`, API handlers | E2 | rev | — |
| 10 | `docs/reference/configuration.md` | Configuration | A4 A5 | What can I set? | `config/`, settings modules | E3 | exec | — |
| 11 | `docs/concepts/clarifications-and-unknowns.md` | Clarifications and unknowns | A1 | What is KAE asking me? | `clarification_service.py`, `assumption_service.py` | E2 | rev | 2 |
| 12 | `docs/concepts/readiness.md` | Readiness | A1 A3 | What does the percentage mean? | `readiness_service.py` | E2 | rev | 2 |
| 13 | `docs/concepts/context-assembly.md` | Context assembly | A1 A2 | What do I get for an agent? | `assembly_service.py` | E2 | rev | 2 |
| 14 | `docs/concepts/modules-and-dependencies.md` | Modules and dependencies | A2 | How is a system decomposed? | `module_service.py` | E2 | rev | **B3** |
| 15 | `docs/workflows/submit-observations.md` | Submitting observations | A1 | How do I tell it something? | `kae_submit_observation`, `ingestion_service.py` | E2 | exec | 2, 5 |
| 16 | `docs/workflows/review-knowledge.md` | Reviewing knowledge | A1 | How do I confirm or reject? | confirm/reject/correct tools; `expected_version` | E2 | exec | 2, 5 |
| 17 | `docs/workflows/answer-clarifications.md` | Answering clarifications | A1 | How do I close a gap? | `clarification_service.py` | E2 | exec | 11 |
| 18 | `docs/workflows/retrieve-and-search.md` | Retrieval and search | A1 A2 | How do I find what is known? | `retrieval_service.py`; **VG-2** | E2 | exec | 13 |
| 19 | `docs/workflows/assemble-context.md` | Assembling context | A1 A2 | How do I hand context to an agent? | `kae_assemble_context` | E2 | exec | 13 |
| 20 | `docs/index.md` | Documentation home | all | Where do I start? | this manifest | E3 | link | all |

---

## Phase 2C — Written, then validated by execution

Written in 2B, **published only after execution**. Each compresses workflows
whose steps must be proven first.

| # | Path | Title | Aud. | Answers | Sources | Ev. | Valid. | Depends on |
|---|---|---|---|---|---|---|---|---|
| 21 | `docs/getting-started/quickstart.md` | Quickstart | A1 A3 | Can I see this work in ten minutes? | `Makefile`, `run-local.sh` | E3→E1 | **exec** | 15–19 |
| 22 | `docs/getting-started/connect-mcp-client.md` | Connecting an MCP client | A1 | How do I attach my client? | `config/mcp/`, `kae-memory-mcp` | E3→E1 | **exec** | 5 |
| 23 | `docs/getting-started/first-project.md` | Your first project | A1 | What does a real run look like? | setup and preliminary services | E3→E1 | **exec** | 21, 22 |
| 24 | `docs/development/local-setup.md` | Local setup | A4 | How do I run it? | `Makefile`, `pyproject.toml` | E3→E1 | **exec** | — |
| 25 | `docs/development/testing.md` | Testing | A4 | How do I verify a change? | `tests/`, 1,675 collected; provider fixture | E2 | exec | 24 |
| 26 | `docs/examples/cross-session-continuity.md` | Cross-session continuity | A3 | Is the memory claim real? | **B4** — no end-to-end test yet | **E4** | **exec** | 21–23 |

---

## Phase 2D — Architecture, operations, visual evidence

| # | Path | Title | Aud. | Answers | Sources | Ev. | Valid. | Depends on |
|---|---|---|---|---|---|---|---|---|
| 27 | `docs/architecture/system-context.md` | System context | A3 A6 | Where does this sit? | ADR-0026, ADR-0023 | E3 | rev | 2 |
| 28 | `docs/architecture/components.md` | Components | A4 A6 | What is inside? | 19 application services, worker | E3 | rev | 27 |
| 29 | `docs/architecture/persistence-and-providers.md` | Persistence and providers | A4 A5 | Which database, and how supported? | ADR-0022, `providers.py`; **VG-4 / B2** | E3 | rev | — |
| 30 | `docs/architecture/retrieval-and-assembly.md` | Retrieval and assembly | A2 A4 | How is context built? | `retrieval_service.py`, `assembly_service.py` | E2 | rev | 13, 18 |
| 31 | `docs/architecture/security-boundaries.md` | Security boundaries | A2 A5 | What is trusted? | ADR-0024, ADR-0027; **B1** | E3 | rev | 7 |
| 32 | `docs/operations/deployment.md` | Deployment | A5 | How do I run this for real? | `deploy/server/`; **B1, D1** | E3 | exec | 31 |
| 33 | `docs/operations/health-and-monitoring.md` | Health and monitoring | A5 | Is it working? | `GET /health` | E1 | exec | 32 |
| 34 | `docs/operations/migrations-and-upgrades.md` | Migrations and upgrades | A5 | How do I move versions? | `migrations/` — 21, head `0021` | E1 | exec | 32 |
| 35 | `docs/operations/troubleshooting.md` | Troubleshooting | A5 A1 | Why is it not working? | 2C failures, real incidents | E4 | rev | 21–26 |
| 36 | `docs/development/repository-layout.md` | Repository layout | A4 | Where is anything? | tree | E1 | link | — |
| 37 | `docs/examples/sparse-project-walkthrough.md` | Sparse project walkthrough | A1 A3 | What if I barely know what I want? | preliminary/setup services | E2 | exec | 23 |

*(37 rows; 34 distinct pages — `docs/index.md` and two workflow pages are counted
once and appear in their dependency position.)*

---

## Generated, not written

Four pages should be produced from code and regenerated, not maintained by hand.
Each has a source that a test already enforces, so drift becomes a test failure
rather than a documentation defect.

| Page | Generated from | Enforced by |
|---|---|---|
| capability-matrix | `capabilities.py` | `test_adapter_parity.py` |
| mcp-tools | tool registration + schemas | `tests/mcp_adapter/test_tools.py` |
| http-api | `specifications/openapi.json` | `test_recorded_contract.py` |
| response-policy | `mcp/response_policy.py` | policy tests |

**Not built in Phase 2A.** A generator is worth writing only once the target
format is settled, which is Phase 2B's job.

---

## Diagrams

Mermaid, in-page, renderable on GitHub. Six, no more — each earning its place.

| Diagram | Type | Shows | Source | Phase |
|---|---|---|---|---|
| System context | flowchart | Studio, CIE, agents, KAE-Memory, database | ADR-0026, ADR-0023 | 2D |
| Knowledge lifecycle | stateDiagram | `proposed → validated → superseded`; `proposed → rejected` | `domain/lifecycle.py` | **2B** |
| Acquisition flow | sequence | message → run → extraction → candidates | `worker/execution.py` | 2D |
| Retrieval and assembly | flowchart | query → chunks → bounded package | `assembly_service.py` | 2D |
| Adapter boundary | flowchart | MCP and HTTP over shared services | `capabilities.py` | 2D |
| Deployment topology | flowchart | proxy, API, worker, database | `deploy/server/` | 2D — after **D1** |

The lifecycle diagram is in 2B because page 2 is unreadable without it: four
states and two terminal ones are a picture, not a paragraph.

---

## Captures

All Phase 2D, from a real system, after 2C proves the flows.

MCP client configuration · tool discovery · an observation becoming a candidate ·
a review decision · a clarification answered · assembled context ·
**cross-session recall** — the one that carries the argument.

**No Studio captures block anything.** MCP-first documentation stands alone;
Studio visuals arrive if and when Studio is presentable.

---

## Validation strategy

| Check | Method | CI? |
|---|---|---|
| Relative links | script over `docs/` and `specifications/` | yes — cheap, catches the most common rot |
| Secrets and private paths | grep for account ids, hostnames, `KAE-Ecosystem` | yes |
| MCP tool names | diff against `declared_mcp_tools()` | yes |
| HTTP routes | diff against `openapi.json` | yes |
| Configuration keys | diff against settings modules | later |
| Commands | executed in 2C | manual |
| Mermaid | rendered | manual |
| Everything else | review | manual |

**Recommended for CI now: the first four.** They are greps and diffs against
sources tests already guard, and they fail loudly. A documentation toolchain
beyond that is not justified by 34 pages, and building one in Phase 2A would be
building for a shape that does not exist yet.
