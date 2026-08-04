# Reviewing knowledge

KAE-Memory records what agents propose. It does not decide what is true. That
decision is yours, and this is the surface where you make it.

Everything an agent submits arrives as **proposed**. Proposed knowledge is
visible, searchable, and marked as proposed everywhere it appears. It never
becomes authoritative on its own, however many times an agent repeats it.

## The states

| State | Meaning |
|---|---|
| `proposed` | Recorded, not decided. Contributes partial readiness. |
| `validated` | A person accepted it. Authoritative. |
| `rejected` | A person turned it down. Kept as history; contributes nothing. |
| `superseded` | Replaced by a different statement. Kept; contributes nothing. |

`validated` is the repository's word for what some documents call "confirmed".
There is one state, not two words for one state.

## `kae_confirm_knowledge`

Accepts one proposed item as authoritative, without changing its wording.

```json
{
  "project_id": "…",
  "knowledge_id": "…",
  "expected_version": 1,
  "reviewer": "cris",
  "note": "Matches the approval policy.",
  "idempotency_key": "review-2026-08-03-01"
}
```

| Field | Required | Notes |
|---|---|---|
| `project_id` | yes | The item must belong to it |
| `knowledge_id` | yes | |
| `expected_version` | yes | The version you read |
| `note` | no | Why you accepted it |
| `reviewer` | **yes** | The person whose decision this is |
| `idempotency_key` | no | Supply it to make retries safe |

Response:

```json
{
  "knowledge_id": "…",
  "state": "validated",
  "version": 1,
  "authoritative": true,
  "already_applied": false,
  "knowledge_revision": 42,
  "readiness_changed": true
}
```

### Why `reviewer` is required

Confirmation is a human act (FR-005). Before Phase C, that held because the
capability simply was not on the MCP surface — no agent could confirm anything
because no tool could. Exposing this tool removes that guarantee, and no amount
of wording in a tool description restores it.

What replaces it is attribution. An agent that has not been told who is
confirming cannot supply `reviewer`, and the record never says a person decided
without naming which person. This is weaker than the tool not existing, and the
trade is recorded in the Phase C decisions.

You are relaying a decision, not making one. If nobody has told you who is
confirming, do not call this tool.

### Why `expected_version` is required

A confirmation is about wording, not about an item in the abstract. If the text
changed after you read it, your decision is about text you have not seen, so it
is refused rather than applied. Re-read the item and decide on what it says now.

### Retries

With an `idempotency_key`, retrying a confirmation returns the decision already
recorded and reports `already_applied: true`. One decision is stored, not two.

Without a key, confirming an already-confirmed item is still safe — it reports
the current state and records nothing new — but a retry cannot be distinguished
from a fresh decision, so supply a key when the call might be repeated.

A retry is not the same as a **stale** request. A retry replays a decision you
already made; a stale request is a decision about wording someone has since
changed. The first succeeds, the second is refused.

### Valid transitions

```
proposed → validated
```

Rejected and superseded knowledge cannot be confirmed. Reopening a rejection is
a different act with different consequences, and it is not this tool.

### Errors

| Code | Meaning |
|---|---|
| `project_not_found` | No such project |
| `knowledge_not_found` | No such item **in this project** |
| `version_conflict` | The wording moved; re-read and decide again |
| `invalid_state_transition` | Not reachable from the current state |
| `invalid_argument` | A missing or malformed argument |

`knowledge_not_found` covers both "does not exist" and "belongs to another
project", deliberately. A separate code would confirm that an item you may not
touch exists somewhere else.

### What it records

Every confirmation appends one row to the review log: the item, the version
reviewed, the states moved between, who decided, when, and any note. The log is
append-only. Confirming does not alter the statement's content or provenance.

### What it does to readiness

Readiness counts confirmed knowledge, so a confirmation can move an area from
partial to sufficient. Recalculation is not immediate: the project's knowledge
revision advances, which marks earlier readiness snapshots stale, and the next
calculation reflects the change. `readiness_changed` means "the revision
advanced", not "a new percentage has been computed".

## Who is the actor

This tool records that **a person** decided. An agent calling it on its own
initiative would be writing "a person confirmed this" into the audit trail,
which is the one claim the trail exists to keep honest.

Agent-submitted observations are recorded as agent activity and stay proposed.
Nothing an agent does moves knowledge into `validated`.

## `kae_reject_knowledge`

Rules out one proposed item. **Not deletion** — the statement, its versions, and
its provenance all stay readable. What changes is that it stops counting toward
readiness and stops appearing in search.

```json
{
  "project_id": "…",
  "knowledge_id": "…",
  "expected_version": 1,
  "reason_code": "incorrect",
  "reviewer": "cris",
  "note": "The repository uses SQS, not SNS."
}
```

