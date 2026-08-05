# MCP Response Baseline — Size and Duplication

Status: **measurement**, 2026-08-03. Target T1 of `MCP_TARGET_CHECKLIST.md`.
No response contract was changed.

## 1. Scope

The six enabled MCP tools that only read:

`kae_list_projects` · `kae_get_project_briefing` · `kae_get_module_context` ·
`kae_search_knowledge` · `kae_get_open_decisions` · `kae_get_readiness`

`kae_submit_observation` is excluded. Measuring a write by performing one would
leave evidence in whatever project was measured, so the measurement harness
cannot call it and a test asserts it is absent from the tool list.

**Superseded in part, 2026-08-05.** Every tool this section listed as unbuilt
now exists: `kae_confirm_knowledge`, `kae_reject_knowledge`, and
`kae_correct_knowledge` in Phase C; `kae_get_clarifications` and
`kae_answer_clarification` in Phase D; `kae_ingest_document` and
`kae_assemble_context` in Phase E.

The measurements below were taken against the seven-tool surface and are kept
as the baseline they are — a record of what response sizes looked like before
T3 trimmed the briefing by 71%. They are not a description of the current
surface, which is fifteen tools. Re-measure before comparing.

The exclusion still holds: `kae_submit_observation` and the other writes are
not measured, because measuring a write by performing one would leave evidence
in whatever project was measured.

## 2. Measurement method

Harness: [`scripts/development/measure-mcp-responses.py`](../../scripts/development/measure-mcp-responses.py).

```bash
KAE_DATABASE_URL=... python scripts/development/measure-mcp-responses.py [project_id]
```

With no project id it measures every project in the database. It builds the same
services `kae_memory.mcp.server.build_context` wires, and calls tools through
`dispatch`, so it measures the real adapter path rather than a reconstruction.

**Token approximation.** No tokenizer is installed and none was added; the
repository has no such dependency and T1 does not justify introducing one. Two
deterministic estimates are reported:

| Estimate | Definition | Bias |
| --- | --- | --- |
| `~tok/4` | `kae_memory.domain.chunks.estimate_tokens`, i.e. `len(text) // 4` | **Under-counts JSON.** Reused because it is the repository's existing convention, so a measurement here and a chunking decision elsewhere do not disagree about what a token is |
| `~struct` | Runs of letters, runs of digits, and each punctuation mark counted separately | **Over-counts prose.** Included to show the direction of the first estimate's error |

A real count for these payloads sits between the two, nearer `~struct`, because
JSON is punctuation-dense and full of UUIDs — a UUID is one `~tok/4` unit per
nine characters but tokenizes into far more. **Treat absolute totals as
indicative and comparisons as reliable**: both estimates are deterministic, so
the same response measured before and after a change is directly comparable.

Duplication is measured structurally, not by token counting:

- `ids` — every UUID *occurrence*, in document order.
- `dup ids` — occurrences beyond the first for each identifier.
- `dup text` — distinct string values of ≥24 characters appearing more than
  once. Shorter strings repeating are usually enum values; longer ones repeating
  are usually the same fact rendered twice.

## 3. Tool-by-tool measurements

Against `kae_dev`, 2026-08-03, on the live server after restart onto `main`.

### Ministry Reporting — 10 confirmed statements, 5 of 10 areas covered

| Tool | Chars | `~tok/4` | `~struct` | Fields | Nodes | IDs | Dup IDs | Dup text |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `kae_list_projects` | 286 | 71 | 136 | 2 | 13 | 2 | 0 | 0 |
| **`kae_get_project_briefing`** | **12,199** | **3,049** | **4,315** | 12 | 423 | 27 | 4 | 24 |
| `kae_get_module_context` | 2,525 | 631 | 766 | 9 | 61 | 5 | 0 | 0 |
| `kae_search_knowledge` | 1,965 | 491 | 723 | 7 | 52 | 10 | 5 | 0 |
| `kae_get_open_decisions` | 644 | 161 | 246 | 6 | 19 | 3 | 0 | 0 |
| `kae_get_readiness` | 1,969 | 492 | 670 | 14 | 85 | 1 | 0 | 0 |

### Local test — no confirmed knowledge, 0 of 10 areas covered

