# Observation Classification and Routing

Status: **future implementation**, 2026-08-03. **Not authorised, and not an
architectural blocker.** Owning target: **T24**
(`../09_development/MCP_TARGET_CHECKLIST.md`).

Reviewed 2026-08-03 and moved out of active architecture. The current behaviour —
preserve submitted evidence, maintain provenance, require human confirmation —
is sufficient and correct. This document is design detail held for whenever T24
is scheduled, and **must not block T2 or T3**.

Design authority for how a submitted observation becomes — or deliberately does
not become — durable project knowledge.

> **Nothing in this document is implemented.** `kae_submit_observation` records
> text verbatim as a message and does nothing else. §1 states exactly what
> exists today so this document cannot be mistaken for a description of it.

---

## 1. Current behaviour, precisely

| Step | Today |
| --- | --- |
| Submission | `kae_submit_observation` records the text as a `Message` with `message_type = proposal`, verbatim |
| Provenance | Project, session, actor, idempotency key, timestamp — all recorded |
| `classification_hint` | **Cosmetic.** `_render_observation` appends it as a line of text inside the message body. It routes nothing, classifies nothing, and is never read again |
| Extraction | **None.** No run is enqueued. The message sits as evidence |
| Knowledge | **None created.** An observation never becomes a `knowledge_item` unless someone separately enqueues a requirements run over that message |
| Briefing | Observations do **not** appear. The briefing renders knowledge sections and findings; messages are not among them |

Two consequences worth stating because they read as design and are not:

**Personal commentary is already excluded from briefings** — not by policy, but
because no pipeline promotes any observation into knowledge. The filtering this
document proposes is currently performed by an absence.

**`classification_hint` implies a capability that does not exist.** A caller
passing `classification_hint: "requirement"` may reasonably believe something
acts on it. Nothing does. This is the one part of the current surface that
overstates itself, and T24 should either honour the parameter or remove it.

---

## 2. Principle

> Preserve the submission exactly. Derive beside it, never over it.

Classification creates records *alongside* the original observation. The
observation is immutable evidence; every derived item points back to it with a
span, a classifier version, and a confidence.

```
submission
  → observation stored verbatim
  → deterministic extraction        (dates, IDs, statuses)
  → semantic classification         (span → class)
  → field extraction                (class-specific)
  → policy routing                  (durable | operational | evidence)
  → review, confirmation, or nothing
```

**Classification is not confirmation.** A high-confidence `requirement` is still
a proposal. Confidence describes the classifier's certainty about the *type*,
never the truth of the statement (FR-005).

---

## 3. Retention tiers

| Tier | Holds | Appears in a standard briefing |
| --- | --- | --- |
| **Durable knowledge** | requirements, decisions, constraints, assumptions, scope, quality attributes, domain facts, acceptance criteria | Yes, once confirmed |
| **Operational state** | milestone status, tasks, blockers, check-ins, deadlines, test results, defects, risks, progress, ownership | Current state only |
| **Evidence and history** | session notes, personal commentary, temporary notes, exploratory remarks, noise | **No** — audit and history views only |

The tiers differ in authority as much as in content. Durable knowledge needs a
human. Operational state may transition on authoritative evidence. Evidence
needs no confirmation at all, because it is not a claim about the project.

---

## 4. Taxonomy

Deliberately small. A first implementation with forty overlapping labels is a
first implementation nobody can review.

**Durable** — `requirement` · `decision` · `open_question` · `assumption` ·
`constraint` · `scope` · `quality_attribute` · `domain_fact` ·
`acceptance_criterion` · `integration`

**Operational** — `task` · `milestone_status` · `check_in` · `deadline` ·
`blocker` · `test_result` · `defect` · `risk` · `progress_update` ·
`ownership_update`

**Evidence-only** — `session_note` · `personal_commentary` · `temporary_note` ·
`exploratory_statement` · `noise` · `unknown`

