# Master MCP Target Checklist

Status: **control register**, opened 2026-08-03. Updated after each completed target.

This is the authoritative list of what the MCP surface still needs. It is
sequenced: Phase A reduces what every later response costs, Phase B fixes the
one capability that currently reports itself unavailable, and Phases C to E add
the surfaces for engine capability that already exists but cannot be reached.

T1B was inserted between T1 and T2 to settle the response-policy architecture
before any response is changed.

Legend: `[ ]` not started · `[~]` in progress · `[x]` complete

---

## Phase A — Token and response efficiency

- [x] **T1** — Measure current MCP response size and duplication — [`MCP_RESPONSE_BASELINE.md`](MCP_RESPONSE_BASELINE.md), 2026-08-03
- [x] **T1B** — Define MCP response profiles and consumption controls — [`MCP_RESPONSE_POLICY.md`](../06_architecture/MCP_RESPONSE_POLICY.md), 2026-08-03
- [x] **T2** — Define compact MCP response conventions — `mcp/response_policy.py`, 2026-08-03
- [x] **T2B** — Compact response conventions (style) —
  [`ADR-0021`](../../specifications/ADR/ADR-0021-compact-response-conventions.md),
  2026-08-03. T2 shipped the mechanism; this is the naming, nulls, ordering,
  and references half. Audit: 6 of 8 tools partial, none non-compliant
- [x] **T3** — Trim `kae_get_project_briefing` — 12,199 → 3,634 chars (71%), 2026-08-03
- [x] **T4** — Apply pagination, limits, and detail levels to read tools —
  2026-08-05. All four §Coordination items honoured: the `{total, page, cursor,
  results}` wrapper on `kae_list_projects`, `kae_get_open_decisions`, and
  `kae_search_knowledge`; `count` split into `matched_chunks` /
  `matched_knowledge_items`; per-area counts moved to `diagnostic` (rule 15);
  and `note` registered as a short form while `why` gates on prose.

  `total` counts the collection, never the page — an agent that read twenty of
  forty open decisions and believed it had seen them all would plan around a
  project it only partly understood. An unreadable cursor is an error rather
  than a silent restart from page one.

  Found and fixed on the way: `_prune` descended into dicts but not into list
  elements, so a field map entry naming a key inside every element was silently
  ignored. The response looked compacted and was not.
- [ ] **T5** — Verify token reduction without losing essential context

## Phase B — Embedding replacement

- [x] **T6** — Select the model — ADR-0008, `amazon.titan-embed-text-v2:0`,
  availability verified in `ca-central-1` 2026-08-03
- [x] **T7** — Model and version metadata — `embedding_model`,
  `embedding_dimensions`, `embedding_version` recorded on every chunk
- [x] **T8** — Implement the real embedding provider — `agents/provider.py`,
  2026-08-03. `KAE_EMBEDDING` selects; region resolves through AWS_REGION,
  AWS_DEFAULT_REGION, then the active profile; selection raises rather than
  falling back to hash-derived vectors
- [x] **T9** — Restartable re-embedding workflow — `ReembeddingService` +
  `scripts/development/reembed-knowledge.py`, 2026-08-03. `EMBEDDING_VERSION`
  bumped to 2; selection is version-aware; claiming is compare-and-set; failures
  are isolated and retryable; the old vector survives a failed request
- [x] **T10** — Re-embed existing knowledge — 2026-08-03. All 32 chunks migrated
  to Titan V2 at version 2; 12 post-migration checks pass; rerun is a no-op;
  lexical retrieval unaffected throughout
- [x] **T11** — Validate semantic retrieval quality — 2026-08-03,
  [RETRIEVAL_QUALITY_T11.md](RETRIEVAL_QUALITY_T11.md). **Accepted with
  documented limitations.** Semantic top-3 100%, MRR 0.91, paraphrase 100%
  against lexical 0%. Required raising `MAX_DISTANCE` 0.75 → 0.85 on measured
  distances. The limitation: the usable window for a global cutoff is 0.005
  wide, one weak query now leaks, and hybrid ranking — not a better constant —
  is the follow-up

## Phase C — Knowledge review surfaces

- [x] **T11B** — Implement `kae_create_project` — 2026-08-03. Out of sequence: an
  agent could submit an observation about a project but could not bring one into
  being, so the surface was unusable without a second channel. Settles the open
  question of whether project creation is human-only — it is not.