| Tool | Chars | `~tok/4` | `~struct` | Fields | Nodes | Dup text |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `kae_list_projects` | 286 | 71 | 136 | 2 | 13 | 0 |
| **`kae_get_project_briefing`** | **14,108** | **3,527** | **4,626** | 12 | 497 | 34 |
| `kae_get_module_context` | 1,639 | 409 | 415 | 9 | 31 | 0 |
| `kae_search_knowledge` | 520 | 130 | 137 | 7 | 13 | 0 |
| `kae_get_open_decisions` | 533 | 133 | 190 | 6 | 15 | 0 |
| `kae_get_readiness` | 1,953 | 488 | 664 | 14 | 85 | 0 |

**The briefing is 5× the next largest response, and an order of magnitude above
the rest.** Everything else is already proportionate.

### The counter-intuitive result

**A project with no knowledge produces a *larger* briefing (14,108) than one
with ten confirmed statements (12,199).** The `sections` field of the empty
project is `[]` — two characters — yet its total is 1,909 characters higher.

The briefing scales with what is **absent**, not with what is known. Every
uncovered area generates a finding, a next step, a `missing` entry, an
`incomplete` entry, and a `missing_information` entry. A project at the start of
discovery therefore pays the most, which is exactly when an agent has the least
to gain from the response.

## 4. `kae_get_project_briefing` structural analysis

### Construction

| Layer | Symbol |
| --- | --- |
| Handler | `kae_memory.mcp.tools.kae_get_project_briefing` |
| Services | `MemoryService.get_project`, `ReadinessService.latest`/`calculate`, `ReadinessService.knowledge_revision`, `BlueprintService.generate`, `ReviewService.findings` |
| Helpers | `_readiness_explanation`, `_readiness_projection`, `_knowledge_health` |
| Rendering | The handler itself. No template layer and no generated prose |
| Queries | One project read, one readiness snapshot (recalculated when stale), one knowledge revision read, the blueprint's own reads, and the review service's single-transaction read |

Verbosity is **not** caused by duplicated database retrieval — each service is
called once. It is caused entirely by the handler rendering the same retrieved
facts into several shapes.

There is no generated prose. `status_label`, `explanation.method`, and
`projection.note` are fixed strings; every other value is counted or computed.

### By field — Ministry Reporting

| Field | Chars | Share |
| --- | ---: | ---: |
| `readiness` | 4,856 | 40% |
| `sections` | 2,595 | 21% |
| `findings` | 2,268 | 19% |
| `recommended_next_steps` | 1,347 | 11% |
| `findings_by_severity` | 479 | 4% |
| `knowledge_health` | 185 | 2% |
| `project` | 113 | 1% |
| `open_questions` | 103 | 1% |
| `complete`, `knowledge_revision`, `statement_count`, `unassigned_confirmed_count` | 10 | 0% |

### Inside `readiness`

| Sub-field | Chars | Share of `readiness` |
| --- | ---: | ---: |
| **`explanation`** | **3,847** | **79%** |
| `projection` | 422 | 9% |
| `missing_information` | 196 | 4% |
| `missing_mandatory_areas` | 71 | 1% |
| everything else | ~320 | 7% |

`readiness.explanation` alone is **32% of the entire briefing**. It renders
**15 area objects for 10 distinct areas** — 5 in `contributing`, 5 in `missing`,
5 in `incomplete` — because `incomplete` is `contributing ∪ missing` filtered to
credit < 1.0, which on a project with no partial area equals `missing` exactly.

> **Revised 2026-08-03.** That equality holds only where no area is partial.
> See §5.4: on a project with partial areas, `incomplete` carries rows that
> appear nowhere else, and is not the pure duplicate this section first
> called it.

Each area object is 232 characters across 10 fields: `area`, `name`, `state`,
`weight`, `credit`, `weight_outstanding`, `mandatory`, `confirmed_statements`,
`awaiting_review`, `confirmed_needed`.

On the empty project the same field is 5,032 characters and renders **20 area
objects for 10 areas**.

## 5. Duplication register

### 5.1 The headline: one gap, nine renderings

`Scope and boundaries has no confirmed knowledge.` — entity
`area_key=scope_and_boundaries` — appears in **nine places** in a single
response. Identical for `quality_attributes` and `domain_model_and_data`.

| # | Location | Form | Authoritative? |
| --- | --- | --- | --- |
| 1 | `findings[]` | Full object: kind, severity, summary, action, area, ids | **Yes** |
| 2 | `findings_by_severity.critical[]` | Exact summary string | No — regroups #1 |
| 3 | `recommended_next_steps[].because` | Exact summary string | No — repeats #1 |
| 4 | `recommended_next_steps[].action` | Exact `recommended_action` string | No — repeats #1 |
| 5 | `readiness.explanation.missing[]` | Full area object | **Yes** for the weights |
| 6 | `readiness.explanation.incomplete[]` | Same area object again | No — exact repeat of #5 |
| 7 | `readiness.missing_mandatory_areas[]` | Area key | No — key is in #5 |
| 8 | `readiness.missing_information[]` | Area key + name | No — both in #5 |
| 9 | `readiness.projection.requires[]` | Area key + name + weight | No — all in #5 |