Note the overlap with `KnowledgeKind`, which has eight values and a different
purpose: `KnowledgeKind` says what a *confirmed statement is*, this taxonomy
says what a *submitted span was*. T24 must not merge them — putting
`personal_commentary` into `KnowledgeKind` would place it in the extraction
vocabulary and the readiness denominator.

---

## 5. Mixed observations

One submission, several spans, several routes. This is the normal case, not an
edge case.

Worked example from a real submission on 2026-08-03:

> *Cris KAE-Memory project achieved data insertion success on T1 test at this
> point. Few more tests before sleeping. To God be the glory!*

| Span | Class | Route |
| --- | --- | --- |
| "achieved data insertion success on T1 test" | `test_result` | operational — reported, not verified |
| "Few more tests before sleeping" | `session_note` | evidence only |
| "To God be the glory!" | `personal_commentary` | evidence only |

The whole observation stays intact and searchable in history. One derived
operational record; nothing durable; nothing confirmed.

Offsets in any implementation must be real spans into the stored text, so a
reviewer can see precisely which words produced which candidate.

---

## 6. Pipeline

**Stage 1 — deterministic.** Dates, relative dates, milestone IDs (`M8`), target
IDs (`T1`), decision IDs (`OQ-014`), PR numbers, status words, action verbs,
URLs, versions, environments. Produces candidate *fields*, decides nothing.

**Stage 2 — semantic.** Span → class, with confidence and a short rationale.
Structured output only; no stored chain-of-thought. This is the one stage that
needs a model, and it must degrade to "unclassified" when unavailable rather
than blocking submission.

**Stage 3 — fields.** Class-specific extraction: a `milestone_status` yields
milestone, status, effective date; a `check_in` yields subject, due date,
timezone, and **date role** — historical, effective, deadline, target, and
check-in are different things and a bare date does not say which.

**Stage 4 — routing.** By class, confidence, and authority.

### Confidence policy

| Confidence | Action |
| --- | --- |
| ≥ 0.90 | Classify and route as proposed |
| 0.65–0.89 | Route with an explicit review flag |
| < 0.65 | Leave unclassified for a human |

Confidence gates *routing*, never truth.

---

## 7. Authority

| Class | Confirmation |
| --- | --- |
| Durable knowledge | Human, always (FR-005) |
| `milestone_status` | Proposed transition. Auto-confirm **only** on authoritative execution evidence — passing acceptance tests, a merged release PR, a signed deployment record |
| `check_in` | Proposed operational reminder; never durable knowledge |
| `test_result` | `verified` only when produced by an approved runner; otherwise `reported` |
| `personal_commentary` | Never confirmed, because it is not a claim about the project |

**A milestone is never completed because a sentence said so.** A reported
completion creates a proposed transition carrying `reported_status`,
`current_status`, `transition_type`, and `authority: user_reported`.

This repository has a live example of why: `CURRENT_PROJECT_STATE.md` recorded
*"M8 is complete: knowledge is chunked, embedded, and searchable"* while no
production path created chunks at all. A human wrote that in good faith. An
automatic classifier accepting the same sentence would have made the false claim
machine-readable.

---

## 8. Storage

Conceptual separation; names may differ.

| Store | Holds |
| --- | --- |
| `observations` | verbatim text, source, session, submitter, idempotency key, provenance — **exists today as `messages`** |
| `observation_classifications` | observation id, class, confidence, classifier version, span, route, review state, rationale |
| `knowledge_candidates` | potential durable knowledge — **exists today as `knowledge_items` in `proposed`** |
| `operational_updates` | milestone transitions, tasks, blockers, check-ins, test results |
| `review_actions` | confirm, reject, correct, supersede, reclassify — with reviewer and reason |

Two of five already exist. `observation_classifications` and
`operational_updates` are new tables; `review_actions` is partly served by the
knowledge lifecycle and provenance links.

**Classified fragments must not go directly into `knowledge_items`.** That table
feeds readiness, and routing commentary into it would inflate coverage with
text nobody proposed as a requirement.