- [x] **T12** — Implement `kae_confirm_knowledge` — 2026-08-03. Carries the
  Phase C foundation: migration `0007` adds the append-only
  `knowledge_review_events` log; ownership is enforced in `MemoryService`, which
  also closes the same hole in the HTTP confirm route; `expected_version` gives
  item-level optimistic concurrency using the existing `KnowledgeVersion` number
  rather than a second revision field; new error codes `knowledge_not_found`,
  `version_conflict`, `invalid_state_transition`. Also fixes
  `kae_submit_observation` recording agent output as `ActorType.USER`.
  Decisions and amended checks in [PHASE_C_DECISIONS.md](PHASE_C_DECISIONS.md).
- [x] **T13** — Implement `kae_reject_knowledge` — 2026-08-03. Closes the live
  defect: lifecycle existed only inside the embedded metadata prefix, so
  rejected knowledge was ranked and returned by search. Now filtered in SQL on
  both the semantic and lexical paths, with `RETRIEVABLE` / `AUTHORITATIVE` /
  `HISTORICAL` scopes per the B1 decision. Every result carries `state` and
  `authoritative`, read live from the item and protected as integrity fields.
  Also fixes `reject_knowledge` accepting a `note` and discarding it.
- [x] **T14** — Implement `kae_correct_knowledge` — 2026-08-03. Append-only:
  the original proposal is preserved and attributed to the agent, the correction
  to the person. Approved lifecycle split implemented, keyed on the **actor**
  as well as the prior state — an agent correction never validates, or the
  worker could confirm knowledge. Migration `0008` adds `from_version_number`,
  because an event carrying one version number cannot say which wording gave way
  to which. Corrected chunks are marked stale for the Phase B re-embed workflow;
  no embedding call inside the review transaction (ADR-0008, B2).
- [x] **T15** — Verify audit trail and readiness recalculation — 2026-08-03,
  [PHASE_C_COMPLETION.md](PHASE_C_COMPLETION.md). Audit coverage, attribution,
  ordering, replay and stale-decision behaviour verified; readiness verified
  against the repository's existing lifecycle rules rather than restated. Adds
  `review_history_for_project` as the minimal read surface, and one end-to-end
  scenario over the whole workflow. **Scenario 3 is not applicable**: correction
  cannot reclassify knowledge, because `kind` is immutable and readiness
  resolves through area link plus kind — asserted as a test rather than omitted.
  Phase C verdict: **complete with documented limitations**.

## Phase D — Clarification surfaces

- [x] **T16** — Implement `kae_get_clarifications` — 2026-08-04. Settles the
  identity mismatch that gated Phase D: clarifications derived from findings
  have no id, so this **records** the questions it returns, keyed on subject
  through the existing `_question_key` and `UNIQUE (project_id,
  idempotency_key)`. The mutation behind a `get_` name is declared in the tool
  description, the docstring, the write-surface guardrail, and a test. Fixes
  three ownership defects in `ClarificationService`, the worst of which wrote an
  answer into another project's session while claiming this project's id.
- [x] **T17** — Implement `kae_answer_clarification` — 2026-08-04. Records a
  person's answer verbatim and queues extraction. The response keeps three facts
  separate — answer accepted, extraction scheduled, **knowledge unchanged** —
  and `knowledge_state` / `knowledge_changed` are integrity fields, so no
  profile can compact "answered" into "known". One logical answer per question:
  a retry replays it, a *different* answer is refused, because nothing
  downstream could say which one the project believes.
- [x] **T18** — Connect clarifications to blockers and knowledge — 2026-08-04,
  [PHASE_D_COMPLETION.md](PHASE_D_COMPLETION.md). The loop closes end to end
  through the **real worker**, not a stand-in: answer accepted -> extraction
  queued -> worker claims -> proposed knowledge with provenance -> human
  confirms -> readiness moves. `ClarificationState` exposes where a
  clarification has reached, derived from the records rather than stored beside
  them. Every integrity claim has a test that fails if it stops being true —
  including that proposed knowledge earns no readiness coverage. **Phase D
  complete.**

## Phase E — Ingestion and assembly

- [x] **T19** — Implement `kae_ingest_document` — 2026-08-04. The service
  existed; this exposes it. The response separates three facts a caller must
  not collapse: text recorded, extraction **queued**, knowledge unchanged. An
  unread remainder is reported rather than dropped, because nothing downstream
  can tell an absent requirement from one that was never read.
- [x] **T20** — Connect ingestion to observations and proposed knowledge —
  2026-08-04. Draining the queued runs yields candidates that are **proposed**,
  each tracing to the stored span it came from. A document cannot confirm its
  own contents; ingesting a file must not become the project's opinion.