Every repetition is **exact or structurally nested**, not paraphrased. Nothing
is reworded, which means every one of these is removable without losing meaning.

### 5.2 Register

| Source fact | Entity | Appears in | Repetition | Authoritative location | Could be a reference? |
| --- | --- | --- | --- | --- | --- |
| Missing-area finding | `area_key` | 9 sections (above) | Exact | `findings[]` + `explanation.missing[]` | Yes — area key |
| Finding summary | finding (no id) | `findings`, `findings_by_severity`, `next_steps.because` | Exact | `findings[]` | Yes — index |
| Recommended action | finding (no id) | `findings.recommended_action`, `next_steps.action` | Exact | `findings[]` | Yes — index |
| Area weights and counts | `area_key` | `explanation.contributing`/`missing`/`incomplete` | Exact, nested | `explanation` (one list) | Yes — `state` flag |
| Open-question knowledge ids | `04fb6ac3…`, `2c13d899…` | 3 findings each | Exact | `findings[].knowledge_ids` | Already ids |
| Area key + name | `area_key` | `missing_mandatory_areas`, `missing_information`, `projection.requires`, `explanation.missing` | Exact | `explanation.missing[]` | Yes — key only |

**Statement bodies are not duplicated.** Each confirmed statement's text appears
exactly once, in `sections`. A test pins this, because if a later change starts
echoing statement bodies the briefing would begin growing with the corpus rather
than with the template — a far worse scaling property than today's.

### 5.3 Measured redundancy

| Removable payload | Chars | Share |
| --- | ---: | ---: |
| `recommended_next_steps` (actions and summaries already in `findings`) | 1,347 | 11% |
| `explanation.incomplete` (identical to `missing` here) | 1,199 | 9% |
| `findings_by_severity` (summaries already in `findings`) | 479 | 3% |
| `readiness.missing_information` (areas already in `missing_mandatory_areas`) | 196 | 1% |
| **Total** | **3,221** | **26%** |

**Roughly a quarter of the briefing is the same facts rendered again.** This
counts only exact duplicates; it excludes the deeper question of whether
`explanation` needs ten-field objects for every area.

### 5.4 Revision — measured against a project with partial areas

T1 recorded that 26% was a floor because neither measured project had a partial
area. **KAE-Memory**, registered 2026-08-03, has six. Re-measuring changed two
conclusions, one in each direction.

| | Ministry Reporting | Local test | **KAE-Memory** |
| --- | ---: | ---: | ---: |
| Partial areas | 0 | 0 | **6** |
| Confirmed statements | 10 | 0 | **0** |
| Briefing chars | 12,199 | 14,108 | **13,535** |
| `missing` / `incomplete` rows | 5 / 5 | 10 / 10 | **4 / 10** |
| Identical? | yes | yes | **no** |
| Measured redundancy | 26% | — | **30%** |

**`explanation.incomplete` is not pure duplication.** Six of its ten rows —
every partial area — appear in neither `contributing` as complete nor in
`missing`. Only four repeat `missing`, costing 967 characters (7%) rather than
the 1,199 (9%) measured before. The §7 recommendation to drop the field outright
was wrong; it should be **merged into a single `areas` list keyed on `state`**,
which removes the repetition without losing the partial rows.

**Total redundancy rose rather than fell.** 26% → **30%**, for a reason T1 did
not anticipate: partial areas generate *more findings*, and
`recommended_next_steps` scales with them — 1,855 characters here (13%) against
1,347 (11%). The floor claim was right; the mechanism was not the one predicted.

**The scaling result is now firmer.** 13,535 characters — about 3,383 tokens —
for a project holding **zero confirmed statements**. `sections` is empty. The
entire payload describes what is absent.

## 6. Field classification

Against the six questions a default briefing should answer: what project, what
state, what is blocking, what is incomplete, what to examine next, which ids to
retrieve.

### `essential-default`

| Field | Answers |
| --- | --- |
| `project` | What project is this |
| `readiness.percentage`, `.status`, `.status_label` | What is its current state |
| `readiness.missing_mandatory_areas` | What areas are incomplete |
| `findings` (severity, summary, action, area, ids) | What is blocking, what to do next, which ids |
| `knowledge_health` | State in one object, 185 chars — the best value-per-character in the response |
| `open_questions` | Human-owned blockers |
| `knowledge_revision` | Staleness checking |
| `statement_count`, `complete` | Cheap scalars |

