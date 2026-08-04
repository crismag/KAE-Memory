# Phase C — Knowledge Review Surfaces: completion report

Completed 2026-08-03. Targets T11B, T12–T15.

**Verdict: complete with documented limitations.**

Phase C set out to let a person review what agents propose and make an explicit,
durable decision about it. It does that, and the review record it leaves is
trustworthy. It also cost one architectural guarantee, which is the most
important thing in this report and is stated before the successes.

## What it cost: FR-005 stopped being structural

Before Phase C, `tests/mcp_adapter/test_boundaries.py` asserted:

> Two writes, and neither confirms anything. Confirmation stays a human act
> (FR-005), so no tool here may perform it.

That was not a naming rule. With confirmation absent from the MCP surface,
FR-005 held **structurally** — the surface is reached by agents, and an agent
cannot perform an act for which no capability exists. Phase C requires the
review tools on that surface, so the guarantee is gone, and no tool description
recovers it: a description is a request, and the tool is callable regardless.

The first implementation made it worse before making it visible. It hardcoded
`actor_type=ActorType.USER`, so an agent calling `kae_confirm_knowledge` on its
own initiative would have written *"a person confirmed this"* into the audit
trail — the same mislabel this phase fixed in `kae_submit_observation`,
reintroduced in the one tool whose entire purpose is recording that a human
decided.

**What replaces it is attribution.** `reviewer` is required on all three review
tools. An agent that has not been told who is deciding cannot supply it, so it
cannot record a human decision, and no decision is anonymous. Bulk review stays
off the surface, so one call is one item, one named person, one version.

This is weaker than the tool not existing. The boundary tests now document what
they stopped enforcing rather than being deleted.

**Residual risk, unmitigated:** an agent that fabricates a reviewer name records
a human decision nobody made. Nothing in this layer detects it. Closing it needs
identity that MCP does not carry.

## Tools implemented

| Tool | Transition | Notes |
|---|---|---|
| `kae_create_project` | — | T11B, delivered earlier |
| `kae_confirm_knowledge` | `proposed → validated` | content untouched |
| `kae_reject_knowledge` | `proposed → rejected` | reason code required |
| `kae_correct_knowledge` | see below | appends a version |

Correction resolves by prior state **and actor**:

| Correcting a… | by | becomes |
|---|---|---|
| `proposed` item | a person | `validated` — they wrote the words |
| `validated` item | a person | `proposed` — the old confirmation covered the old wording |
| `proposed` item | an agent | `proposed` — an agent may not confirm |

The actor term is not decoration. Keying on prior state alone would let the
worker validate knowledge, putting FR-005 back in a model's hands in the one
place nobody would look for it.

## Mechanisms

**Correction revision strategy: versioned logical record** (Strategy A). Already
the repository's model — `KnowledgeItem.append_version` is append-only and the
schema enforces `UNIQUE (knowledge_item_id, version_number)`. Nothing was
rebuilt.

**Concurrency: `expected_version` over the existing `KnowledgeVersion` number.**
No second revision field. The project-level `knowledge_revision` was too coarse:
any write anywhere would have made two reviewers working on different items
collide. Two layers — an explicit comparison after load, and the unique
constraint as backstop for the race between check and insert, translated to
`version_conflict`.

**Idempotency: unique index on `(knowledge_item_id, idempotency_key)`.** Not a
read-then-insert, which races: two concurrent retries of one decision would both
find nothing and both write. A retry and a stale decision are distinguished
deliberately — they look alike from the client and are not alike at all.

**Ownership: enforced in `MemoryService`.** A check in the MCP handler would
have left the HTTP confirm route unprotected, and that route accepted a
knowledge id with no project scoping at all. Fixing it below the adapter closed
both.

**Audit: `knowledge_review_events`,** migration `0007`, append-only with no
update path. Actions are `knowledge_validated`, `knowledge_rejected`,
`knowledge_corrected` — never a generic "updated", because a correction that
ends `validated` and a plain confirmation are the distinction an audit reader is
looking for. Migration `0008` adds `from_version_number`: confirmation and
rejection decide about a version without changing it, but a correction has two
in play, and deriving "resulting = prior + 1" would hold until it did not.

