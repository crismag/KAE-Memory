# MCP Response Policy — Profiles, Controls, and Configuration

Status: **proposed design**, 2026-08-03. Target T1B of
`../09_development/MCP_TARGET_CHECKLIST.md`. No implementation is authorised;
T2 begins after this is reviewed.

Design authority for how KAE MCP surfaces decide *how much* to return. Grounded
in the measurements in [`../09_development/MCP_RESPONSE_BASELINE.md`](../09_development/MCP_RESPONSE_BASELINE.md).

Covers: response profiles · prose policy · detail levels · budget controls ·
retrieval controls · configuration hierarchy · per-tool applicability · Studio
requirements · future surfaces.

---

## 1. Where this has to live

### What exists today

| Concern | Current state |
| --- | --- |
| Tool handlers | `kae_memory.mcp.tools` — seven functions returning `dict[str, Any]` |
| Serialisers / DTOs | **None for MCP.** Handlers build dicts inline |
| Response mappers | **None** |
| Rendering layer | **None.** The handler *is* the renderer |
| Single choke point | `kae_memory.mcp.server.dispatch` — every call and every error routes through it |
| Per-request options | Only on `kae_search_knowledge`: `limit`, `kinds`, `mode`, `diagnostics` |
| Process configuration | `ToolContext`, built once in `server.build_context` |
| Declared input schemas | `server.TOOL_DEFINITIONS` |

The HTTP API has 28 Pydantic schemas in `kae_memory.api.schemas`. **MCP uses none
of them.** There is no shared DTO layer, so there is currently no single place a
policy could be enforced.

### Two facts that decide the design

**T1 found that verbosity is a rendering problem, not a retrieval problem.**
Every service is called exactly once per briefing; the handler renders retrieved
facts into several shapes. So the control belongs in a rendering layer — and
that layer does not exist yet. Creating it is the substance of T2.

**`diagnostics` is already a detail level in disguise.** `kae_search_knowledge`
moves vector internals behind a boolean. That precedent should be generalised,
not duplicated six more times.

### Recommended location

> **A response-projection step in `dispatch`, applied to a payload the handler
> built at full detail.**

```
client request
   ↓
dispatch  ── resolve ResponsePolicy (§7) ──┐
   ↓                                       │
handler (renders authoritative payload)    │
   ↓                                       │
project(payload, policy)  ←────────────────┘
   ↓
client response
```

Rationale, and the cost of it:

- **One place, not seven.** Four controls across seven tools is twenty-eight
  opportunities to diverge if handlers enforce policy themselves.
- **Handlers stay authoritative.** A handler's job is to render everything it
  can support. Deciding what a *caller* can afford is a different concern and
  belongs to a different layer.
- **`dispatch` already owns the cross-cutting concern** of turning any outcome
  into a structured payload.
- **It saves tokens, not database work.** A projection at `dispatch` cannot
  un-run a query. For the briefing this mostly does not matter —
  `explanation` is computed from a snapshot already fetched — but `sections`
  comes from `BlueprintService.generate`, which is real work. Treat push-down as
  a **second phase**, added only where measurement shows the query cost matters
  (§10).

---

## 2. The rule that constrains everything else

> **A profile may reduce what a response says. It may never reduce what a
> response admits.**

KAE's MCP surface is sold on not claiming more than it can support. Fields that
exist to prevent a caller from over-trusting a result are **integrity fields**,
and no profile, budget, or prose setting may remove, shorten past their canonical
short form, or make them conditional.

### The integrity floor

| Field | Tool | Why it cannot be dropped |
| --- | --- | --- |
| `warnings` | search, assembly | States that a conceptual query cannot be served |
| `search_mode`, `semantic_search_available` | search | A term match read as a semantic one is a wrong answer |
| `ranking` | search | Says which signal ordered the results |
| `caveat` | module context | "A term match is not module membership" |
| `guidance` | capability errors, open decisions | "Do not infer the missing information" |
| `error`, `capability`, `missing_capabilities` | capability errors | The gap itself |
| `scope_note`, `module_scope_available` | readiness | Stops a project figure reading as a module answer |
| `confirmation_state`, `unresolved_critical_gaps` | assembly (T21) | Never empty-by-omission, per `KAE_PACKAGE_MODEL.md` §1 |
| `source_knowledge` | assembly (T21) | An artifact that cannot name what it read cannot be invalidated |
| `label` on statements | briefing, assembly | Grounded vs assumption |
| `truncation` | any budgeted response | What this response left out (§6) |

