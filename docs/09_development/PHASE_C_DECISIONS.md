# Phase C — approved decisions and amended checks

Recorded 2026-08-03. Two checks in the Phase C direction were amended after
measurement; both amendments are approved. This file is the traceable record of
what changed and why, so a later reader does not find the implementation
disagreeing with the brief and assume it drifted.

## B1 — searchable is not the same as authoritative

**Original wording:** default authoritative search returns only `VALIDATED`.

**Amended.** Conflating "searchable" with "authoritative" would have emptied the
system. Measured on the development corpus before the change:

| lifecycle | knowledge items | chunks |
|---|---|---|
| `proposed` | 20 | 20 |
| `validated` | 11 | 11 |
| `rejected` | 1 | 1 |

`VALIDATED`-only retrieval drops searchable content from 32 chunks to 11 — 63%
of the corpus — including most of what the T11 evaluation set queries. It would
also contradict readiness, where proposed knowledge earns partial credit rather
than nothing, and contradict the product's own contract that a submitted
observation is visible as proposed evidence.

**Approved contract:**

| context | lifecycle states |
|---|---|
| authoritative, and default for generation | `VALIDATED` |
| review and discovery | `VALIDATED` + `PROPOSED`, each labelled |
| normal retrieval | excludes `REJECTED` and `SUPERSEDED` |
| historical and audit | explicit lifecycle or history query only |

The real defect the original check was aimed at is genuine and remains: one
`REJECTED` item is retrievable today, because lifecycle appears only inside the
embedded metadata text and never in a query predicate. That is fixed in T13.

## B2 — check 32, corrected knowledge and stale vectors

**Original wording:** the old vector must never represent the corrected item.

**Amended**, preserving ADR-0008. Deleting the vector on correction would make a
corrected statement semantically invisible until a re-embed lands, turning a
correction into a temporary disappearance.

**Replacement check:**

> After a correction, retrieval must return the current corrected knowledge
> text. The previous embedding may remain temporarily available under ADR-0008,
> but it must be identified as stale or pending replacement, and must cease
> being the active vector after successful re-embedding.

So staleness is bounded and observable rather than forbidden. What is forbidden
is presenting stale wording as though it were the current authoritative text.

Measured context, from T11: the ADR-0008 metadata prefix itself costs
separation — 0.130 with it against 0.191 without. Revisiting the prefix is a
separate target requiring embedding version 3.

## Vocabulary

The repository's terms are authoritative. Where the direction used different
words:

| direction | repository |
|---|---|
| confirmed | `LifecycleState.VALIDATED` |
| revision | `KnowledgeVersion.number` |
| actor | `ActorType.USER` / `AGENT` / `SYSTEM` |
| review event | `KnowledgeReviewEvent` |

No parallel status vocabulary was introduced in persistence.

## FR-005 stopped being structural

The most consequential thing Phase C changes, and it was not in the direction.

`tests/mcp_adapter/test_boundaries.py` asserted, before T12:

> Two writes, and neither confirms anything. Confirmation stays a human act
> (FR-005), so no tool here may perform it.
>
> `assert not {n for n in names if "confirm" in n or "approve" in n}`

That was not a naming convention. With confirmation absent from the MCP surface,
FR-005 held **structurally**: the surface is reached by agents, and an agent
cannot perform an act for which no capability exists. Phase C requires
`kae_confirm_knowledge` on that surface, so the guarantee is gone. It cannot be
recovered by a tool description — a description is a request, and the tool is
callable whether or not the caller honours it.

The first implementation made this worse rather than visible: it hardcoded
`actor_type=ActorType.USER`, so an agent calling the tool on its own initiative
would have written *"a person confirmed this"* into the audit trail. That is the
same mislabel this phase fixed in `kae_submit_observation`, reintroduced in the
one tool whose entire purpose is recording that a human decided.

**What replaces the structural guarantee is attribution.** `reviewer` is
required. An agent that has not been told who is confirming cannot supply it, so
it cannot record a human decision, and no confirmation is ever anonymous. Bulk
confirmation stays off the surface, so one call is one item reviewed by one
named person at one version.

This is **weaker** than the tool not existing, and the weakening is deliberate
and approved. It is recorded here rather than absorbed into a passing test,
because the boundary test that used to enforce it now documents what it stopped
enforcing.

Residual risk, stated plainly: an agent that fabricates a reviewer name records
a human decision that no human made. Nothing in this layer detects that. Closing
it needs identity that MCP does not currently carry.

## Observed during T13

**The embedded metadata prefix goes stale on confirmation.** A chunk's body
carries `Status: proposed` from when it was written, and nothing rewrites it
when a person confirms the statement. Result labels are therefore read live from
the knowledge item, never parsed from the text.

Rewriting the prefix on every lifecycle change would mark the chunk stale and
require a re-embed per confirmation, which is a large cost for a label the
response already reports correctly. Recorded as a follow-up rather than fixed
here. It does mean the *embedded* text a semantic query matches against carries
a status that may be out of date — a second reason, after the T11 separation
measurement, to revisit whether the prefix earns its place.

## Deviations recorded during T12

**Cross-project mismatch returns `knowledge_not_found`.** The direction asked
for a distinct mismatch error; check 46 asked that it not leak. A distinct code
confirms to a caller that an item they cannot touch exists somewhere else, which
is the one fact the ownership check withholds. Which case occurred is
distinguishable server-side.

**Correction auto-validation keys on the actor, not only the prior state.** A
human reviewer correcting a proposed item validates it, because they authored
the wording. An *agent* correcting one does not — prior state alone would let
the worker confirm knowledge, which FR-005 forbids. Implemented in T14 as a
distinct review operation; the existing `correct_knowledge` is unchanged for
agent callers.

**Readiness is invalidated, not recalculated, inside the mutation.** The
existing model advances the project's knowledge revision, which marks earlier
snapshots stale; calculation happens on demand. `readiness_changed` in a
response therefore means "the revision advanced", not "a new percentage was
computed". Making recalculation part of the mutation transaction would be a
change to the readiness model, not to Phase C.

**`Message` invariant amended.** An `AGENT` message previously had to name the
agent run that produced it. An agent working through MCP has no run inside this
system, which is why `kae_submit_observation` had been recording model output as
`ActorType.USER`. The invariant now requires an agent message to name either the
run or the external actor — accountability is preserved, and the mislabel is
gone.
