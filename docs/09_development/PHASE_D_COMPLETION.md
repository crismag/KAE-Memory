# Phase D — Clarification Surfaces: completion report

Completed 2026-08-04. Targets T16–T18.

**Verdict: complete.**

Phase D set out to let KAE ask a person what it does not know, and to route the
answer back into the system without anything pretending to know more than it
does. The loop now closes end to end, and the asynchronous stages are visible
rather than collapsed.

## The pipeline, working

```
gap in what the project knows
  -> question materialised, with an id a caller can answer
  -> person answers, verbatim
  -> extraction queued                      [nothing known yet]
  -> worker claims and extracts             [asynchronous]
  -> proposed knowledge, with provenance    [still nothing confirmed]
  -> person confirms
  -> readiness moves
```

Only the first stages are synchronous, and the tests keep it that way: the
integration test runs a real `Worker` over the queue rather than calling the
extractor, because a test that collapsed the stages would prove a workflow the
product does not have.

## What each target settled

**T16 — `kae_get_clarifications`.** Settled the contract question that gated the
phase. A clarification derived from a finding has no identity, so a read that
returned them would hand back questions nothing could answer. This *records*
the questions it returns, keyed on subject, so re-deriving one already asked
returns the existing question rather than asking a person twice.

That makes a `get_` call a write, which is a trap for anyone reasoning about
what is safe to retry. So it is declared in four places — the tool description,
the docstring, the write-surface guardrail, and a test asserting the description
admits it — rather than being true and unmentioned.

**T17 — `kae_answer_clarification`.** Records the answer verbatim and queues
extraction. The care here is in what the response claims: answer accepted,
extraction scheduled, knowledge unchanged, kept as three separate facts.
`knowledge_state` and `knowledge_changed` are integrity fields, so no profile or
token budget can compact "answered" into "known".

One logical answer per question, enforced in the service so every caller gets
it. A retry replays; a *different* answer is refused, because two answers under
one question leave nothing downstream able to say which the project believes.

**T18 — the loop closes.** Extraction happens through the existing worker, not
from the MCP surface. What it produces is `PROPOSED`, and readiness does not
move until a person confirms.

`ClarificationState` exposes where a clarification has reached —
`waiting_for_answer`, `waiting_for_extraction`, `extracting`,
`awaiting_review`, `completed`, `extraction_failed` — so a caller reads its
position rather than inferring it from unrelated fields.

That state is **derived from the records**, not stored beside them. A stored
state would be a second source of truth able to disagree with the first, and the
disagreement would be invisible.

## The integrity guarantees, asserted rather than asserted-about

Each of these has a test that fails if the claim stops being true:

| claim | how it is held |
|---|---|
| answering creates no knowledge | knowledge count unchanged after answering |
| answering does not move readiness | knowledge revision unchanged |
| extraction proposes, never validates | every produced item is `PROPOSED` |
| proposed knowledge earns no coverage | every area's `confirmed_count` is 0 |
| confirming is what moves readiness | revision advances only after `review_confirm` |

The last two matter most: a system that raised its own readiness by generating
more candidates would be worse than one with no readiness score at all.

## Provenance

Extracted knowledge links back to the answer message it came from
(`DERIVED_FROM_MESSAGE`), the answer links to its question (`answers_message_id`),
and the question carries its subject (`asks_about`). The subject is carried
forward onto the answer deliberately, so the chain survives the finding that
prompted it being resolved away.

## Idempotency

A replayed answer returns the recorded one and queues no second extraction. A
completed run replays its output rather than extracting again, so running the
worker twice proposes one set. A conflicting answer is refused even after
extraction has run.

## Limitations

**Extraction quality is the deterministic adapter's.** These tests use
`DeterministicExtractionAdapter`, so they prove the *pipeline*, not the quality
of what a real model would extract from an answer. That is the right split —
the pipeline is what Phase D owed — but nobody should read these results as
evidence about extraction quality.

**Findings recompute; they are not pushed.** A resolved gap stops producing a
finding the next time findings are derived. Nothing notifies a caller that a
finding disappeared, and `kae_get_clarifications` is the surface for noticing.

**`extraction_failed` is terminal for now.** A failed extraction leaves the
answer standing with nothing extracted from it. Retry is a worker concern and
not yet surfaced through the clarification API.

## Test results

746 passing on PostgreSQL. T18 adds 16 integration tests over the real worker;
T17 added 24; T16 added 21.

CockroachDB remains in maintenance verification (ADR-0022): both providers
passed 675 at the last full cross-provider run, and the offline schema-parity
checks run on every suite invocation.

## Next

Phase E — ingestion and assembly. Phase D established the workflow semantics;
Phase E broadens the inputs and turns validated knowledge into context an AI
system can build from.