**The cheapest profile must not be the least honest one.** An Economy response
that omitted `semantic_search_available` would cost fewer tokens and mislead the
agent reading it — a worse outcome than spending the tokens. This is the single
constraint T2 must not trade away under size pressure.

---

## 3. Three axes, not two

The target named two axes. The measurements imply a third, which is the reason
§2 exists.

| Axis | Controls | Range |
| --- | --- | --- |
| **Detail** | Which facts appear | `minimal` → `full` |
| **Prose** | How explanatory strings are worded | `none` → `standard` |
| **Integrity** | What must always appear | **Not an axis.** Fixed floor |

Detail and prose are independent: `detail=full, prose=none` is a legitimate
request for every fact with no explanation, and `detail=minimal, prose=standard`
is legitimate for a human-facing preview.

---

## 4. Detail levels

Controls **factual coverage**. Each level is a superset of the one above.

**Settled 2026-08-03: three levels, `summary` / `standard` / `diagnostic`.**
The earlier four-level proposal is withdrawn; do not reintroduce competing
names.

| Level | Intent | Consumer | Briefing carries |
| --- | --- | --- | --- |
| `summary` | **Default.** Answers the six briefing questions | Agent about to plan work | `project`, readiness figures, `knowledge_health`, `findings`, `missing_mandatory_areas`, `open_questions`, counts |
| `standard` | Adds the knowledge itself | Agent about to write or review | Above, plus `sections` |
| `diagnostic` | Adds justification and arithmetic | Auditing a score; debugging a package | Above, plus `readiness.explanation`, `readiness.projection` |

Derived from T1's classification. `summary` is the default because it answers
all six questions — what project, what state, what is blocking, what is
incomplete, what to examine next, which ids to retrieve — while leaving out the
32% (`explanation`) and 21% (`sections`) that answer none of them.

**Rule: a lower detail level omits whole fields.** It never returns a partial
object, a truncated list without a count, or a shortened statement body.

---

## 5. Prose policy

Controls **wording of explanatory strings only**. Three categories, and the
distinction between them is the whole design:

| Category | Examples | Prose may |
| --- | --- | --- |
| **Explanatory** | `explanation.method`, `projection.note`, `status_label` | Shorten or omit |
| **Integrity statements** | `warnings[]`, `caveat`, `guidance`, `scope_note` | Shorten to a registered short form — **never omit** |
| **Data** | Statement text, finding `summary`, `recommended_action` | **Never rewritten.** These are content |

| Level | Explanatory | Integrity | Intent |
| --- | --- | --- | --- |
| `none` | Omitted | Canonical short form | Machine consumer that will never surface text |
| `minimal` | Omitted | Short form | Cost-sensitive agent |
| `concise` | **Default.** One clause | Short form | Balanced |
| `standard` | Current full wording | Full wording | Human-facing, Studio preview |

Short forms must be a **registered table**, not runtime summarisation. Generating
the short version of a warning with a model would make the guarantee
non-deterministic, and an integrity statement that varies is not a guarantee.

Illustrative (T2 owns the real registry):

| Full | Short |
| --- | --- |
| "Semantic ranking is unavailable because no semantic embedding model is configured. Matched on query terms instead, so conceptual queries that share no wording with the stored text will not be found." | "Lexical match only; no semantic model configured." |
| "These statements match the wording of the requested name. That is a term match, not module membership — no record of which knowledge belongs to this module exists in this version." | "Term match, not module membership." |

**Prose never changes truth value.** If `prose=none` cannot express a warning,
the warning wins and the prose setting is overridden for that field.

---

## 6. Budget controls

| Control | Configurable | Server-enforced | Deterministic |
| --- | --- | --- | --- |
| `max_output_tokens` | Yes | Yes — clamped to a server maximum | Estimated (§6.1) |
| `max_entities` (per list) | Yes | Yes | Exact |
| `max_text_length` (per statement) | Yes | Yes | Exact |
| `max_evidence` (provenance per item) | Yes | Yes | Exact |
| `relationship_depth` | Yes | Yes | Exact — fixed at 0 until traversal exists |
| `history_depth` (versions per item) | Yes | Yes | Exact |
| `page_size` / `cursor` | Yes | Yes | Exact |

### 6.1 Estimating tokens

