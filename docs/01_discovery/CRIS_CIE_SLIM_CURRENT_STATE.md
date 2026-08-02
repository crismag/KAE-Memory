# CRIS-CIE Slim — Current State

Status: **evidence-based inspection**, 2026-08-01. Investigation only; nothing here authorizes integration.

Repository: `https://github.com/crismag/cris-cie-slim`, inspected at `/home/cris/workspaces/cris-cie-slim`.

## Method

Code, tests, package metadata, configuration, generated artifacts, and a real recorded live-provider run were inspected and the suite was installed and executed. Documentation claims were not accepted as evidence.

## 1. Repository state

| Fact | Value |
| --- | --- |
| Branch | `main`, synchronised with `origin/main` |
| Latest commit | `724ac65` "cie slim model updates" |
| Commit date | **2026-05-29** — roughly two months stale |
| Python | Requires ≥3.11; verified on 3.11.9 |
| Core dependency | `PyYAML` only |
| Optional extras | `anthropic`, `openai`, `dev` |
| Entry point | `cie-slim = cie_slim.cli:main` |
| Install | `pip install -e ".[dev]"` — succeeded without incident |
| Persistence | **File-based JSON**: `session.json`, `workflow_state.json`, `answers.json`, `ai_decisions.jsonl`, `events.jsonl` |
| Providers | `echo`, `mock`, `fixture`, `anthropic`, `openai`, `ollama`, `claude-cli` |
| Tests | 35 files, **284 tests, all passing** |
| Coverage | **59% overall**; ≈90% excluding the untracked `kae/` package |

### The most important state fact

**`src/cie_slim/kae/` (17 modules, ~6,020 lines, 1,741 statements) is untracked in git and has 0% test coverage.** So is `src/cie_slim/domain_packs/`.

That is roughly **45% of the Python in the working tree**, absent from the repository history entirely. It contains a second knowledge model (`knowledge_model.py`, `coverage.py`, `gap_detector.py`, `extractor.py`, `knowledge_auditor.py`, `question_planner.py`, `conversation_engine.py`).

Two consequences:

1. Anyone cloning the repository gets a materially different system from the one in this working tree.
2. The part of the codebase most relevant to KAE — it is literally named `kae/` — is the part with **no tests and no history**.

## 2. Capability status classification

| Capability | Status |
| --- | --- |
| CLI, workflow runner, session store, artifact writer | **Implemented and tested** (84–100% coverage) |
| Deterministic governor (`govern_turn`) | **Implemented and tested** — the strongest asset |
| AI interview runtime (`ai_interview.py`) | **Implemented, 92% covered, but only against `mock`/`fixture` providers** |
| Provider adapters (anthropic, openai, ollama, claude-cli) | **Implemented, weakly tested** — no live-provider test in the suite |
| Discovery model + scoring | **Implemented and tested — but the model is unsound (§4)** |
| Context/artifact generation | **Implemented; output quality unverified (§5)** |
| `kae/` knowledge model, gap detector, extractor, auditor | **Implemented, entirely untested, untracked** |
| Expert-role profiles | **Absent** — no role-profile mechanism exists |
| Concurrency / multi-client safety | **Absent** — no locking, no idempotency |
| Provenance in generated output | **Absent** (§5) |

## 3. Interview runtime — genuinely good

This contradicts the cautious prior, and the evidence is a recorded live run at `out/live/` (17 turns, 16 questions, real provider).

The questions are adaptive and context-aware. Verbatim samples:

> *"You mentioned the backend receives inputs from another system — what is that upstream system, and what kind of…"*
> *"On the downstream side, when an invoice is generated, where does it actually go — for example, is it emailed a…"*
> *"Here's a pragmatic MVP tax approach: (1) a single configurable default tax rate set in system settings…"*

Across 16 questions: **no repetition, no semantically equivalent duplicates, and zero governor warnings.** Questions reference earlier answers, offer concrete options when the user is likely unsure, and progressively narrow scope.

### The governor is the standout asset

`ai_interview.govern_turn` enforces, deterministically and without a model:

- **Verbatim grounding** — a proposed fact is rejected unless its `source_text` appears in the user's actual answer, whitespace-normalised.
- **Field validity** — rejects invented discovery fields, tolerating `data_entities.client` as `data_entities`.
- **Duplicate rejection** — string-normalised, plus optional semantic detection.
- **Frustration rejection** — refuses to echo the user's irritation back as a question.

This is a real anti-hallucination control operating on model output, and it is the single most transferable idea in the repository.

## 4. Readiness is unsound — the decisive negative finding

From the same live run, `out/live/quality_report.md` states:

> **Overall readiness: 100%** · **Status:** `ready_for_generation` · **Generation gate: Clear.** No blocking gaps — strict generation is allowed.

While the *same report* states:

> relevance: **fail** · efficiency: **fail** · aggregate **0.60**

And two areas reached 100% by vacuity:

> "integration clarity has **no required fields**; treated as clear."
> "implementation readiness has **no required fields**; treated as clear."