### `useful-on-request`

| Field | Why not default |
| --- | --- |
| `sections` | 21% of the response. An agent orienting needs the *shape*; the statements themselves are a follow-up read |
| `readiness.explanation` | 32%. Justifies the number, needed when the number is challenged, not to answer "what state is this in" |
| `readiness.projection` | Planning, not orientation |

### `duplicated`

`findings_by_severity` · `recommended_next_steps` · `readiness.missing_information` ·
`readiness.explanation.incomplete`

### `diagnostic-only`

`readiness.explanation.method` · `readiness.projection.note` ·
`explanation` per-area `weight`, `credit`, `weight_outstanding` — arithmetic
provenance, valuable when auditing a score and noise otherwise.

### `candidate-for-removal`

`unassigned_confirmed_count` — 1 character, but it duplicates what the
`unclassified_knowledge` finding already reports with more context.

## 7. Highest-cost sections

Ranked by chars removable per unit of meaning lost:

1. **`readiness.explanation` → on request** — 3,847 chars, 32%. Nothing else
   comes close.
2. **`recommended_next_steps` → drop** — 1,347 chars, 11%. Both fields already
   exist in `findings`, which is already severity-ordered.
3. **`explanation.incomplete` → merge into one `areas` list** — 967 chars, 7%
   of the repetition on a project with partial areas (§5.4). **Not a drop:** it
   carries partial areas that appear in no other list. Collapsing
   `contributing` / `missing` / `incomplete` into one list keyed on `state`
   removes the overlap and keeps every row.
4. **`sections` → on request or summarise** — 2,595 chars, 21%. The only field
   that grows with the corpus, so it matters most as projects get real.
5. **`findings_by_severity` → drop** — 479 chars, 3%. `findings` carries
   `severity` and is already ordered.

Items 2, 3, and 5 together remove **3,025 characters, 25%, with no information
loss at all** — every value survives in `findings` or `explanation.missing`.

## 8. Recommended boundaries for T2

1. **Define a detail level** — `summary` (default) / `full`. Move `sections`,
   `explanation`, and `projection` behind `full`. This is the single change with
   the largest effect.
2. **One rendering per fact.** Where a value exists in a structured list, other
   sections reference it by key or index rather than restating it.
3. **Collapse `contributing`/`missing`/`incomplete` into one `areas` list** with
   the `state` and `credit` already on each object.
4. **Keep every honesty field.** `warnings`, `search_mode`,
   `semantic_search_available`, `caveat`, `guidance`, `scope_note`, and the
   capability-gap fields are content, not overhead. They are why a response can
   be trusted, and T2 must not treat them as compressible.
5. **Do not compress `findings`.** It is the authoritative rendering and the
   most useful field per character after `knowledge_health`.
6. **Leave the other five tools alone.** All are ≤2,525 characters. Pagination
   (T4) is worth defining for `search` and `sections` but is not urgent for any
   response measured here.

## 9. Risks and unresolved questions

- **The token estimates are approximations.** Both are deterministic and
  comparable across runs, but neither is a real tokenizer count.
  **Decided 2026-08-03:** adopt one tokenizer implementation before making any
  quantitative reduction claim. Until then every token figure in this document
  is an estimate and must be described as one. If T5 reports a percentage
  before standardisation, it must name the estimator and use it on both sides.
- **~~Two projects is a small sample~~** — partially resolved. A third project
  with partial areas was measured (§5.4) and confirmed 26% was a floor, at
  30%. Still unmeasured: an open blocker, a recorded contradiction, and any
  project above 10 statements.
- **No project here has more than 10 statements.** `sections` is the only field
  that grows with the corpus; on a project with 200 confirmed statements it
  would dominate, and the ranking in §7 would change. Worth re-measuring against
  a large project before T3 concludes.
- **~~Removing `recommended_next_steps` is a contract change~~** — resolved
  2026-08-03. A repository search found it produced only by `mcp/tools.py` and
  consumed only by its own tests; absent from the frontend, `openapi.json`, and
  the HTTP API. **No external consumers: T3 may remove it.**
- **`module_scope_available`, `scope_note`, and the capability-gap fields look
  like overhead to a size pass.** They are the opposite: they exist so a caller
  cannot mistake a project figure for a module answer. Any compression that
  removes them fails the honesty rule that governs this whole surface.
