# KAE-Memory under the PPA operating model

What this repository owes, and why. The governing decision, the findings and the
ordering live in KAE-Ecosystem — `decisions/ADR-0001-ppa-operating-model.md`,
`roadmap/PPA_FINDINGS_REGISTER.md`, `roadmap/EXECUTION_SEQUENCE.md`, and the two
contracts in `contracts/`. This file is the Memory-side view of them.

## What Memory owns

**Project truth** — source · inference · recommendation · assumption ·
confirmation · provenance · history.

**Memory does not converse.** Every task below is about representing and
projecting project state, never about deciding what to say.

## The finding that concerns this repository most

> **KAE-Memory was designed for an assistant. CIE was built as an examiner. The
> assistant's machinery has never been switched on.**

Six of the seven built-and-unused capabilities are in `domain/`:
`AssumptionOrigin.KAE_RECOMMENDED_ACCEPTED`, `Consequence`/`MATERIAL`,
`RevisitTrigger`, `AssumptionOrigin.UNRESOLVED_ALTERNATIVE`, `deferred`
(`setup.py:169`, `generation.py:60`, `maturity`), and the ten weighted areas of
`SOFTWARE_TEMPLATE`.

**Nothing here needs a new domain model.** It needs the existing one reachable.

## Tasks

### M-1 · Set confirmation — *blocks the interaction contract*

`confirm_knowledge(item_id)` operates on one item; there is no area-level, batch
or set confirmation anywhere. So when a user says *"yes, that holds"* about a
synthesis drawn from nine statements, there is nothing to act on — this is half
of PPA/STATE-01.

Required: confirm a **named set** of knowledge ids in one operation, atomically,
with the provenance of the confirming act recorded. The set comes from the CIE
turn's `provenance` field.

*Exit:* one call confirms nine statements; readiness moves; partial failure
confirms nothing.

### M-2 · The reviewer on the deployment — *F-019, one variable*

`KAE_REVIEW` is unset, so the shipped reviewer is
`deterministic-review-fixture`, which classifies only where a knowledge kind
leaves no choice. **Eight of ten areas can never populate.** This is why 72
accurate statements produced `0% · not_started`.

The adapter must declare itself as extraction reports
`deterministic-fixture`, and refuse rather than degrade on an unsatisfiable
opt-in.

*Exit:* more than two of ten areas populate on a project holding hundreds of
statements.

### M-3 · The aggregate clarification key — *PPA-01*

`_question_key` (`application/clarification_service.py:633`) hashes
`sorted(clarification.knowledge_ids)`. One more `unknown` joins the aggregate →
new key → the identical question is asked again. Observed ~10 times in 42
messages.

The key must identify **the question**, not its current membership.

### M-4 · Status stops being materialised into the conversation — *PPA-02*

`_as_clarification` plus `_LazySession` write findings into the conversation's
own session, and Studio's `POST /clarifications` materialises on listing. A
status finding then renders as a conversational turn (PPA-03).

A directive may exist. **It must never be a transcript entry.**

### M-5 · The planning-state projection — *PPA-17, DEF-1.2*

The projection carries a real `definition` block, backend-owned area states
(established · partial · missing · assumed · conflicting · needs confirmation ·
unavailable), structured gaps extending `Blocker`, `generated_at`,
`contract_version`, and surfaced staleness (F-020).

Area states, coverage and the percentage are **computed here**, per
`contracts/PLANNING_MODEL.md`. Studio renders them; it does not derive them.

**Content loss is reported separately and never folded into the percentage.** A
percentage computed over content that was never captured is a confident lie.

### M-6 · Extraction repair — *F-018*

29–65% of real content abandoned across four corpora. `_normalise` survives
reflowed prose but not box-drawing characters, code fences or tables — and the
prose-only corpus still lost 29%, so **do not assume one cause**. Reproduce from
a real chunk first. Then reconsider the batch rule: one unverifiable citation
currently discards every good item beside it.

M-5 makes this urgent — the moment coverage is visible, it must be honest.

### M-7 · Project deletion as a capability — *D-C, F-021*

Every foreign key to `projects` is `NO ACTION` across nine tables. The child
ordering is domain knowledge; a script that gets it wrong half-deletes a
project.

### M-8 · The adapter-surface test — *T0.6*

A test that walks the application services and asks *"is this declared on any
adapter"*. Four capabilities have been found complete and unreachable — F-007,
modules (F-006), assumptions (N45), `enqueue_review` (EM-5) — and
`PublicationService.publish` is a fifth (F-022, retire it under D-D).

Parity tests check that declared capabilities exist, not that existing behaviour
is declared. The gap is invisible from both directions.

## What must not change

The `SYSTEM_DIRECTIVE`. Principle 8 — *model-generated inference must never
silently become user-confirmed decisions* — is **strengthened** by this work:
R1 and R19 give recommendations a first-class representation with a KAE origin,
so KAE can be opinionated without its opinions being mistaken for the
customer's.

Credentials stay with the integration and secret-management layer, never
embedded in knowledge, generated documents or manifests.