`reason_code`, `reviewer`, and `expected_version` are all required.

### Reason codes

| Code | Use when |
|---|---|
| `incorrect` | The statement is factually wrong |
| `irrelevant` | True, but not about this project |
| `duplicate` | Already recorded elsewhere |
| `obsolete` | Was true; no longer is |
| `unsupported` | An inference the evidence does not carry |
| `out_of_scope` | Outside what this project covers |
| `other` | **Requires a note** |

`other` without a note is refused. A rejected statement stays readable forever,
and a reader who cannot tell a factual error from a scope decision has the
record without the meaning.

### Valid transitions

```
proposed → rejected
```

Confirmed knowledge cannot be rejected. Retiring something already authoritative
is supersession — a different act, recording what replaced it.

## What search returns

Search is scoped by lifecycle, and this is enforced in the query rather than
afterwards:

| Context | States returned |
|---|---|
| Normal search and briefing | `validated` + `proposed` |
| Authoritative (generating output) | `validated` only |
| Historical and diagnostic | everything, on explicit request |

Rejected and superseded knowledge is **excluded from normal search**, not ranked
lower. Until T13 it was returned like any other result, because lifecycle
existed only inside the embedded text where no query could reach it.

Every result carries `state` and `authoritative`, and no response profile can
strip them — a caller reading unreviewed proposals as established fact is the
most expensive mistake compaction could cause.

Those labels are read live from the knowledge item, not from the result text.
The embedded body still carries the status it had when written, so a confirmed
statement's text may read `Status: proposed` while its `state` correctly reads
`validated`.

## `kae_correct_knowledge`

Replaces a statement's wording. The previous wording is **kept**, never
overwritten — versions are append-only, and what the agent originally proposed
stays readable alongside what you made of it.

```json
{
  "project_id": "…",
  "knowledge_id": "…",
  "expected_version": 1,
  "content": "The service publishes reports over SQS.",
  "reviewer": "cris",
  "note": "The repository uses SQS."
}
```

### What it does to the state

| You correct a… | It becomes | Why |
|---|---|---|
| `proposed` statement | `validated` | You wrote the words; confirming your own text is ceremony |
| `validated` statement | `proposed` | The earlier confirmation covered the *previous* wording |

An **agent** correcting a proposal never validates it. Only a person's
correction can, or the worker could confirm knowledge and FR-005 would fall in a
second place nobody would look.

### Embedding

Correction changes what the statement means, so its vector is out of date.
Following ADR-0008:

1. the corrected text is stored and searchable **immediately** by lexical match;
2. the chunk is marked stale and queued for re-embedding;
3. the previous vector keeps serving semantic hits until the new one lands, so
   retrieval degrades rather than disappearing;
4. once re-embedded, the old vector is gone.

The response reports `"embedding": "pending"`. No embedding model is called
inside the review transaction.

### Response

```json
{
  "knowledge_id": "…",
  "state": "validated",
  "version": 2,
  "replaced_version": 1,
  "authoritative": true,
  "already_applied": false,
  "embedding": "pending"
}
```

### Retries

With an `idempotency_key`, a retry returns the recorded correction rather than
appending a second version. Without one, a repeated call is a **new** correction
of the corrected text — and its `expected_version` will no longer match, so it
is refused as a conflict rather than silently stacking.

## Reading the history

Every decision is on the record: the item, the version, the states moved
between, who decided, when, and why. Corrections name both versions, so
"what did we originally think, and what did we change it to" is answerable.

A correction stays distinguishable from a plain confirmation even when both end
`validated` — only one of them rewrote what the project says.


## Answering a clarification

`kae_get_clarifications` returns open questions; `kae_answer_clarification`
records the answer.

```json
{
  "project_id": "…",
  "clarification_id": "…",
  "answer": "Roughly 25 ministries file reports.",
  "idempotency_key": "answer-2026-08-04-01",
  "actor_id": "cris"
}
```

### What answering does and does not do

An answer is **evidence**, not knowledge. It is stored exactly as written and
queued for extraction; what extraction produces is *proposed* knowledge that a
person still confirms.

The response says three separate things, and they stay separate:

```json
{
  "status": "answered",
  "knowledge_state": "pending_extraction",
  "knowledge_changed": false,
  "readiness_changed": false
}
```

Reading `"answered"` as "the project now knows this" would mean acting on an
unreviewed claim. `knowledge_state` and `knowledge_changed` are integrity
fields: no response profile or token budget can remove them.

### One answer per question

With an `idempotency_key`, a retry returns the answer already recorded and
queues no second extraction. A **different** answer to the same question is
refused — nothing downstream could say which one the project believes.

An answered question stops appearing in `kae_get_clarifications`.
