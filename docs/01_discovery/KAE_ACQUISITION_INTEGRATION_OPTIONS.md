# KAE Acquisition — Integration Options for CRIS-CIE Slim

Status: **options analysis**, 2026-08-01. Companion to `CRIS_CIE_SLIM_CURRENT_STATE.md`, `..._CAPABILITY_MATRIX.md`, `..._TEST_AND_RISK_ASSESSMENT.md`.

## The question

> Which parts of CRIS-CIE Slim have enough demonstrated value to accelerate KAE's governed project-acquisition workflow, without creating a competing source of truth or importing unverified behaviour?

## Constraints every option must satisfy

1. KAE-Memory remains the sole authority for evidence, knowledge, corrections, provenance, confirmation, relationships, **readiness**, findings, retrieval, and context assembly.
2. No second knowledge model becomes authoritative.
3. Nothing untested enters KAE-Memory.
4. Fixture or `echo`-provider output is never presented as capability.
5. KAE must remain operable without Slim.

## Option A — Slim becomes KAE's acquisition runtime

Slim is adapted to use KAE-Memory for durable state and exposed to Studio and development tools.

| Dimension | Assessment |
| --- | --- |
| Duplication | **Severe.** `KnowledgeState`, `coverage`, `gap_detector`, `scoring`, and session persistence all duplicate Memory. Each must be gutted, not adapted. |
| Coupling | High and bidirectional; Slim's control flow assumes local files it would no longer own. |
| Maintainability | Poor. 45% of the tree is untracked and untested; adopting it makes that debt KAE's. |
| Offline usability | Currently good — and would be **lost**, since durable state moves to CockroachDB. |
| Studio compatibility | Weak. Studio needs an API, not a CLI process. |
| Claude/Codex/Cursor compatibility | Only via a new MCP surface, which is Memory's job anyway. |
| Provider flexibility | Good (7 adapters) — the one genuine advantage. |
| Testability | Poor until `kae/` is committed and tested. |
| Deployment complexity | New runtime to package, version, and host. |
| Knowledge integrity | **Unacceptable risk.** Slim's readiness and knowledge model would arrive with it. |
| Migration effort | **Largest.** Most of Slim would be rewritten; what remains is the part already recommended for `adapt`. |

**Verdict: reject.** The work of removing Slim's competing model exceeds the work of building the loop cleanly, and the end state still carries an untested package.

## Option B — Extract selected components into KAE-Memory

Only proven interview/governance components are moved or rewritten inside KAE-Memory.

| Dimension | Assessment |
| --- | --- |
| Duplication | **None** if scoped to the governor and decision-log shape. |
| Coupling | None — Slim becomes irrelevant after extraction. |
| Maintainability | Good. Small, well-understood additions to a tested codebase. |
| Offline usability | Unchanged; Memory already runs fully offline. |
| Studio compatibility | Good — Studio consumes Memory's API as designed. |
| Claude/Codex/Cursor compatibility | Good — arrives through the MCP surface already planned. |
| Provider flexibility | Unchanged; Memory has `ExtractionPort`. |
| Testability | Good. The governor is a pure function and directly testable. |
| Deployment complexity | None. |
| Knowledge integrity | **Improved.** The grounding gate closes a real hole in Memory's write path. |
| Migration effort | **Smallest.** Two ideas, rebuilt against Memory's domain. |

**Verdict: recommended as the primary path.** The governor and the per-turn governance record are the only components with demonstrated value that KAE-Memory lacks.

## Option C — Slim remains an independent KAE client

Slim communicates through MCP or HTTP and proves the same acquisition contracts other clients would use.

| Dimension | Assessment |
| --- | --- |
| Duplication | Tolerable if Slim's local state is explicitly a cache, never authoritative. |
| Coupling | Low, and contract-shaped — exactly what MCP-M1 exists to provide. |
| Maintainability | Moderate; two repositories, one contract. |
| Offline usability | **Preserved** — Slim keeps working standalone when Memory is unreachable. |
| Studio compatibility | Neutral; both are peer clients. |
| Claude/Codex/Cursor compatibility | Good — Slim proves the same surface those clients use. |
| Provider flexibility | **Best.** Slim's adapters stay useful without entering Memory. |
| Testability | **Valuable** — Slim becomes a second, independent implementation exercising the acquisition contract, which is how contract bugs surface. |
| Deployment complexity | Low; nothing new is hosted. |
| Knowledge integrity | Safe **only** if Slim's readiness and `KnowledgeState` are demoted to local advisory state. |
| Migration effort | Low, but it is Slim-side effort with no KAE deliverable. |

**Verdict: valuable later, as a test client — not now.** It presupposes an acquisition contract that does not yet exist. It becomes attractive after KAE-M2.

## Option D — Slim remains reference-only

KAE implements a new acquisition runtime, reusing only validated models, questions, tests, or patterns.

| Dimension | Assessment |
| --- | --- |
| Duplication | None. |
| Coupling | None. |
| Maintainability | Best — KAE owns everything it runs. |
| Offline usability | Unchanged. |
| Studio compatibility | Best; designed for it. |
| Claude/Codex/Cursor compatibility | Best; designed for MCP from the start. |
| Provider flexibility | Requires building what Slim already has. |
| Testability | Best — tests written against KAE's own criteria. |
| Deployment complexity | None beyond what is planned. |
| Knowledge integrity | Highest. |
| Migration effort | Highest *build* effort, but no *unwinding* effort. |

