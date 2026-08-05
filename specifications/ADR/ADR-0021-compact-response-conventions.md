# ADR-0021 — Compact Response Conventions

Status: **proposed**, 2026-08-03. **No implementation authorised.** Target
**T2B** (`../09_development/MCP_TARGET_CHECKLIST.md`).

Companion to `MCP_RESPONSE_POLICY.md`, which defines *how much* a response
returns. This defines *how it is shaped*, regardless of profile.

---

## Relationship to T2 as shipped

T2 was completed on 2026-08-03 and delivered the **mechanism**: detail levels,
profiles, budgets, the integrity registry, and the projection in
`mcp/response_policy.py`. This document is the **style half** — naming, nulls,
ordering, references over embedded objects — which the mechanism does not
address. Recorded as **T2B** rather than reopening T2, so the shipped work keeps
its identifier.

Two corrections to the brief that produced this document, both against
decisions already taken:

**There are three detail levels, not four.** `summary` / `standard` /
`diagnostic`. `minimal` was proposed, then withdrawn on 2026-08-03 — *"Do not
continue supporting competing naming schemes"* — and three are implemented and
tested. This document assumes three.

**`ResponseProfile` and `DetailLevel` are different things.** Profiles are
`economy` / `regular` / `detailed` / `custom` and resolve *into* a detail level.
Conflating them is why the brief lists four "profiles" that are levels.

---

## Context

T1 measured where tokens go: repeated facts, regrouped renderings, and objects
returned where an identifier would serve. T3 removed the worst of it from the
briefing — 71%. What remains is the absence of a *convention*, so each new tool
re-decides naming, nulls, and nesting, and the next surface drifts again.

## Decision

Fifteen rules, of which **thirteen are adopted as written, one is adopted with a
carve-out, and one is rejected.** The two exceptions are the substance of this
ADR; a convention that quietly contradicts the integrity floor would trade the
property this surface is sold on for tokens.

---

## Adopted

### 1. Responses are data, not documentation
No narrative framing. `{"observations": [...]}`, never *"The following
observations were found"*.

### 2. Never repeat project information
Identifiers only. **Exception:** a tool whose subject *is* the project may carry
`name` and `key` once at the top — a caller holding a UUID and no name cannot
render anything a person will read, and the alternative is a second call on
every turn. `kae_get_project_briefing` keeps its three-field `project` object;
nothing repeats it deeper in the payload.

### 3. Prefer IDs over embedded objects
Return `knowledge_id`, not a knowledge object, wherever a read tool can expand
it. **Exception:** a statement's `text` in search results — the whole point of
the call is the text, and an id-only result would force a second call per hit.

### 4. Eliminate duplicated summaries
Include a count only when it saves downstream work. A count over a list the
caller already holds does not.

### 5. Stable naming
`project_id`, `knowledge_id`, `observation_id`, `clarification_id`, `module_id`.
Never `id`, `projectId`, or `project_identifier`. One field, one meaning, every
tool.

### 6. Compact enums
`confirmed`, `pending`, `rejected`. Not `knowledge_confirmation_status`.

### 7. Arrays over verbose wrappers
A bare array when there is no metadata; a wrapper only when `total`, `page`, or
a cursor must travel with it. **In practice most KAE reads need the wrapper**,
because integrity fields travel alongside results.

### 8. Metadata at the top
`{"total": 20, "results": [...]}` — never per-item metadata repeating a
collection-level fact.

### 9. References instead of duplication
Where another tool retrieves the detail, return `clarification_ids`.

### 11. Consistent timestamps
ISO-8601, UTC, always. Currently **no MCP response carries a timestamp at all**,
so this binds new fields rather than correcting old ones.

### 12. Omit null values
Never `"description": null`. Omit the field.

### 13. Omit empty collections — **with a carve-out**
Omit `"errors": []`. **Do not omit a collection whose emptiness is a claim.**
`confirmation_state` and `unresolved_critical_gaps` are required to be present
even when empty (`KAE_PACKAGE_MODEL.md` §1) precisely so that absence cannot be
read as "nothing outstanding". The rule is: omit when empty means *nothing to
say*; keep when empty means *we checked and found none*.

### 14. Deterministic ordering
`id` → `type` → `status` → `timestamps` → `references` → `payload`, then
integrity fields last. Stable across calls, which makes diffs meaningful.

### 15. No duplicated derived information
If `percentage` is returned, do not also return the counts it was computed from
unless the caller asked. Counts move to `diagnostic`.

---

## Adopted with a carve-out: Rule 10

> **Rejected as written:** "Avoid natural-language explanations. Machine first."

Adopted for *explanatory* prose. **Rejected for integrity statements.**

