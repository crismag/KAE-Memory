# ADR-0016 — Blueprint generation and statement traceability

- **Status:** accepted
- **Date:** 2026-07-28
- **Satisfies:** FR-008, and the trace half of FR-007
- **Depends on:** [`ADR-0012`](ADR-0012-blueprint-readiness-model.md), [`ADR-0015`](ADR-0015-review-agent-and-findings.md)
- **Acceptance:** AT-004
- **Milestone:** M9

## Context

FR-008 requires that confirmed knowledge render as a reviewable blueprint whose
statements link back to their supporting evidence, labelled grounded, derived, or
assumption, exportable as Markdown. AT-004 is the test: *a generated blueprint
section links each statement to the confirmed knowledge item and source evidence
that produced it.*

`MOD-blueprint` has been specified and unimplemented since M1. Everything it
needs now exists — confirmed knowledge, readiness areas, provenance links from
knowledge to the run that produced it and the message it came from, and the
`used_by` links that record what a run consumed.

## Decision

### The blueprint is generated, not authored

**No model writes blueprint prose.** Each statement is a confirmed knowledge
item's own text, grouped by the readiness area it was assigned to, ordered by the
template's area order.

That is a deliberate refusal. A model asked to "write the blueprint" would
produce fluent connective text that no knowledge item supports, and every
sentence of it would be unattributable — which is exactly the failure FR-008's
labelling exists to prevent. A blueprint whose every statement traces to a
confirmed item is worth more than a readable one that mostly does.

Prose synthesis is a later decision, and it will need a rule for how generated
connective text is labelled and traced before it can be taken.

### Derived, like findings

**No blueprint table and no migration.** A blueprint is a function of confirmed
knowledge, area links, and the readiness template, computed on request — the same
reasoning as ADR-0015. A stored blueprint would go stale against the knowledge it
claims to describe, and the readiness snapshot already records the state a given
rendering reflected.

Statement identifiers are therefore **deterministic**, not random: a UUIDv5 over
the project, area, and knowledge item. The same statement keeps the same
identifier across regenerations, so a client can link to one, and a statement
that disappears does so because its knowledge changed rather than because the
identifier churned.

### Labels

| Label | Meaning |
| --- | --- |
| `grounded` | Traces to a source message — the user's own words |
| `derived` | Produced by an agent run from other knowledge, with no message of its own |
| `assumption` | Knowledge of kind `assumption`, whatever its provenance |

The label is computed from provenance, never asserted. `assumption` wins over the
others: something the project assumed remains an assumption even when a message
prompted it, and labelling it `grounded` would overstate its standing.

**No statement lacks a label or a trace target**, which is FR-008's acceptance
condition, and it holds structurally: a statement exists only because a confirmed
knowledge item exists, and that item always carries a `produced_by` link.

### Eligibility, and what a draft must expose

A **draft** blueprint requires `draft_eligible` — ADR-0012's 50% threshold. It is
marked incomplete and carries its missing mandatory areas, open questions, and
unresolved findings alongside the content.

An **implementation** blueprint requires `implementation_eligible`: every
mandatory area sufficient, no critical blocker, no unresolved contradiction on a
mandatory area.

Below the draft threshold the API still returns a blueprint, marked
`incomplete` with an empty or sparse body. Refusing to render would tell a user
nothing about *what is missing*, and the missing-area list is the most useful
thing an early blueprint can say.

### Trace

`GET /v1/knowledge/{id}/trace` returns the full chain for any knowledge item:
project, the sessions and messages it came from, the run that produced it, the
runs that consumed it, and every version with its provenance.

Statements carry their knowledge item identifier, so tracing a blueprint
statement is one hop rather than a parallel trace API over derived identifiers.
The chain is assembled from `knowledge_provenance_links`, which M5 created for
exactly this and which nothing had read until now.

## Consequences

**Positive.** Every statement is attributable by construction. No migration, no
staleness, no invalidation. The blueprint works offline because it involves no
model at all. Markdown export is a rendering of the same structure, so the two
cannot disagree.

**Negative.** The blueprint reads as a structured list rather than a document.
That is the honest consequence of refusing to generate unsupported prose, and it
will disappoint anyone expecting narrative — the gap is real and named rather
than papered over.

**Corrected while building this.** Area assignment now rejects a kind the area
does not declare. Readiness already applied that guard when scoring, so a
permissive assignment produced a statement that appeared in the blueprint and
contributed nothing to the percentage printed beside it. "Assigned" and "counts"
must mean the same thing, or the blueprint quietly disagrees with the score.

**Accepted limit.** A knowledge item assigned to no area appears in no section.
Offline that is most items (ADR-0015), so an offline blueprint can be nearly
empty while the knowledge base is not. The response reports the unassigned count
so the emptiness is explained rather than mysterious.

## Related

- [`ADR-0012-blueprint-readiness-model.md`](ADR-0012-blueprint-readiness-model.md) — the gates this honours
- [`ADR-0015-review-agent-and-findings.md`](ADR-0015-review-agent-and-findings.md) — derived-not-stored, and the classification limit
- [`ADR-0005-m5-physical-schema.md`](ADR-0005-m5-physical-schema.md) — the provenance links this finally reads