Reuse T1's method: `kae_memory.domain.chunks.estimate_tokens` as the primary
estimate, with the documented caveat that it under-counts JSON. Budgets must be
**advisory ceilings with margin**, not exact contracts, and the estimator used
must be named in the response.

Do not add a tokenizer dependency for this. If exactness later matters, that is
its own target with its own justification.

### 6.2 Graceful degradation

A response over budget **drops whole units in a fixed order** and says so. It
never truncates a structure into something that will not parse or, worse, parses
into a false claim.

Drop order, first dropped first:

1. `readiness.projection`
2. `readiness.explanation`
3. `sections` statement bodies → identifiers plus kind and area
4. `sections` entirely
5. `findings[].knowledge_ids` tails, keeping a count
6. `findings` tail beyond severity order, keeping a count

**Never dropped**, at any budget: everything in §2, plus `project`,
`readiness.percentage`/`status`, and `knowledge_revision`.

> **Settled 2026-08-03.** Integrity takes precedence over a requested budget.
> Return the smallest context satisfying the floor; if that exceeds the
> budget, report the overage and explain why. Never truncate silently to fit.
> A budget is a request; honesty is not.

Every degraded response carries:

```json
"truncation": {
  "applied": true,
  "dropped": ["readiness.explanation", "sections"],
  "reason": "max_output_tokens=800, estimated 3049",
  "retrieve_with": {
    "readiness.explanation": "kae_get_readiness",
    "sections": "kae_search_knowledge or kae_get_project_briefing detail=detailed"
  }
}
```

`retrieve_with` is what makes truncation recoverable rather than lossy: the
caller learns both that something is missing and how to get it. **Silent
truncation is prohibited** — the same rule the ingestion policy already follows
for `max_chunks`.

---

## 7. Response profiles

Presets that resolve into explicit values. A profile is never itself a runtime
behaviour; it expands at resolution time, and the resolved values appear in the
response so a caller can see what it got.

| | `economy` | `regular` (default) | `detailed` | `custom` |
| --- | --- | --- | --- | --- |
| `detail` | `summary` | `summary` | `standard` | explicit |
| `prose` | `none` | `concise` | `standard` | explicit |
| `max_output_tokens` | 800 | 2,500 | 8,000 | explicit |
| `max_entities` | 10 | 25 | 100 | explicit |
| `max_text_length` | 200 | none | none | explicit |
| `history_depth` | 1 | 1 | 3 | explicit |
| Briefing ≈ tokens | ~250 | ~900 | ~2,400 | — |
| Intent | Sweeps, cheap clients, tight windows | Everyday agent work | Review, audit, package generation | Deliberate tuning |
| Trade-off | No statement bodies; no arithmetic | No arithmetic | Cost | Caller owns the outcome |

Briefing estimates are projections from the T1 field breakdown, not
measurements. **T5 must verify them**; if `regular` does not land near a
70% reduction the profile values are wrong, not the measurement.

`regular` is the default because T1's classification shows `summary` detail
answers all six briefing questions. Defaulting to `economy` would make the
common case lossy; defaulting to `detailed` keeps the problem T1 measured.

---

## 8. Retrieval controls

Distinct from response shaping: these change **what is searched**, not what is
returned.

| Control | Tier | Default | Notes |
| --- | --- | --- | --- |
| `similarity_threshold` | Per-tool, per-request | `MAX_DISTANCE` (0.75) | Exists. Per-request override should be **clamped, never widened** past the server maximum, or a caller can defeat relevance filtering |
| `min_coverage` (lexical) | Per-tool | `MIN_COVERAGE` (0.5) | Exists |
| `limit` | Per-request | 8 | Exists |
| `kinds` | Per-request | all | Exists |
| `include_proposed` | Per-request | `false` | Exists on assembly. **Must always be reported when true** |
| `include_rejected` | Per-request | `false` | New. Audit only |
| `include_superseded` | Per-request | `false` | New. Audit only |
| `relationship_depth` | Global | 0 | Reserved. No traversal exists |
| `archived_projects` | Global | excluded | — |

**Lifecycle inclusion is never silent.** A response containing proposed,
rejected, or superseded knowledge must say so and label each item, or a caller
cannot distinguish what the project believes from what it considered.

---

## 9. Configuration hierarchy

```
System  →  Project  →  Client  →  Session  →  Per-request
(lowest precedence)                          (highest)
```