**Readiness: invalidated, not recalculated.** The existing model advances the
project's knowledge revision, marking earlier snapshots stale; calculation
happens on demand. `readiness_changed` in a response means the revision
advanced, not that a new percentage was computed.

## Retrieval, and the defect this phase closed

Rejected knowledge was being returned by search. Lifecycle existed only inside
the embedded metadata prefix, where no query could reach it, so a statement a
person had ruled out came back as an ordinary result. The development corpus
held one such item.

Both paths now filter in SQL. Per the approved B1 decision, searchable and
authoritative are separate questions:

| Context | States |
|---|---|
| Normal search, briefing, review | `validated` + `proposed`, each labelled |
| Authoritative (generating output) | `validated` |
| Historical and diagnostic | everything, on explicit request |

`VALIDATED`-only retrieval was measured before being rejected as a default: it
would have cut the corpus from 32 searchable chunks to 11 and failed the T11
evaluation set.

Every result carries `state` and `authoritative`, both added to
`INTEGRITY_FIELDS` so no profile or token budget can strip them, and both read
live from the knowledge item rather than parsed from the text.

## Verified in T15

**Audit** — one event per decision, each under its own action; full attribution;
corrections naming both versions; stable ordering; project scoping; replays and
stale decisions writing nothing.

**Readiness** — confirmation makes an area sufficient; rejection and supersession
contribute nothing; correcting a proposal earns coverage; correcting confirmed
knowledge reduces it. The revision advances once per real decision and not at
all on a replay or a refusal.

**End-to-end** — one project, four proposals, every decision, plus a retry, a
stale decision, and a cross-project attempt. Afterwards: rejected content gone
from search but still readable historically, corrected wording returned and the
replaced wording not, original versions preserved, corrections queued for
re-embedding and picked up by the Phase B workflow, exactly one event per real
decision, and nothing at all in the neighbouring project.

## Limitations

**Correction cannot reclassify knowledge.** The Phase C direction's Scenario 3
expected a correction to move an item between readiness areas. It cannot:
readiness resolves an item through its area link and its `kind`, and correction
changes only content. `kind` is immutable after creation. Asserted as a test so
a later reclassification feature overturns it deliberately.

**A fabricated reviewer name is undetectable.** See above.

**The metadata prefix goes stale on confirmation.** A chunk's body still reads
`Status: proposed` after a person confirms the statement; nothing rewrites it.
Responses are correct because labels are read live, but the *embedded* text a
semantic query matches against can carry a status that is out of date. Rewriting
it on every lifecycle change would mark the chunk stale and force a re-embed per
confirmation.

**Readiness recalculation is not inside the mutation transaction.** By existing
design. A caller wanting a fresh percentage must ask for one.

**Reopening a rejection is not possible**, by design and per scope.

## Follow-ups

1. **Reconsider the ADR-0008 metadata prefix.** Two independent reasons now: it
   goes stale on confirmation, and T11 measured it costing retrieval separation
   (0.130 with, 0.191 without). Needs embedding version 3 and a migration.
2. **Reclassification** — a way to change an item's `kind` or area link under
   review, if Scenario 3's behaviour is wanted.
3. **Reviewer identity** — anything stronger than a caller-supplied name.
4. **Hybrid ranking** — carried over from Phase B; still the durable answer to
   the 0.005 threshold window.

## Migrations

`0007` — `knowledge_review_events`. `0008` — `from_version_number`. Both
additive; nothing existing altered.

## Test results

Full suite green at each merge: **547** (T12), **575** (T13), **597** (T14).
T15 adds 37 more — 17 audit and readiness verification, 20 end-to-end.

Phase C added roughly 120 tests across the review surface, lifecycle filtering,
audit, readiness, and the end-to-end workflow.

## Also fixed in passing

- `reject_knowledge` accepted a `note` and discarded it.
- `kae_submit_observation` recorded agent output as `ActorType.USER`.
- The `Message` invariant now admits an external agent: it must name the run
  that produced it **or** the actor, which is why the mislabel above existed.
- Migration tests ran `downgrade base` against whatever `KAE_DATABASE_URL`
  named — the real database — and passed while doing it. Fixed separately, with
  a fail-closed guard.

## Next

Phase D — clarification surfaces (T16–T18).
