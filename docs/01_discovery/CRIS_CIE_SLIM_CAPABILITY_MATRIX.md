# CRIS-CIE Slim — Capability Matrix and Component Dispositions

Status: **evidence-based comparison**, 2026-08-01. Companion to `CRIS_CIE_SLIM_CURRENT_STATE.md`.

KAE-Memory evidence cites `/mnt/ai/workspaces/KAE-Memory` at `de37cc4`. Slim evidence cites `/home/cris/workspaces/cris-cie-slim` at `724ac65`.

## Capability comparison

| Capability | CRIS-CIE Slim | KAE-Memory | Recommended authority | Reuse decision |
| --- | --- | --- | --- | --- |
| **Interview orchestration** | Real, adaptive, 92% covered but only against mock/fixture providers. 16-question live run shows genuine quality. | **Absent.** No interview loop exists. | **Neither yet** — the loop is Studio/runtime, the state is Memory's | `adapt` — port the loop shape, not the code |
| **Question selection** | `_next_question` + backlog + gap-derived questions; deterministic fallback. Demonstrably non-repetitive in the live run. | **Absent.** Findings identify gaps but nothing selects a question. | Runtime, over Memory-held gaps | `adapt` |
| **Turn governance (grounding)** | `govern_turn` — verbatim source-text grounding, invented-field rejection, duplicate and frustration rejection. Tested. | **Absent.** Extraction writes knowledge without a grounding gate. | **KAE-Memory** — it protects knowledge integrity | `adapt` — **highest-value asset** |
| **Provider invocation** | 7 adapters, uniform `ModelClient`, helpful failure messages. No retry/backoff/rate limiting. | `ExtractionPort` + `EmbeddingPort`, Bedrock and deterministic adapters, worker-side with leases and retry. | **KAE-Memory** (extraction) / Studio (interview provider) | `reference_only` |
| **Evidence retention** | `answers.json`, `session.json`, `ai_decisions.jsonl` — files, no locking, no idempotency. | `MessageRow` + `ProvenanceLink`, immutable, transactional, FK-integral. Tested. | **KAE-Memory** — unambiguously | `retire` |
| **Knowledge extraction** | Model-driven with a schema, plus a governor. Untested against a live provider. | `ExtractionPort`, deterministic + Bedrock adapters, writes versioned `KnowledgeItem` in one transaction with the producing run. | **KAE-Memory** | `adapt` — take the governor, keep Memory's write path |
| **Corrections and revisions** | Correction handling exists in the v1.3 decision-log work; supersession semantics unverified. | `append_version`, `LifecycleState`, `supersedes`, guarded transitions. Tested. | **KAE-Memory** | `retire` |
| **Decision history** | `ai_decision_log.py` (100% covered) — per-turn JSONL of AI proposal, governor verdict, warnings. | Agent runs, provenance links, readiness snapshots. No per-turn governance record. | Split: turn-level to Memory as evidence; decision knowledge is Memory's | `adapt` — the *format* is the asset |
| **Readiness** | **Unsound.** 7 required fields → 100% "ready_for_generation" while its own rubric fails. Empty areas score 100%. | Weighted areas, per-area state, append-only snapshots, staleness, blockers, explainable. Tested. | **KAE-Memory — no contest** | `retire` |
| **Requirements generation** | Prose sections; identifiers only in a hand-curated sample; no acceptance criteria. | `BlueprintService` — statements are confirmed knowledge's own text, labelled `grounded`/`derived`/`assumption`, fully traceable. | **KAE-Memory** | `retire` |
| **Module discovery** | One optional field (`service_boundaries`). Modules appear in generated prose without evidence. | Absent — a known structural gap with a defined minimum capability contract. | **KAE-Memory** (once built) | `reference_only` |
| **Dependency modeling** | **Absent.** | Absent — `RelationshipType` exists but has no `depends_on` and no write path. | **KAE-Memory** (once built) | Not applicable |
| **Context packaging** | Multi-artifact packages with profiles; **no provenance in any generated file**; flagship example hand-curated. | `BlueprintService.generate` + `render_markdown` + `trace`; project-scoped only. | **KAE-Memory** assembles; Studio renders/publishes | `reference_only` — the artifact *taxonomy* is useful |
| **Client continuity** | Session resume from local files. Single-machine, single-process. | Durable runs with leases, resume, cross-client state; MCP-M1 will expose it. | **KAE-Memory** | `retire` |

## Component dispositions

Every disposition carries evidence and rationale. One disposition per component, as required.

### `adapt` — take the idea, rewrite inside KAE

**`ai_interview.govern_turn` — deterministic governor**
*Evidence:* `src/cie_slim/ai_interview.py:230-281`; tested in `tests/test_governance.py`; zero warnings across the 16-turn live run.
*Rationale:* Verbatim grounding is the one control that stops a model inventing a requirement, and KAE-Memory has nothing equivalent — extraction currently writes whatever the adapter returns. This belongs in Memory's write path, applied to every client including MCP observations. Port the rule, not the module: it must operate on `KnowledgeKind` and `MessageRow`, not on Slim's field ids.

