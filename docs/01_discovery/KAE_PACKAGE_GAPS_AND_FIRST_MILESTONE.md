# KAE Package Generation — Capability Gaps, Studio Implications, and First Milestone

Status: **analysis**, 2026-08-01. Completes the required outputs. No implementation is authorized.

Covers: KAE-Memory capability gaps · KAE-Studio UI implications · recommended first end-to-end package-generation milestone.

## 1. KAE-Memory capability gaps

Verified against code at `de37cc4`. Severity is cost-to-build, not importance.

| # | Capability | Status today | Gap | Blocks |
| --- | --- | --- | --- | --- |
| 1 | Modules as knowledge | `KnowledgeKind` has 8 values, no `module` | **Additive** for the label; **structural** for the capability (see the minimum module capability contract) | Module packages |
| 2 | Typed relationships | 7 types; no `depends_on`, `owns`, `satisfies`, `verified_by` | **Additive** — plain string column | Dependency graph |
| 3 | Relationship write path | **Only `record_contradiction` creates edges** | **Structural** | Every graph artifact |
| 4 | Graph traversal | **Absent** | **Structural** | Build order, module context, change impact |
| 5 | **Purpose/scope-bounded assembly** | One project-wide blueprint | **Structural — the load-bearing gap** | Every package |
| 6 | Scoped readiness | Project-wide only; `ReadinessSnapshot` keyed by `project_id` | **Structural** | Module and integration gates |
| 7 | Readiness profiles | One weighted template | **Structural** | The five gates |
| 8 | **Artifact and package lineage** | **Absent entirely** | **Structural** | Staleness, regeneration, trust |
| 9 | Staleness query | `is_stale_against` exists for snapshots | **Additive** once lineage exists — reuse it | Outdated detection |
| 10 | Publication records | **Absent** | **Structural** | Publish audit |
| 11 | Acquisition-session state | **Absent** | **Structural** | Resumable interviews, cross-client continuity |
| 12 | Idempotent evidence ingestion | Runs idempotent; messages not | **Structural**, small | Retry safety — already in `ADR-0018` |
| 13 | Grounding gate on writes | **Absent** | **Structural**, small | Knowledge integrity — from `ADR-0019` |
| 14 | Per-turn governance record | **Absent** | **Structural**, small | Audit trail — from `ADR-0019` |

**Ordering that respects dependencies:** 2 → 1 → 3 → 4 → 6/7 → 5 → 8 → 9 → 10. Items 12, 13, 14 are independent and small; do them early because they protect everything after.

**Item 5 is the pivot.** Without purpose- and scope-bounded assembly there is no package at all — only the existing project-wide blueprint. Everything else either feeds it or records what it produced.

## 2. KAE-Studio UI implications

Studio's prototype already covers acquisition, review, and a Deliverables screen with generate/preview/publish and the five deliverable states. Package generation adds the following. **None of it moves authority into Studio.**

**Package composition.** Choose scope (project or module), profile (§6 of the inventory), and target tool. Today the prototype has fixed deliverables; composition makes profile and tool explicit choices with visible consequences.

**Confirmation-state preview before generation.** Show what *would* be rendered as proposed versus confirmed, and which open decisions would travel with it — before the user commits to generating. The prototype shows this after generation; before is more useful.

**Readiness gate display, per profile.** Not one percentage. "Module implementation: blocked — security incomplete, OD-011 unresolved" against the five profiles, with the specific unmet condition named.

**Staleness surfaced per artifact, not per package.** The prototype marks whole deliverables outdated. Granular lineage means showing *which files* went stale and *which knowledge change* did it.

**Conflict presentation.** When a published file was hand-edited, show the diff and require a decision. Never overwrite. This is the highest-consequence screen in delivery and does not exist yet.

**Human-override protection.** Paths outside the manifest must be visibly excluded from any write. The user should be able to see, before publishing, that `PROTOTYPE_NOTES.md` and hand-authored files are not in scope.

**Lineage inspection.** For any generated statement, trace to the knowledge and evidence that produced it — Memory already supports this via `trace`; Studio should expose it from the package view.

**What Studio must still not do:** compute readiness, decide package contents, hold authoritative knowledge, or render authoritatively in the browser (`ADR-0020`).

## 3. Recommended first end-to-end milestone

**KAE-M3 — One module package, end to end.**

Deliberately the narrowest thing that proves the product claim. It comes after MCP-M1 (`ADR-0018`) and after the acquisition loop KAE-M2 defines, because a package is only as good as the knowledge behind it.

### Scope

> From a project whose knowledge already exists in KAE-Memory, generate one **module context package** for one module, pinned to an exact revision, with a complete manifest and lineage, publish it to one target, and detect it as outdated when the module's knowledge changes.

### Deliverables

1. **Bounded assembly** — `POST /v1/projects/{id}/context-assemblies` with `scope: module` and `purpose: implementation`, returning structured context with trace references and the pinned revision.
2. **Delivery worker** — renders the assembly into the module package layout with a manifest (`KAE_PACKAGE_MODEL.md` §4).
3. **Lineage records** — package, per-artifact `source_knowledge`, content hashes, generator/template/prompt versions.
4. **One publisher** — GitHub branch or draft PR, properly, with preview and conflict detection. Not three shallowly.
5. **Publication record** in Memory.
6. **Staleness detection** — change one requirement; the package reports outdated, granular to the affected artifacts.
7. **Agent instruction file** for one target tool, stating the package/MCP precedence rule.

### Prerequisites

Modules must exist as knowledge (gaps 1–4) and module-scoped readiness must compute (gap 6). **Attempting KAE-M3 before those lands would mean fabricating module structure in the renderer** — the precise failure `ADR-0019` rejected.

### Acceptance criteria

1. The package generates from a pinned revision and the manifest names it.
2. Every artifact records the knowledge identifiers it rendered.
3. Confirmation state and unresolved gaps appear in the manifest **and** in the artifacts.
4. An unresolved open decision appears as open — **no decision is resolved to make output look complete.**
5. Dependency modules appear as stubs; no neighbour specification is copied.
6. Publication previews changes before writing and never overwrites a hand-edited file.
7. Changing one requirement marks exactly the affected artifacts outdated.
8. A coding agent given only this package can state what to build, what it depends on, how success is verified, and what remains undecided.
9. Human-authored files at the target are untouched.

Criterion 8 is the product claim. It should be tested by actually giving the package to Claude Code and Codex and recording what they can and cannot answer.

### Explicit non-goals for KAE-M3

Whole-project packages · all three publishers · expert-role profiles · prompt-version experimentation · change-impact analysis · knowledge scopes and the pattern library · Studio composition UI beyond what exists.

## 4. Summary of what this analysis establishes

The output KAE sells is **not a large folder of documents.** The evidence from this repository's own history is that four properties carried the value:

1. **A context index that governs selective loading** — "load only the layers required for the current activity."
2. **One page that wins conflicts** — a current-state document that overrides every other document.
3. **Per-task extraction** — "do not hand an agent the whole context package."
4. **Explicit non-authorisation and open decisions carried as open** — so an agent refuses rather than invents.

A generator that produces thirty coherent documents without those four properties will not accelerate a coding agent. With them, a much smaller package will.
