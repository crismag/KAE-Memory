# ADR-0015 — Review Agent output and the findings model

- **Status:** accepted
- **Date:** 2026-07-28
- **Satisfies:** FR-015
- **Depends on:** [`ADR-0006`](ADR-0006-extraction-contract.md), [`ADR-0012`](ADR-0012-blueprint-readiness-model.md)
- **Milestone:** M9

## Context

FR-009 authorises three agent roles and two are implemented. `review.v1` has had
a prompt since M6 and no execution path, so a review run failed as an
unimplemented role.

The Review Agent does not fit the extraction contract. Requirements and
Architecture both produce **knowledge**: typed items with a quoted source that
enter the lifecycle and can be confirmed. Review produces **findings** — "this
area has nothing in it", "these two statements disagree", "this claim cites
nothing". A finding is a statement *about* the knowledge base, not a member of
it. Forcing findings through `ExtractedItem` would put them in the readiness
denominator and in the extraction vocabulary, where neither belongs.

## Decision

### Findings are derived, not stored

There is **no findings table and no migration**. Findings are computed from
persisted state each time they are requested.

FR-015 says reporting is *"a view over operational data, not a separate
analytics platform"*, and that settles it: every deterministic finding is a
function of knowledge, area links, blockers, relationships, and the readiness
template. Storing them would create a second copy that can disagree with the
state it describes, and would need invalidation on every authoritative write —
machinery whose only purpose is to keep a cache honest.

The corollary is that findings have no identity and cannot be "dismissed". A
finding disappears when the condition that produced it does — by confirming
knowledge, assigning an area, resolving a contradiction, or raising a blocker.
Acting on a finding means changing the state, which is the behaviour worth
encouraging.

### The deterministic checks

Computed with no model involved, so they work offline and give the same answer
every time:

| Finding | Condition |
| --- | --- |
| `missing_area` | A mandatory area has no confirmed knowledge |
| `partial_area` | An area has confirmed knowledge below its configured minimum |
| `unclassified_knowledge` | A knowledge item is linked to no readiness area |
| `unconfirmed_knowledge` | A proposed candidate is still awaiting human review |
| `open_question` | An `unknown` knowledge item — a gap the project recorded about itself |
| `unresolved_contradiction` | A `CONTRADICTS` relationship with no `resolved_at` |
| `open_blocker` | A blocker in `open` status |

Each carries a severity, the knowledge it concerns, and a recommended action.
Severity is `critical` only where the condition blocks an implementation
blueprint — a mandatory area with nothing in it, an unresolved contradiction, an
open critical blocker — because a report where everything is urgent is a report
nobody reads.

### What the model may do, and may not

Unchanged from ADR-0012: **classification proposes, calculation decides.**

The Review Agent **may** classify knowledge into readiness areas, and that
classification is written as a `knowledge_area_links` row stamped with the run
that proposed it. This is the one authoritative write a review run performs, and
it is reversible, attributable, and cannot invent coverage on its own — an area
still needs *confirmed* knowledge of an accepted kind to become sufficient.

The Review Agent **may not** record contradictions. It reports candidates as
findings; a human records one through the existing endpoint. The reason is
asymmetric cost: an unresolved contradiction on a mandatory area blocks
readiness, so a false positive from a model would stall a project on the model's
say-so. Flagging costs a reader a moment; recording costs the project its gate.

The Review Agent never confirms knowledge (FR-005), never resolves anything, and
never edits what it reviews. Its prompt already says *"report findings; do not
correct what you find."*

### Offline classification

The default offline path classifies by knowledge kind, mapping each kind to the
areas whose configured `kinds` accept it, and assigning only when **exactly one**
area does. Against the shipped software template that is a narrow set:

| Kind | Areas accepting it | Offline result |
| --- | --- | --- |
| `actor` | 1 | assigned to users and stakeholders |
| `assumption` | 1 | assigned to constraints and assumptions |
| `goal` | 2 | unclassified |
| `rule`, `decision` | 3 | unclassified |
| `requirement`, `constraint` | 5 | unclassified |
| `unknown` | 0 | unclassified — a gap is not coverage |

**Six of eight kinds are left to a human or a model, and that is the honest
number.** Refusing to guess is the point: choosing between "functional
requirements" and "quality attributes" for a `requirement` is precisely the
discrimination a model is for, and inventing it offline would manufacture
coverage a user would then have to unpick.

The practical consequence for an offline demonstration is stark — a typical
extraction produces `goal` and `unknown` items, so **`areas_assigned` is often
zero**. That is not a defect in the review path; it is the review path correctly
declining to invent judgement. A demonstration should say whether classification
came from the fixture or from a model.

## Consequences

**Positive.** No migration, no cache, no invalidation. Findings cannot disagree
with the state they describe. The review path works offline, so the workflow is
demonstrable from a clean clone. A false positive from a model can never block a
project.

**Negative.** Findings are recomputed on every request. At demonstration volumes
that is several small queries; at scale it would need either pagination or a
materialised snapshot, and the latter would reintroduce exactly the cache this
decision avoids. Recorded rather than solved.

**Accepted limit.** Offline classification reaches only two of eight kinds, so an
offline demonstration will show `unclassified_knowledge` for nearly everything
and readiness will barely move without a human assigning areas. That is honest —
the work genuinely has not been done — but it means the offline path demonstrates
the *mechanism*, not the assistance. Live classification is what makes the Review
Agent feel like an agent.

## Related

- [`ADR-0012-blueprint-readiness-model.md`](ADR-0012-blueprint-readiness-model.md) — classification proposes, calculation decides
- [`ADR-0006-extraction-contract.md`](ADR-0006-extraction-contract.md) — the knowledge contract findings deliberately do not use
- [`ADR-0014-http-api-contract.md`](ADR-0014-http-api-contract.md) — the transport findings are served over