**`ai_decision_log.py` — per-turn governance record**
*Evidence:* `src/cie_slim/ai_decision_log.py`, 100% covered; `out/live/ai_decisions.jsonl`, 34 KB of real turns.
*Rationale:* Recording *what the model proposed, what the governor accepted, and why it rejected the rest* is exactly the audit trail KAE sells. Memory records runs but not per-turn governance verdicts. Adopt the shape as evidence metadata.

**Interview loop shape and question-selection behaviour**
*Evidence:* the 16-question live transcript — adaptive, option-offering, non-repetitive.
*Rationale:* This is the behaviour KAE-M2 must reproduce. Reuse the observed *pattern* (probe → govern → record → select next from gaps); do not import the implementation, which is bound to file-based sessions.

### `reference_only` — read it, build our own

**Discovery model (`discovery_model.yaml`)** — *Evidence:* 26 fields, 13 of them tech picks, 7 KAE areas absent. *Rationale:* the `covered_when` phrasing is a genuinely good idea (an explicit, human-readable coverage predicate per field); the field set itself is not KAE's and must not become it.

**Interview stages and project-type packs** — *Evidence:* `workflow_registry.py` (96% covered), `domain_packs/` untracked. *Rationale:* staged interviews map onto KAE's typed interviews, but Slim's stages encode its own model.

**Artifact profiles and context builder** — *Evidence:* `context_builder.py`, `interview_artifacts.py`; `examples/outputs/church_ministry_portal/`. *Rationale:* the artifact taxonomy (Requirements / ArchitectureGuide / ImplementationContext / ValidationPlan / open_questions / assumptions) is a useful checklist against KAE's package structure. The generation itself has no provenance and cannot be trusted.

**Question bank and `question_backlog.py`** — *Evidence:* 96% covered, small and clean. *Rationale:* KAE's question banks live in `DISCOVERY_INTERVIEWS.md` and will be methodology knowledge under ADR-0005, not code.

**Provider adapters** — *Evidence:* `model_client.py`, 76% covered, no retry or rate limiting. *Rationale:* KAE-Memory already has `ExtractionPort`/`EmbeddingPort` with worker leases and retry. The `claude-cli` and `ollama` adapters are worth reading if local-model support is ever wanted.

### `defer_pending_evidence`

**The entire `src/cie_slim/kae/` package** — 17 modules, ~6,020 lines.
*Evidence:* **untracked in git; 0% test coverage; 1,741 statements.** Contains `knowledge_model.py`, `coverage.py`, `gap_detector.py`, `extractor.py`, `knowledge_auditor.py`, `question_planner.py`, `conversation_engine.py`.
*Rationale:* This is a second knowledge model with a stated design contract ("every field value is sourced from a confirmed user statement, not inferred") that **nothing verifies**. It is simultaneously the most KAE-relevant and the least trustworthy code in the repository. It cannot be assessed as reusable while it has no history and no tests. **It must not be imported into KAE-Memory in any form** — it would be a competing source of truth arriving untested.
*Required before reassessment:* commit it, test it, and demonstrate the design contract holds.

**`gap_detector.py` specifically** — deterministic gap detection is conceptually right and aligns with KAE's findings model, but shares the untracked/untested status. Reassess after the above.

### `retire` — KAE-Memory already owns this, better

- **File-based session persistence** (`session_store.py`) — no locking, no idempotency, single-process. Memory has transactional, FK-integral storage on CockroachDB.
- **Readiness/scoring** (`scoring.py`, `interview_quality.py`) — demonstrably unsound; Memory's model is weighted, explainable, snapshotted, and staleness-aware.
- **Requirements generation** (`templates.py`, artifact writers) — Memory's blueprint renders confirmed knowledge's own text with labels and full trace.
- **Evidence retention** — Memory's immutable messages with provenance links.
- **Client continuity** — Memory's durable runs; MCP-M1 exposes them to any client.

### `rewrite`

**Nothing is recommended for rewrite-in-place.** The components worth keeping are `adapt` (rebuilt inside KAE against Memory's domain); the rest are `reference_only` or `retire`. A rewrite disposition would imply Slim's structure survives, and no component earns that.

## Expert-role investigation

**Finding: no role-profile mechanism exists.** Searching for `role_profile`, `persona`, `expert`, or analogous constructs returns only workflow-registry and domain-router matches — routing by *project type*, not by *reviewer perspective*.

The closest reusable idea is `workflow_registry.py`'s notion of a named workflow selecting stages and artifact profiles. That is a structural precedent for role profiles (a named configuration selecting concerns, questions, and deliverables) but contains nothing role-specific.

**Recommendation:** role profiles should be designed fresh, as governed configuration over one shared acquisition runtime, per the stated preference — areas of concern, question priorities, expected deliverables, gap rules, review criteria, allowed knowledge kinds, escalation conditions. All roles read and write the same Memory-held evidence and knowledge. Slim contributes the precedent that a named profile can select stages and outputs, and nothing more.

## Capabilities that must not be duplicated

KAE-Memory owns these. No Slim component, and no acquisition runtime, may hold a competing version:

immutable evidence · structured knowledge and versions · corrections, supersession, lifecycle · provenance and traceability · confirmation state · relationships and dependencies · **readiness** · review findings · retrieval · context assembly · durable acquisition-session state.

The specific hazard identified by this evaluation: **Slim's `KnowledgeState` and its readiness score are exactly such a competing version.** Any option that keeps them authoritative creates two sources of truth.