`warnings`, `guidance`, `caveat`, `scope_note`, and the capability-gap fields are
natural-language and are the reason a caller can trust the surface. They say what
a response did *not* do:

> Semantic ranking is unavailable… conceptual queries that share no wording with
> the stored text will not be found.

There is no machine-readable form that carries that. A flag says *whether*;
only prose says *what it means for the answer you are holding*. An agent reading
`semantic: false` may still treat a term match as semantic; an agent reading the
sentence cannot.

**The reconciliation already exists.** `ProseLevel` shortens registered
statements to a fixed short form — *"Lexical match only; no semantic model
configured."* Machine-first is achieved by shortening from a table, never by
removal, and never by runtime summarisation, which would make the guarantee
non-deterministic.

> **Rule 10 as amended:** no narrative framing, no explanatory prose below
> `standard`. Integrity statements shorten to their registered form and are
> never omitted.

---

## Compliance checklist

Every MCP tool must satisfy:

- [ ] Identifiers follow the `<entity>_id` convention
- [ ] No project metadata repeated below the top level
- [ ] References, not embedded objects, where a read tool can expand
- [ ] Compact enum values
- [ ] Deterministic field ordering
- [ ] Nulls omitted
- [ ] Empty collections omitted **unless emptiness is a claim**
- [ ] No derived value returned beside its inputs
- [ ] Timestamps ISO-8601 UTC
- [ ] Integrity fields present at every profile
- [ ] Explanatory prose gated on prose level; integrity prose shortened, not dropped
- [ ] Collection metadata at the top, never per item
- [ ] Response projected through `response_policy.project`

---

## Tool audit

Measured against `kae_dev`, 2026-08-03.

| Tool | Verdict | Required changes |
| --- | --- | --- |
| `kae_list_projects` | **Partial** | `count` duplicates `len(projects)` (rule 4). Each entry uses `project_id` correctly |
| `kae_create_project` | **Partial** | Returns `knowledge_statements: null` on the idempotent path — must be omitted (rule 12) |
| `kae_get_project_briefing` | **Compliant** | Post-T3. `project` object retained under the rule 2 exception; no repetition below it |
| `kae_get_readiness` | **Partial** | Returns `percentage` alongside per-area `confirmed`/`proposed` counts (rule 15) — move counts to `diagnostic`. No detail levels yet (T4) |
| `kae_search_knowledge` | **Partial** | `count` is chunk-level and unlabelled — split into `matched_chunks` / `matched_knowledge_items` (rules 4, 5). `why` is explanatory prose needing a prose gate |
| `kae_get_open_decisions` | **Partial** | Emits `findings: []` and `open_knowledge: []` (rule 13) — but see the carve-out: an empty `findings` here *is* a claim that nothing is unresolved, so keep it and document why |
| `kae_get_module_context` | **Compliant** | Error payload is entirely integrity fields; `available_now` carries its caveat correctly |
| `kae_submit_observation` | **Partial** | `note` is explanatory prose stating nothing was confirmed — an integrity statement; needs registering in `SHORT_FORMS` rather than a prose gate |

**No tool is non-compliant.** Nothing embeds a full object where an id would do,
and no naming collisions exist — `project_id` and `knowledge_id` are used
consistently throughout.

---

## Coordination with T4

Four items must be decided here so T4 does not revisit structure:

1. **Wrapper shape is fixed now.** `{total, page, cursor, results}` at the top.
   T4 populates it; it does not design it.
2. **`count` splits into `matched_chunks` / `matched_knowledge_items`** — a
   naming change (rule 5) that T4's pagination fields must not conflict with.
3. **Per-area counts move to `diagnostic`** (rule 15), which is a detail-level
   assignment and belongs in T4's field map, not a separate edit.
4. **`why` and `note` need prose treatment.** `why` is explanatory and gates on
   prose level; `note` is an integrity statement and needs a registered short
   form. Deciding which is which now avoids T4 gating an integrity field.

---

## Consequences

**Breaking changes**, all justified and none silent:

| Change | Justification |
| --- | --- |
| `count` → `matched_chunks` + `matched_knowledge_items` | The current field is chunk-level and reads as item-level; already wrong for multi-chunk statements |
| Per-area counts move to `diagnostic` | Derived from data already returned |
| `knowledge_statements: null` omitted | Rule 12 |

`kae_get_project_briefing` already changed shape in T3; no consumer outside the
repository reads any of these, which was verified for `recommended_next_steps`
and holds for the rest.

**Cost:** thirteen rules constrain every future tool. That is the point — the
alternative is each new surface re-deciding, which is how the briefing reached
12,199 characters.