**Verdict: the correct default**, and Option B is a strict improvement on it — B is D plus two specific, evidenced borrowings.

## Recommendation

**Option B, with Option D as the surrounding posture and Option C reserved for later.**

Concretely:

1. **Build KAE's acquisition loop natively** in KAE-Memory (KAE-M2). Do not adopt Slim's runtime.
2. **Port two things, rewritten against Memory's domain:** the deterministic grounding governor, and the per-turn governance record.
3. **Read, do not import:** the `covered_when` coverage-predicate idea, the artifact taxonomy, the staged-interview precedent, and the live transcript as a behavioural benchmark.
4. **Revisit Option C after KAE-M2 exists,** where Slim earns real value as an independent client proving the acquisition contract.
5. **Import nothing from `src/cie_slim/kae/`** until it is committed and tested.

### Why not simply adopt the runtime that already works

Because what works and what is needed are different layers. Slim's *conversation* is good and its *knowledge model* is not — and the conversation is the cheaper half to rebuild. Adopting the runtime means inheriting the readiness model that certified a project complete on seven fields while its own rubric failed, and a 6,020-line untracked package with no tests. The borrowable value is two well-understood ideas, and those transfer in days.

## Required KAE-Memory changes

None of these are created by this evaluation; it confirms and prioritises them.

1. **Grounding gate on the knowledge write path** — reject an extracted item whose source span is not present in the evidence it claims to come from. *New, from this evaluation.*
2. **Per-turn governance record** — store what was proposed, accepted, and rejected, with reasons, as evidence metadata. *New, from this evaluation.*
3. **Idempotent evidence ingestion** — already specified in MCP-M1/ADR-0018.
4. **Acquisition-session state** — durable, resumable, cross-client: which questions were asked, answered, deferred, superseded. *Already identified as a structural gap.*
5. **Gap → question selection** — Memory answers "what is missing"; the runtime turns that into one question.
6. **Relationship write and traversal; module-scoped readiness; purpose-bounded assembly** — the three structural gaps in the capability matrix, needed before module-level acquisition means anything.
7. **`KnowledgeKind` and `RelationshipType` extension** — additive, cheap, unblocks the model.

## Capabilities that must not be duplicated

Immutable evidence · structured knowledge and versions · corrections and supersession · provenance · confirmation state · relationships and dependencies · **readiness** · findings · retrieval · context assembly · durable acquisition-session state.

## Explicit non-goals

- Merging the repositories.
- Making Slim a KAE runtime dependency.
- Importing Slim's readiness or `KnowledgeState` in any form.
- Copying KAE-Memory domain code into Slim, or Slim persistence into KAE-Memory.
- Building expert-role agents before one governed acquisition loop is proven.
- Treating the `church_ministry_portal` package as demonstrable capability.
- Broad refactoring of either repository during this evaluation.

## Phased plan

| Phase | Work | Exit condition |
| --- | --- | --- |
| **CIE-EVAL-0** | Capability inventory | **Complete** — this document set |
| **CIE-EVAL-1** | Executable baseline | **Complete** — 284 tests pass, 59% coverage, `kae/` at 0% |
| **CIE-EVAL-2** | Scenario benchmark | **Deferred, and optional.** Requires live-provider budget and criteria fixed in advance. The recommendation does not depend on it: no scenario result would make Slim's readiness model adoptable. Run only if Option C is revisited. |
| **CIE-EVAL-3** | Acquisition contracts | Provider-independent schemas for interview turn, evidence submission, candidate knowledge, gap, question, answer, assumption, decision, conflict, correction, proposed module, dependency, session state — defined **in KAE-Memory** |
| **CIE-EVAL-4** | Component decisions | **Complete** — dispositions recorded in the capability matrix |
| **KAE-M2** | Governed bidirectional acquisition | The ten-step loop runs end to end through KAE-Memory, and a second client continues from the resulting state |

CIE-EVAL-3 is the real next step, and it is KAE work, not Slim work.

## Executive recommendation

**Do not adopt CRIS-CIE Slim. Borrow two ideas from it and build the acquisition loop natively.**

Slim's interview is better than expected — a recorded live run shows sixteen adaptive, non-repetitive, context-referencing questions with zero governance warnings. Its knowledge layer is worse than its documentation implies: readiness certified a project "ready for generation" at 100% while the same report failed relevance and efficiency, and two areas scored full marks for having no required fields. Its best-looking artifact is a hand-curated sample generated with the placeholder provider. Forty-five percent of the code is untracked and untested, including everything named `kae/`.

The transferable value is real but small: a **deterministic grounding governor** that rejects any model-proposed fact whose source text is not present in the user's own words, and a **per-turn governance log** recording what was proposed, accepted, and refused. KAE-Memory has neither, and both directly protect the knowledge integrity the product is sold on.

Everything else Slim does, KAE-Memory either already does better or must build to its own standard.