- [x] **T21** — Implement `kae_assemble_context` — 2026-08-04. Bounded by
  purpose, pinned to a revision, and hashed, so the same inputs produce the
  same package. The manifest always carries the confirmation split and every
  unresolved gap: generation may be incomplete, it may never be silent.
- [x] **T22** — Generate compact manifests and external artifacts — 2026-08-04.
  Deliberately metadata, not bytes: `describe_package` says what a package would
  contain — one artifact per non-empty area, each with its own hash and its
  confirmed split — without rendering or storing anything. No new tables.
  Rendering belongs to whoever owns the destination; what a caller needs first
  is the shape, so it can decide whether to render at all. Content is
  deterministic while `package_id` is a fresh identity per generation, because
  "the package I already have" and "this act of assembling" are different
  questions.
- [x] **T23** — Complete end-to-end MCP workflow test — 2026-08-04. The Demo V1
  scenario, executed through the MCP surface rather than around it: create a
  project, ingest a document, drain the queue, read the briefing, confirm a
  candidate, assemble a bounded context, describe the package. What it defends
  is the honesty of each transition — a workflow that quietly promoted evidence
  to fact, or produced a package that read as complete while carrying an
  unanswered question, would pass a naive end-to-end test and fail the only
  claim that matters.

  **Phase E verdict: complete.**

## Phase F — Project focus and default scope

**T25 — Make the selected project the default scope.** Deferred, **implementation
not authorised.** Design: [`PROJECT_FOCUS.md`](../06_architecture/PROJECT_FOCUS.md).

Scoped down after review: cross-project isolation is **already enforced** — six
of eight tools require a `project_id`, every service call is single-project, and
no tool can return knowledge from a project the caller did not name. The gap is
ergonomics and disambiguation, not leakage.

- [ ] **T25.1** — Studio injects the active `project_id`. **Zero KAE change**;
  solves the Studio case entirely
- [ ] **T25.2** — Accept `project_key` alongside `project_id` on every
  project-scoped tool. Stateless, no schema change, removes the
  list → pick → call hop that suppresses routing
- [ ] **T25.3** — *Only if T25.2 proves insufficient:* server-side active
  project, with a mandatory `scope` echo naming the project and how it resolved
- [ ] **T25.4** — Cross-project comparison as a separate tool, never a wider
  setting on an existing one

**Acceptance criteria**

- Explicit project arguments always override any default.
- No project and no default is an `invalid_argument` error, never an inferred
  project.
- Any response answered from an implicit focus states the project and
  `resolved_from`.
- Every tool remains callable statelessly with an explicit project.
- Focus is never an authorisation boundary.
- No schema change, no migration, no new mandatory concept.

## Phase G — Observation classification

**T24 — Classify and route submitted observations.** High priority, **deferred,
awaiting scheduling. Implementation not authorised.** Design:
[`OBSERVATION_CLASSIFICATION.md`](../06_architecture/OBSERVATION_CLASSIFICATION.md).

No existing target owned this. T19/T20 cover ingesting *documents* into proposed
knowledge; neither classifies a submitted observation, separates retention
tiers, records operational state, or filters briefings by tier.

- [ ] **T24.1** — Deterministic extraction: dates, milestone and target IDs,
  status words, action verbs
- [ ] **T24.2** — Semantic classification into the §4 taxonomy, with confidence
  and mixed-span support
- [ ] **T24.3** — Operational records: milestone transitions, check-ins, tasks,
  defects, test results
- [ ] **T24.4** — Briefing filters by retention tier
- [ ] **T24.5** — Resolve `classification_hint`: honour it or remove it

**Acceptance criteria**

- One observation may produce several classified spans, each tracing to a real
  span of the stored text.
- The original observation is never rewritten or replaced.
- A reported milestone completion creates a *proposed transition*, never a
  status change.
- Check-ins extract subject, date, timezone, and **date role**.
- Personal commentary is preserved as evidence and excluded from standard
  briefings.
- Low-confidence text stays unclassified rather than being routed.
- Classifier replay creates no duplicates; a version upgrade preserves prior
  results and review history.
- Observation submission succeeds when classification fails.
- Contradictions and ordinary operational transitions are treated differently.
- Classification never confirms durable knowledge (FR-005).

---

## Starting position

Recorded 2026-08-03 from the live server after it was restarted onto `main`,
against the `kae_dev` Ministry Reporting project. This was the observation
that prompted the register; **T1 has since superseded it** with measurements
across two projects, a section-by-section breakdown, and a duplication
register. See [`MCP_RESPONSE_BASELINE.md`](MCP_RESPONSE_BASELINE.md) — the
figures below are kept only as the register's own history.