---

## 9. Briefing filters

A standard briefing includes confirmed durable knowledge, unresolved
high-impact questions, current milestone state, active blockers, critical risks,
and accepted upcoming actions. It excludes personal commentary, greetings,
expired check-ins, ordinary session notes, rejected candidates, and duplicate
evidence.

```json
{
  "include": ["durable_knowledge", "active_operational_state"],
  "exclude": ["personal_commentary", "session_note", "expired_check_in"]
}
```

This composes with the detail levels in `MCP_RESPONSE_POLICY.md` §4: detail
controls *how much* of a tier is rendered, these filters control *which tiers*
are eligible. They are orthogonal and must not be collapsed into one control.

---

## 10. Classifier contract

```json
{
  "observation_id": "...",
  "classifier": { "name": "kae-observation-classifier", "version": "1.0" },
  "items": [
    {
      "classification": "test_result",
      "confidence": 0.96,
      "source_span": { "start": 0, "end": 62 },
      "normalized_text": "KAE-Memory data insertion passed during T1 testing.",
      "route": "operational_update",
      "review_required": true,
      "fields": { "test_id": "T1", "result": "passed", "subject": "data insertion" }
    }
  ],
  "unclassified_spans": []
}
```

`normalized_text` is a convenience for review. **It never replaces the
original.**

---

## 11. Idempotency, versioning, failure

**Idempotent** by observation id, classifier name, classifier version, and
policy version. Re-running the same version creates no duplicates.

**Versioned.** A classifier upgrade produces a new result set, marks the prior
one superseded, and preserves review history. Never mutate a past
classification — a reviewer's decision was made against what they saw.

**Failure never blocks submission.** If classification fails the observation
persists, classification is marked failed with error metadata, retry is allowed,
and the response does **not** claim the observation was classified. Evidence
capture must not depend on a model being reachable.

---

## 12. Contradictions vs transitions

Not every change is a conflict. `M8 in_progress → complete` is an expected
transition; two incompatible requirements are a contradiction. The design must
distinguish contradiction · supersession · status transition · correction ·
duplicate · supporting evidence, and only the first two belong anywhere near the
contradiction machinery that already gates readiness (ADR-0015).

---

## 13. Privacy

Personal commentary submitted deliberately stays as evidence. It is not
promoted, not included in technical briefings, not used to infer personal
attributes, and not silently discarded. Classification describes **project
relevance, not worth** — `personal_commentary` is a routing decision, not a
judgement about the person who wrote it.

---

## 14. Phasing

1. **Documentation and taxonomy** — this document, the user guide, routing and
   authority policy. *No runtime change.*
2. **Deterministic extraction** — dates, IDs, statuses. Testable without a model.
3. **Semantic classifier** — structured output, confidence, mixed spans.
4. **Operational records** — milestones, check-ins, tasks, defects, test results.
5. **Briefing filters** — purpose-aware inclusion.
6. **Evaluation** — accuracy, false-promotion rate, missed mixed observations,
   reviewer workload.

Phase 1 is complete with this document. Phases 2–6 await activation of T24.

---

## 15. Open questions

1. **Does `classification_hint` stay?** **Deferred 2026-08-03** — do not
   optimise an interface with no runtime behaviour. Revisit when classifier
   work begins (T24.5). It currently implies a capability that does not exist,
   which is why it is recorded rather than left unnoticed.
2. **Do `observation_classifications` and `operational_updates` earn their
   tables?** Two new tables and a migration, against a demo that may not need
   operational state yet.
3. **Which model classifies?** Ties to Phase B (T6–T8). A classifier is a second
   provider dependency, and the extraction adapter already exists.
4. **Is `unknown` a class or the absence of one?** It appears in both the
   taxonomy and `KnowledgeKind`, meaning different things in each.
5. **Who may auto-confirm a milestone transition?** §7 says authoritative
   execution evidence; what counts as authoritative is undecided.
