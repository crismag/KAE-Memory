# ADR-0012 — Blueprint readiness model

- **Status:** accepted
- **Date:** 2026-07-27
- **Closes:** OQ-013
- **Blocks:** M9 — Workspace and Reporting
- **Scope:** decision only. Implementation is M9 and does not begin here.
- **Numbering:** ADR-0011 is the CockroachDB testing decision; this is ADR-0012.

## Decision

Readiness is a **transparent, requirements-based coverage model**: whether the
project holds enough *confirmed* discovery knowledge to generate a useful
blueprint.

It is explicitly **not** implementation progress, success probability, model
confidence, or how much conversation has happened. The North Star shows a
percentage moving from 46% to 58%; that number has to mean something a user can
interrogate, or it misrepresents project state.

### Template

Each project uses a **versioned** readiness template of weighted discovery areas.
An area defines its key, display name, relative weight, whether it is mandatory,
the criteria for sufficient coverage, and the knowledge kinds that may satisfy
them.

The initial software template covers: problem and value proposition; users and
stakeholders; scope and boundaries; functional requirements; quality attributes;
domain model and data; interfaces and integrations; constraints and assumptions;
acceptance criteria; delivery and operational context.

Templates are configurable and versioned. Initial values ship with the
application, but readiness logic never permanently hard-codes one project type.

### Area evaluation

One authoritative state per applicable area:

| State | Credit |
| --- | --- |
| `missing` | 0 |
| `partial` | ½ |
| `sufficient` | 1 |
| `not_applicable` | excluded from the denominator |

Base score is the weighted sum of credits over the sum of applicable weights,
displayed rounded to the nearest whole number.

**Sufficiency comes from explicit configured criteria.** The existence of text,
messages, or model output is not evidence of readiness — that is the failure mode
this model exists to prevent.

### Knowledge authority

Only **confirmed** knowledge can make an area sufficient. Proposed extraction may
establish partial coverage and steer the next question, but never completes an
area on its own. Rejected and superseded knowledge contributes nothing.

An unresolved contradiction touching a **mandatory** area blocks readiness until
resolved or explicitly accepted as an assumption.

AI may classify knowledge, propose coverage states, flag possible contradictions,
and recommend follow-up questions. **The authoritative result is deterministic
application logic** over persisted knowledge and definitions — so the same inputs
give the same score regardless of which model ran.

### Gates — percentage and eligibility are different things

A **draft** blueprint requires ≥ 50%, and must be marked incomplete with missing
areas, assumptions, and open questions exposed.

An **implementation** blueprint requires *all* of: every applicable mandatory area
`sufficient`; no unresolved critical blocker; no unresolved contradiction on a
mandatory area; required acceptance criteria confirmed; and the result reflecting
the latest authoritative knowledge revision.

**A percentage alone never authorises an implementation blueprint.** Unresolved
issues may appear in generated output where policy allows, but always visibly
identified.

### Status

`not_started` · `discovering` · `draft_ready` · `blocked` · `blueprint_ready` ·
`stale`

`blocked` means coverage would otherwise permit generation but a critical blocker
or mandatory contradiction prevents it. `stale` means the result predates a later
authoritative knowledge revision.

### Persistence

Versioned definitions, and **snapshots** carrying project, template version,
knowledge revision, calculation version, score, status, draft and implementation
eligibility, mandatory-area counts, blocker counts, per-area results, and
timestamp.

The system must be able to **explain** a result — which areas, criteria, confirmed
knowledge, gaps, and blockers produced it. A single mutable percentage on the
project row is not an acceptable representation.

### Recalculation

Recalculated when authoritative knowledge changes: confirmed, edited, rejected,
superseded, linked to an area, marked contradictory, or associated with a new or
resolved blocker. Deterministic for a given template version, knowledge revision,
and calculation version.

## Five things this needs that do not exist yet

Recorded here so M9 plans for them rather than discovering them.

### 1. Recalculation is not agent work — and must not become a fourth role

The proposal allows recalculation "through the durable worker". But `enqueue_run`
requires an `AgentRole`, and **FR-009 authorises exactly three roles**. Adding a
`readiness` role to run deterministic arithmetic would breach that for no benefit.

**Resolution:** readiness calculation is synchronous deterministic logic in the
application layer. Only *classification* — deciding which area a piece of
knowledge serves — may be agent work, and that is the **Review Agent**, already
authorised. Classification proposes; calculation decides.