**Readiness is "the 7 fields marked `required: true` have been touched."** Nothing else. A project is declared ready for generation with no integration detail, no implementation detail, and with the system's own interview-quality rubric failing two of five criteria.

The interview in that run spent four of sixteen questions on integration. None of it counted, because `external_integrations` is `required: false`.

### Discovery model coverage against KAE's knowledge areas

26 fields across 10 areas. **13 of the 26 are technology picks** (`frontend_stack`, `backend_stack`, `database_choice`, `auth_strategy`, `pdf_generation_strategy`) — implementation choices, not architecture in KAE's sense. `pdf_generation_strategy` is a single project's concern promoted into the general model.

| KAE knowledge area | Slim coverage |
| --- | --- |
| Problem and value | Interviews (`product_goal`) |
| Users and stakeholders | Interviews users only; **stakeholders absent** |
| Scope and boundaries | Interviews (`mvp_features`, `deferred_features`) |
| Functional requirements | **Field only** — a feature list, no identified requirements |
| Workflows and business rules | Workflows interviewed; **business rules absent** |
| Quality attributes | **Absent** |
| Domain model and data | Interviews (`data_entities`), shallow |
| External interfaces / integrations | Interviews, but **optional and uncounted in readiness** |
| Constraints and assumptions | Constraints optional; **assumptions absent from the model** |
| Security, privacy, compliance | Partial; **compliance absent** |
| Acceptance criteria | **Absent** |
| Delivery and operations | Partial (`deployment_target`, `observability`) |
| Architecture | 13 fields, but tech-stack oriented |
| Modules and component boundaries | **One optional field** (`service_boundaries`) |
| Dependencies | **Absent** |
| Implementation phases / actionable work | **Absent** |
| Open questions | **Absent from the model** |
| Risks | **Absent** |
| Decisions | Absent from the model; a separate decision log exists |

**Seven of nineteen KAE areas have no representation at all**, and the two most load-bearing for KAE's module-level thesis — modules and dependencies — are one optional field and nothing.

## 5. Generated context — the flagship example is not generated

`examples/outputs/church_ministry_portal/` is the best-looking output in the repository: clear prose, 15 `FR-` identifiers, plausible modules.

Its own manifest says:

```json
{ "provider": "echo", "note": "Reference sample package — illustrates the ideal demo output." }
```

`echo` is the offline placeholder provider, which emits `"_Echo provider placeholder for X — run a real model to fill this in._"`. **This package is a hand-curated illustration of the intended output, not evidence of generation quality.** Treating it as a demonstration of what Slim produces would be exactly the fixture-as-evidence error.

Independently of that: **no generated document contains a single provenance reference.** Zero mentions of evidence, source, or session across `Requirements.md` and `ImplementationContext.md`. Nothing traces a statement back to what the user said. `ImplementationContext.md` names modules (`people`, `auth`, `ministries`, `events`, `scheduling`, `notifications`) with no requirement identifiers, no dependencies, no acceptance criteria, and no marking of which statements are assumptions.

Against KAE's context-package requirements, generated output supplies purpose, scope, actors, and workflows; it does not supply identified requirements with acceptance criteria, module dependencies, integration contracts, unresolved decisions carried as open, source provenance, or any instruction preventing an agent from treating a proposal as an approved fact.

## 6. Failure behaviour

Inspected in `model_client.py` and `session_store.py`.

**Handled:** missing SDK extras, missing API key, unreachable Ollama, missing `claude` binary, subprocess timeout (300 s), HTTP timeout (120 s) — all raise `RuntimeError` with a genuinely helpful remediation message. Malformed model output has a repair path (`turn_needs_repair` → `repair_ai_turn`).

**Not handled:** no retry or backoff; no rate-limit handling; no idempotency on any write; **no file locking or concurrency control** on session JSON — two processes writing one session will silently lose data; no partial-artifact rollback; corrupted session file behaviour is untested.

## 7. Documentation-to-implementation discrepancies

1. **`docs/` describes capabilities the tests do not cover.** Seven documentation packs exist (`cris_cie_slim_agent_reference_pack`, `..._claude_skills_agent_pack`, `..._interview_quality_bundle`, and others) describing agent skills and multi-agent UX with no corresponding tested implementation.
2. **The `kae/` package is undocumented in the tracked repository** and untracked in git, despite being the most KAE-relevant code present.
3. **The reference sample reads as product output** and is only disclosed as curated inside its manifest.
4. **`pyproject.toml` declares version 1.0.0** for a system whose readiness model is demonstrably unsound.

## 8. Summary judgement

Slim is a **credible interview prototype with an excellent governor and an unsound completion model**.

What works is the conversation: adaptive, grounded, non-repetitive, and defensibly validated turn by turn. What does not work is everything downstream of the conversation — a readiness score that certifies completeness on seven fields, a discovery model missing seven of KAE's nineteen areas, and generated artifacts with no provenance whose flagship example was written by hand.

The honest headline: **the acquisition front end is worth learning from; the knowledge model behind it is not suitable to become, or to feed, KAE's authoritative state.**
