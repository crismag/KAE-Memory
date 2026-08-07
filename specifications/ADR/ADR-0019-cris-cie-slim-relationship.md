# ADR-0019 — CRIS-CIE Slim is a reference prototype; KAE builds acquisition natively

- **Status:** proposed
- **Date:** 2026-08-01
- **Depends on:** [`ADR-0012`](ADR-0012-blueprint-readiness-model.md), [`ADR-0006`](ADR-0006-extraction-contract.md), [`ADR-0018`](ADR-0018-mcp-engineering-context-server.md)
- **Evidence:** `CRIS_CIE_SLIM_CURRENT_STATE.md`, `CRIS_CIE_SLIM_CAPABILITY_MATRIX.md`, `CRIS_CIE_SLIM_TEST_AND_RISK_ASSESSMENT.md`, `KAE_ACQUISITION_INTEGRATION_OPTIONS.md` — historical evidence, held as archived development context

## Context

KAE is becoming a system that fully defines a software project before development begins. It needs an acquisition capability: interviewing users, discovering knowledge, detecting gaps and conflicts, and routing conclusions for confirmation.

`crismag/cris-cie-slim` contains an interview runtime, a question governor, a discovery model, provider adapters, a decision log, and context generation. It was previously discussed as a possible foundation. This ADR records the outcome of inspecting it — code, tests, configuration, generated artifacts, and one recorded live-provider run — at commit `724ac65`.

### What the evidence shows

**The interview is better than expected.** A recorded live run (`out/live/`) shows 16 adaptive, context-referencing, non-repetitive questions with zero governor warnings.

**The knowledge layer is unsound.** The same run reports readiness **100%**, status `ready_for_generation`, gate **Clear** — while its own rubric returns relevance **fail** and efficiency **fail**. Two areas score 100% because they contain *no required fields*: "integration clarity has no required fields; treated as clear." Readiness means "the 7 fields marked required were touched."

**The flagship artifact is not generated output.** `examples/outputs/church_ministry_portal/` declares `"provider": "echo"` and `"note": "Reference sample package — illustrates the ideal demo output."` `echo` is the offline placeholder provider.

**No generated document contains provenance.** Zero evidence references across the generated package.

**Forty-five percent of the code is untracked and untested.** `src/cie_slim/kae/` — 17 modules, ~6,020 lines, 1,741 statements — is absent from git history with 0% coverage, and contains a second knowledge model whose stated design contract nothing verifies.

**The discovery model misses seven of KAE's nineteen knowledge areas** entirely, including acceptance criteria, dependencies, risks, assumptions, and implementation phases. Modules are one optional field.

## Decision

**CRIS-CIE Slim is a reference prototype. KAE builds its acquisition capability natively in KAE-Memory. Two specific ideas are ported, rewritten against KAE's domain.**

### 1. KAE-Memory remains the sole authority

Evidence, structured knowledge, versions, corrections and supersession, provenance, confirmation state, relationships and dependencies, **readiness**, findings, retrieval, context assembly, and durable acquisition-session state.

No Slim component becomes authoritative for any of these. In particular, **Slim's `KnowledgeState` and readiness score are a competing source of truth and are not imported in any form.**

### 2. Port the deterministic grounding governor

Slim's `govern_turn` rejects a model-proposed fact unless its `source_text` appears in the user's actual answer, whitespace-normalised; rejects invented fields; rejects duplicate and frustration-echoing questions.

**KAE-Memory has no equivalent — extraction currently writes whatever the adapter returns.** A grounding gate is added to the knowledge write path, applying to every client including MCP observations. The rule is ported; the code is not — it must operate on `KnowledgeKind` and `MessageRow`.

### 3. Port the per-turn governance record

What the model proposed, what was accepted, and why the rest was rejected, retained as evidence metadata. Memory records runs, not governance verdicts. This is the audit trail the product's traceability claim depends on.

### 4. Read, do not import

The `covered_when` coverage-predicate idea, the artifact taxonomy, the staged-interview precedent, and the recorded live transcript as a behavioural benchmark for KAE-M2.

### 5. Nothing from `src/cie_slim/kae/` is imported

Not until it is committed to the repository and covered by tests that verify its stated design contract. Its status is `defer_pending_evidence`.

### 6. Slim may later become a test client

After KAE-M2 defines an acquisition contract, Slim can prove that contract as an independent client — a genuinely useful role, and the one place its provider adapters and offline operation retain value. This is deferred, not adopted.

### 7. Readiness authority is not shared

KAE-Memory's weighted, explainable, snapshotted readiness model (`ADR-0012`) remains canonical. No acquisition runtime computes a competing completion figure.

## Consequences

### Positive

- KAE gains a grounding control it currently lacks, closing a real hole in the extraction write path.
- No competing knowledge model, no second readiness authority, no untested code enters KAE-Memory.
- The acquisition loop is designed against KAE's nineteen knowledge areas rather than Slim's twenty-six fields.
- Slim's live transcript becomes a concrete quality bar for KAE-M2 to meet.
- Slim remains free to evolve independently; KAE takes no dependency on it.

### Negative

- KAE builds the interview runtime it could have inherited — the largest cost of this decision.
- Slim's seven provider adapters are not reused; Memory's `ExtractionPort` covers extraction, but a Studio-side interview provider layer is still to be built.
- Offline standalone acquisition, which Slim has today, is not delivered by this path.
- Prior expectations that Slim would accelerate acquisition are not met.

### Accepted risk

Building natively risks reproducing mistakes Slim already made and solved. The mitigation is the recorded transcript and the `covered_when` idea: read them before designing KAE-M2's question selection.

## Alternatives rejected

**Slim becomes KAE's acquisition runtime (Option A).** Rejected. Removing its competing knowledge model, readiness, and file persistence exceeds the cost of building the loop cleanly, and the end state still carries 6,020 untracked, untested lines.

**Extract more broadly than the governor.** Rejected. No other component has evidence of correctness independent of the model this evaluation found unsound.

**Adopt now, validate later.** Rejected. The unsound readiness model would become KAE's completion criterion in the interim, and "ready for generation" is precisely the claim KAE cannot afford to get wrong.

**Run a scenario benchmark before deciding.** Considered and rejected as a blocker. No scenario outcome would make a readiness model adoptable that scores empty areas at 100%. The benchmark is worth running only if Slim is revisited as a client.

## Required KAE-Memory changes

1. **Grounding gate on the knowledge write path** — *new, from this evaluation.*
2. **Per-turn governance record** — *new, from this evaluation.*
3. Idempotent evidence ingestion — already in `ADR-0018`.
4. Durable acquisition-session state: asked, answered, deferred, superseded.
5. Gap → question selection support.
6. Relationship write and traversal; module-scoped readiness; purpose-bounded context assembly.
7. `KnowledgeKind` and `RelationshipType` extension.

## Non-goals

Merging the repositories · making Slim a runtime dependency · importing Slim readiness or `KnowledgeState` · copying KAE domain code into Slim or Slim persistence into KAE · expert-role agents before one governed loop is proven · treating `church_ministry_portal` as demonstrated capability.

## Follow-up

- **CIE-EVAL-3** — define provider-independent acquisition contracts in KAE-Memory.
- **KAE-M2** — the smallest complete governed acquisition loop, with cross-client continuation.
- Reassess `src/cie_slim/kae/` if it is ever committed and tested.
- Revisit Slim as a contract test client after KAE-M2.