### Response sizes

| Tool | Chars | ≈ Tokens |
| --- | --- | --- |
| `kae_list_projects` | 286 | 71 |
| `kae_get_open_decisions` | 644 | 161 |
| `kae_search_knowledge` | 1,965 | 491 |
| `kae_get_readiness` | 1,969 | 492 |
| `kae_get_module_context` | 2,535 | 633 |
| **`kae_get_project_briefing`** | **12,199** | **3,049** |

### Known duplication in the briefing

Each of these was an additive choice made to avoid breaking existing consumers.
Together they are why one call costs ~3k tokens.

- `explanation.missing` and `explanation.incomplete` are identical whenever no
  area is partial — which is the common case. They differ only when an area has
  half credit.
- The eight findings are rendered three times: `findings` (full objects),
  `findings_by_severity` (summaries), `recommended_next_steps` (actions).
- `missing_mandatory_areas` and `missing_information` carry the same areas,
  once as keys and once as keys with names.

### Surface coverage gap

Built and tested as application services, reachable from neither MCP nor the
31 HTTP routes. Phases C to E close this.

| Capability | Service | MCP | HTTP |
| --- | --- | --- | --- |
| Document ingestion fan-out | `IngestionService` | ✗ | ✗ |
| Clarification loop | `ClarificationService` | ✗ | ✗ |
| Correction / rejection / supersession | `MemoryService` | ✗ | ✗ |
| Bounded assembly + manifest | `AssemblyService` | ✗ | ✗ |

### Retrieval

`semantic_search_available: false`. The active embedder is
`DeterministicEmbeddingAdapter`, which is hash-derived and cannot rank meaning.
Lexical retrieval answers term queries; conceptual queries correctly return
nothing. Phase B is what changes that.

---

## Architectural blockers

Reviewed 2026-08-03. Everything else previously listed is now resolved,
deferred, implementation work, operational, or project-specific.

**These four remain, and they are one problem in four parts:**

1. **Relationship vocabulary** — four competing lists; only `depends_on` appears
   in three. Names are hard to change once graph data exists, so this must be
   settled *before* any relationship is written.
2. **Module relationship model** — how a module owns, depends on, and exposes.
3. **Module graph traversal** — dependents, dependencies, build order.
4. **Module-scoped context assembly** — the bounded package `KAE_PACKAGE_MODEL.md`
   §4 specifies and `kae_get_module_context` reports as unavailable.

(1) gates the rest. Nothing else on this register is blocked by them.

### Settled 2026-08-03

| Question | Resolution |
| --- | --- |
| Module readiness — one figure or a profile | **Profile.** Multiple dimensions, as with project readiness. A single percentage may be a derived visualisation, never a replacement |
| Detail-level naming | **Three:** `summary` / `standard` / `diagnostic` |
| Integrity floor vs budget | **Integrity wins.** Return the smallest context satisfying the floor; report any overage; never truncate silently |
| `recommended_next_steps` | **Remove.** No consumer outside its own tests |
| Project focus | **Accepted principle** — the active project is the default boundary; leaving it needs explicit intent |
| Duplicate project names | **Idempotent everywhere.** HTTP now matches MCP |
| M8 / M9 milestone status | **Aligned.** The plan table is authoritative |

### Deferred — not blockers

Project and Session configuration tiers · per-tool vs per-call detail · draft vs
registered context · `classification_hint` · observation classification (T24) ·
project-focus implementation (T25).

### Not architecture

MCP reconnection after a merge, `boto3` for Bedrock, and tokenizer
standardisation are operational. Ministry Reporting's and Local test's open
questions are project-specific and do not affect the platform.

## Constraints that apply throughout

Carried from decisions already recorded elsewhere in this repository, so that
work against this checklist does not quietly reverse them.

- A response never claims more than it can support. Trimming in Phase A must not
  remove a statement of what a tool did *not* do — the warnings and mode fields
  are content, not overhead.
- Confirmation is a human act (FR-005). Phase C exposes it; it does not automate
  it.
- A review run reports contradiction candidates and does not record them
  (ADR-0015).
- Findings have no identity. Phase D links questions to their *subject*, not to
  a finding key.
- `source_knowledge`, `confirmation_state`, and `unresolved_critical_gaps` are
  never empty-by-omission in an assembly manifest (`KAE_PACKAGE_MODEL.md` §1).
- Assembly scope is `project`. Module scope stays unimplemented until modules,
  the relationship write path, and graph traversal exist.
