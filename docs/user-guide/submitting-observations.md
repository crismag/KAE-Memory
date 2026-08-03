# Submitting Observations and How KAE Classifies Them

> **Two behaviours are described below and they are clearly separated.**
> **Today** is what the system does now. **Planned** is designed and *not
> built* — nothing in this guide's Planned sections works yet.

---

## Today

### What `kae_submit_observation` does

```
kae_submit_observation(project_id, observation, idempotency_key)
```

It records your wording **verbatim** as evidence against a project, with its
session, actor, and timestamp. Optional `source` and `classification_hint`.

`idempotency_key` is required — any stable string of your choosing — so a retry
cannot duplicate the evidence.

### What it does not do

- It does **not** create project knowledge.
- It does **not** classify anything. `classification_hint` is stored as text
  inside the message and is not acted on.
- It does **not** extract requirements, dates, milestones, or tasks.
- Your observation does **not** appear in `kae_get_project_briefing`.

An observation today is a durable, attributable note. Nothing reads it back
except a person, or a search over messages.

### What you get back

```json
{
  "message_id": "...", "session_id": "...", "idempotent_replay": false,
  "status": "recorded_as_proposed_evidence", "knowledge_revision": 20,
  "note": "Recorded verbatim as evidence. Nothing is confirmed by this call..."
}
```

`knowledge_revision` does not change, because nothing about the project's
knowledge changed.

### So what should you submit today?

Anything worth having a record of. Mixed notes are fine — nothing is parsing
them, so nothing can misread them. Just don't expect a note saying *"M8 is
complete"* to update a milestone, or *"we need audit logging"* to become a
requirement.

---

## Planned

*Designed in [`../06_architecture/OBSERVATION_CLASSIFICATION.md`](../06_architecture/OBSERVATION_CLASSIFICATION.md).
Target **T24**, deferred. **None of this is built.***

### The intended lifecycle

```
submitted → classified → routed → reviewed → confirmed, rejected, or kept as evidence
```

Your original text is preserved unchanged at every step. Everything derived from
it sits *beside* it, pointing back at the exact words it came from.

### Three destinations

| Tier | Examples | In a normal briefing? |
| --- | --- | --- |
| **Durable knowledge** | requirements, decisions, constraints, acceptance criteria | Yes, once **you** confirm it |
| **Operational state** | milestone status, tasks, blockers, check-ins, test results | Current state only |
| **Evidence** | session notes, personal remarks, working comments | **No** — history views only |

### Mixed notes produce several records

> *"KAE-Memory achieved data insertion success during T1. Check the remaining
> tests tomorrow. Few more tests before sleeping. To God be the glory!"*

| Span | Class | Where it goes |
| --- | --- | --- |
| "achieved data insertion success during T1" | `test_result` | operational, reported |
| "Check the remaining tests tomorrow" | `check_in` | follow-up candidate |
| "Few more tests before sleeping" | `session_note` | evidence only |
| "To God be the glory!" | `personal_commentary` | evidence only |

One note in, four derived records, original intact. You would not have to split
your own thoughts up before writing them down.

### Two things classification will not do

**It will not decide anything is true.** A statement classified as a requirement
with 96% confidence is still a *proposal*. The confidence is about the
classifier being sure of the **type**, never the truth of the claim. Confirming
stays a human act.

**It will not complete a milestone because you said so.** *"M8 is complete"*
would create a proposed transition showing reported status, current status, and
that the authority was a user report. Automatic confirmation requires
authoritative evidence — passing tests, a merged release PR, a signed
deployment.

That rule exists because of a real event in this repository: the project state
recorded *"M8 is complete: knowledge is chunked, embedded, and searchable"* while
no production path created chunks at all. Written in good faith, wrong, and a
classifier taking it at face value would have made it worse.

### Examples

> *"Check vector-search progress on August 10."*
> → `check_in`, subject "vector-search progress", due 2026-08-10, proposed. Not
> durable knowledge, and it can expire.

> *"M8 is complete, but query embeddings remain unconfigured."*
> → two spans: a proposed `milestone_status` transition awaiting evidence, and a
> `constraint` or `open_question` for review.

### Personal and temporary notes

Preserved as evidence, excluded from technical briefings, never promoted, never
silently deleted, and visible in history and audit views.

Classification describes **relevance to the project, not worth**. A note being
routed to evidence-only says where it belongs, not what it is worth to you.

### Reviewing what came out

You would confirm, reject, correct, reclassify, or supersede each candidate, and
inspect the provenance back to the exact words you wrote.

Today, confirmation and rejection are **HTTP-only** — see
[getting-started.md](getting-started.md). Targets T12–T14 bring them to MCP.

---

## Where this sits

| Capability | Status |
| --- | --- |
| Verbatim capture with provenance | **Built** |
| Idempotent retry | **Built** |
| `classification_hint` acted upon | Not built |
| Automatic classification | Not built (T24) |
| Mixed-span extraction | Not built (T24) |
| Operational state records | Not built (T24) |
| Briefing filters by tier | Not built (T24) |
| Confirm / reject over MCP | Not built (T12–T14) |