Resolution: start from system defaults, apply each tier in order, **clamp the
result to server maximums**, then apply the integrity floor unconditionally.

### Tier feasibility — read before designing storage

| Tier | Source | Available today? |
| --- | --- | --- |
| System | `KAE_MCP_*` environment, read in `build_context` | **Yes.** Follows the existing `KAE_INGEST_*` pattern |
| Project | Per-project stored settings | **No.** `projects` has no settings column — needs a migration |
| Client | Client identity | **Not for stdio.** One server process per client, so this collapses into System. Only meaningful for a future HTTP/SSE transport |
| Session | Per-session stored settings | **No.** `sessions` has no settings column — needs a migration |
| Per-request | Tool arguments in `TOOL_DEFINITIONS` | **Yes.** `kae_search_knowledge` already does this |

**Recommendation: implement System and Per-request only.** They cover the real
cases, require no schema change, and match how the repository already configures
the worker and ingestion. Project and Session tiers should wait for a demonstrated
need — a stored setting nobody sets is a migration and a precedence rule bought
for nothing.

### Never overridable by a client

1. Anything in the **integrity floor** (§2).
2. **Server maximums.** A client may request less than the cap, never more —
   `max_output_tokens`, `max_entities`, `limit`, `page_size`.
3. **Relevance thresholds in the widening direction.** A client may demand a
   *stricter* similarity threshold; it may not loosen one past the server value
   and reintroduce the defect T1's predecessor fixed.
4. **Lifecycle inclusion without labelling.** `include_rejected` may be set;
   suppressing the resulting labels may not.
5. **Project scoping.** No control crosses a project boundary.

Validation: an unknown profile name, an out-of-range value, or an unknown
control is an `invalid_argument` error naming the valid values — the existing
behaviour for `mode` and `kinds`. Silently ignoring an unrecognised control
would let a caller believe a budget applied when it did not.

---

## 10. Per-tool applicability

| Tool | Detail | Prose | Budget | Pagination | Notes |
| --- | --- | --- | --- | --- | --- |
| `kae_list_projects` | Low value | Low value | Low value | **Yes** | 286 chars today. Pagination matters only at many projects |
| `kae_get_project_briefing` | **Primary** | **Primary** | **Primary** | Within `sections` | The whole reason this design exists |
| `kae_get_module_context` | Low value | Yes | Low value | `available_now` list | 2,525 chars, mostly the integrity floor. **Little to trim** |
| `kae_search_knowledge` | Yes (`diagnostics` already) | Yes | Yes | **Yes** — grows with `limit` | Generalise `diagnostics` into `detail` |
| `kae_get_open_decisions` | Low value | Yes | Low value | Yes | 644 chars. Already compact |
| `kae_get_readiness` | Yes | Yes | Low value | No | `areas` is a fixed 10 |
| `kae_submit_observation` | **N/A** | Yes | **N/A** | N/A | A write. Its response is a receipt; never budget a receipt |

**Only the briefing and search need the full model.** Applying every control to
every tool would add surface area to five responses that are already
proportionate — T1 measured all of them at ≤2,525 characters. Say so explicitly
so T4 does not over-build.

---

## 11. Studio integration requirements

UI is out of scope. Requirements only.

**Default view.** One control: profile as four options — Economy, Regular,
Detailed, Custom — with the resolved values shown as read-only text beneath, so
choosing a preset teaches what it means.

**Advanced, collapsed by default.** Detail, prose, `max_output_tokens`,
`max_entities`, pagination. Visible only when Custom is chosen or Advanced is
expanded.

**Never exposed as switches.** The integrity floor. Studio must not render a
control that appears to turn off warnings, caveats, or capability reporting,
even disabled — a greyed-out "hide warnings" toggle teaches that hiding them is
a thing KAE does.

**Must show.** Estimated tokens per profile for the current project, computed
from the same estimator the server uses; and a preview of what a lower profile
would omit, expressed as field names rather than a diff.

**Authority.** Studio never computes a resolved policy. It sends a profile plus
overrides and displays what the server resolved, for the same reason it does not
compute readiness (`ADR-0020`).

---

## 12. Future surfaces

Applicability for the tools Phases C to E will add.