If a future workload genuinely needs deferred non-agent work, that is a new work
kind on the worker, not a new agent role. Not in M9.

### 2. Contradictions need the relationship layer, which is not wired

`RelationshipType.CONTRADICTS` exists in the domain and `knowledge_relationships`
exists as a table, but **nothing reads or writes it** — M5 deferred the domain
wiring to M9.

Mandatory-area contradiction blocking therefore depends on M9 first delivering
relationship persistence: a repository, the ability to record a contradiction,
and the ability to resolve one. Without it, `blocked` can never be reached and the
gate is decorative.

### 3. "Blocker" is a new concept

Nothing in the model represents a critical blocker. It is distinct from an
`unknown` knowledge item: a blocker has severity, an owner, and a resolved state.
M9 must define it — most naturally as a knowledge kind plus severity, or a small
dedicated table. This decision does not choose; it records that the choice is
outstanding.

### 4. "Authoritative knowledge revision" has no representation

`stale` requires comparing a snapshot against the project's current knowledge
revision, and no such monotonic value exists. Knowledge versions are per item.

M9 needs a project-level revision — a counter incremented on every authoritative
change, or a max-updated timestamp. A counter is preferable: timestamps collide
under concurrent writes and make "did anything change?" ambiguous.

### 5. Areas do not map onto the knowledge kinds

`KnowledgeKind` is `actor`, `goal`, `rule`, `constraint`, `requirement`,
`decision`, `unknown`, `assumption`. Several proposed areas have no corresponding
kind — "acceptance criteria", "quality attributes", "interfaces and integrations".

Two options, and M9 must pick one explicitly: express the mapping as
*area → set of kinds plus criteria* using the existing eight, or extend
`KnowledgeKind`. The column is a plain string so extension needs no migration —
but it does change the extraction vocabulary in ADR-0006, so it is a decision, not
an implementation detail.

## Schema

Additive revision `0005`, following ADR-0005's conventions: application-generated
`UUID` keys, `TIMESTAMPTZ`, `JSONB` only for open-ended structure, no cascading
deletion.

- `readiness_templates` — key, version, definition, active flag, timestamps.
- `readiness_snapshots` — the fields listed under Persistence, with per-area
  results as `JSONB` and every value used for gating as a relational column, so
  eligibility is queryable without parsing JSON.

Snapshots are append-only. Readiness history is how the demonstration shows
readiness *moving* as knowledge is confirmed, which is a proof moment.

## Interface

Labelled **Blueprint readiness**, never "project completion". Presents the
percentage, semantic status, draft and implementation eligibility, missing
mandatory areas, unresolved blockers and contradictions, the next recommended
action, and each area's contribution.

## Consequences

**Positive.** The percentage is traceable and explainable. Readiness cannot be
inflated by generating unconfirmed text — the single most important property here,
because a system that raises its own score by talking more is worse than having no
score. Mandatory gaps cannot hide behind strong coverage elsewhere. Exploratory
output stays available before full readiness. Gating stays deterministic across
models. Templates generalise beyond software later. Snapshots make progress
demonstrable.

**Negative.** Five prerequisites above must land before readiness is meaningful,
which makes M9 larger than "build the workspace". Templates and criteria are
configuration that has to be authored and maintained. Snapshot-per-change costs
writes.

**Accepted risk.** Weights and the 50% draft threshold are judgement, not
measurement. They will be wrong at first; versioned templates and snapshots are
what make correcting them safe and observable.

## Related

- [`ADR-0005-m5-physical-schema.md`](ADR-0005-m5-physical-schema.md) — schema conventions
- [`ADR-0006-extraction-contract.md`](ADR-0006-extraction-contract.md) — the knowledge-kind vocabulary
- [`ADR-0007-worker-runtime-and-leases.md`](ADR-0007-worker-runtime-and-leases.md) — the worker recalculation must not misuse
- [`ADR-0009-discovery-workspace-frontend.md`](ADR-0009-discovery-workspace-frontend.md) — the workspace that presents this
- [`../../docs/05_product/PRODUCT_EXPERIENCE_NORTH_STAR.md`](../../docs/05_product/PRODUCT_EXPERIENCE_NORTH_STAR.md)
