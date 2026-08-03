# Master MCP Target Checklist

Status: **control register**, opened 2026-08-03. Updated after each completed target.

This is the authoritative list of what the MCP surface still needs. It is
sequenced: Phase A reduces what every later response costs, Phase B fixes the
one capability that currently reports itself unavailable, and Phases C to E add
the surfaces for engine capability that already exists but cannot be reached.

Legend: `[ ]` not started · `[~]` in progress · `[x]` complete

---

## Phase A — Token and response efficiency

- [x] **T1** — Measure current MCP response size and duplication — [`MCP_RESPONSE_BASELINE.md`](MCP_RESPONSE_BASELINE.md), 2026-08-03
- [ ] **T2** — Define compact MCP response conventions
- [ ] **T3** — Trim `kae_get_project_briefing`
- [ ] **T4** — Apply pagination, limits, and detail levels to read tools
- [ ] **T5** — Verify token reduction without losing essential context

## Phase B — Embedding replacement

- [ ] **T6** — Select the production/demo embedding model
- [ ] **T7** — Add embedding model and version metadata
- [ ] **T8** — Implement the real embedding provider
- [ ] **T9** — Build restartable re-embedding workflow
- [ ] **T10** — Re-embed existing knowledge
- [ ] **T11** — Validate semantic retrieval quality

## Phase C — Knowledge review surfaces

- [ ] **T12** — Implement `kae_confirm_knowledge`
- [ ] **T13** — Implement `kae_reject_knowledge`
- [ ] **T14** — Implement `kae_correct_knowledge`
- [ ] **T15** — Verify audit trail and readiness recalculation

## Phase D — Clarification surfaces

- [ ] **T16** — Implement `kae_get_clarifications`
- [ ] **T17** — Implement `kae_answer_clarification`
- [ ] **T18** — Connect clarifications to blockers and knowledge

## Phase E — Ingestion and assembly

- [ ] **T19** — Implement `kae_ingest_document`
- [ ] **T20** — Connect ingestion to observations and proposed knowledge
- [ ] **T21** — Implement `kae_assemble_context`
- [ ] **T22** — Generate compact manifests and external artifacts
- [ ] **T23** — Complete end-to-end MCP workflow test

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