| Tool | Detail | Budget | Pagination | Specific requirement |
| --- | --- | --- | --- | --- |
| `kae_ingest_document` | N/A | N/A | N/A | Write. `IngestionPolicy` already governs depth/extent/breadth — **do not duplicate those controls here**; reference them |
| `kae_get_clarifications` | Yes | Yes | **Yes** | Question lists grow without bound |
| `kae_answer_clarification` | N/A | N/A | N/A | Write. Receipt only |
| `kae_confirm_knowledge` / `kae_reject_knowledge` / `kae_correct_knowledge` | N/A | N/A | N/A | Writes. Receipts carry the resulting lifecycle and revision — never budgeted |
| `kae_assemble_context` | **Yes** | **Yes** | Within sections | **Highest risk.** An assembly is deliberately large; the manifest's integrity fields are floor and the budget must degrade *content*, never the manifest |
| Blueprint generation | Yes | Yes | Yes | Same shape as briefing |

**Two rules for future surfaces:**

1. **Writes are never budgeted.** A receipt tells a caller what happened. Trimming
   it to save tokens loses the outcome of a mutation, which no saving justifies.
2. **A tool with its own domain policy does not get a second one.** Ingestion
   already has `IngestionPolicy`; response policy governs the *response*, not the
   work.

---

## 13. Implementation guidance for T2 onward

**T2 — conventions and the projection layer.** Define `ResponsePolicy` as a
frozen dataclass with `from_environment` and `from_arguments`, matching
`IngestionPolicy` / `policy_from_environment`. Define the integrity-floor
registry and the prose short-form registry as data, not code paths. Define the
projection function signature. Write no trimming yet.

**T3 — the briefing.** Apply detail levels to the briefing only. Remove the
exact duplicates T1 measured — `recommended_next_steps`, `explanation.incomplete`,
`findings_by_severity` — which is a 25% reduction with no information loss and
does not need the profile machinery. Then put `explanation`, `projection`, and
`sections` behind detail levels.

**T4 — the rest.** Pagination for `kae_search_knowledge` and `kae_list_projects`.
Generalise `diagnostics` into `detail`. Leave the three already-compact tools
alone.

**T5 — verification.** Re-run `scripts/development/measure-mcp-responses.py` and
compare against the T1 baseline with the same estimator. Add a test that the
integrity floor survives at `economy` with `max_output_tokens` set below the
floor's own size — the case most likely to be got wrong.

**Order matters.** T3's duplicate removal is independent of the profile
machinery and delivers a quarter of the win on its own. If T2 stalls on design
review, T3's first half can still proceed.

---

## 14. Open questions

Reviewed 2026-08-03. Most are closed; what remains is listed as such.

**Settled**

- **Detail-level names** — three levels, `summary` / `standard` / `diagnostic` (§4).
- **Integrity floor vs budget** — integrity wins; report the overage (§6.2).

**Deferred — not blockers**

- **Project and Session configuration tiers.** Current usage does not justify a
  migration. Retain System and Per-request only; revisit when Studio produces a
  real requirement.
- **Per-tool vs per-call detail.** One consistent model is sufficient. Optimise
  later only if justified.
- **Profiles nameable per project.** Follows the tier decision above.

**Open**

1. **Does the default profile land near its projected reduction?** §7's
   per-profile figures are projections from T1 field shares, not measurements.
   T5 decides, using one estimator consistently.
2. **`recommended_next_steps`** — **closed 2026-08-03: remove.** A repository
   search found it produced only by `mcp/tools.py` and consumed only by its own
   tests. Not in the frontend, `openapi.json`, or the HTTP API. T3 may drop it.

## 15. Risks

- **Size pressure erodes honesty.** The integrity floor is a rule, not a
  mechanism, until T2 makes it a registry with a test. Between now and then it
  is only as strong as whoever is reviewing.
- **Projection at `dispatch` saves tokens, not queries.** A caller asking for
  `economy` still costs the server a full briefing computation. Acceptable now;
  it will not be at scale, and push-down is a real second phase rather than a
  refinement.
- **Estimated budgets will be wrong in both directions.** `estimate_tokens`
  under-counts JSON, so a budget may be honoured on paper and exceeded in fact.
  Margin, and naming the estimator in the response, are the mitigation.
- **Four profiles invite a fifth.** Each is a maintained combination. Adding one
  should require showing a real caller the existing four fail.
- **Custom profiles make responses irreproducible** unless the resolved values
  ship in the response. They must.
- **The design assumes stdio.** An HTTP/SSE transport makes the Client tier real
  and adds authorisation questions this document does not answer.
