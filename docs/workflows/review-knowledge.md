# Reviewing knowledge

Deciding which candidates the project stands behind.

This is the step that makes the rest mean anything. Until a person reviews,
extraction has produced text; after review, the project has knowledge.

> Drafted from source and tests. The exact call shapes come from your MCP
> client's discovered schemas, and executable validation of this workflow is
> still outstanding.

---

## What is waiting

Knowledge in `proposed` — everything extraction derived, plus anything an agent
submitted. Read it with `kae_search_knowledge`, or over HTTP with
`GET /v1/projects/{project_id}/knowledge`.

Reading a candidate's evidence first is usually worth it. `GET
/v1/knowledge/{item_id}/trace` returns the message or document behind it, and a
statement that looks wrong often turns out to be a fair reading of something
that was said carelessly — which is a different problem, with a different fix.

## Confirming

`kae_confirm_knowledge`, or `POST /v1/knowledge/{item_id}/confirm`.

Moves the item to `validated`. Only then does it count toward readiness or reach
assembled context.

## Rejecting

`kae_reject_knowledge`, or `POST /v1/projects/{project_id}/knowledge/{item_id}/reject`.

Two things are required, and both matter:

**A reason.** "No" without one tells the next reader nothing, and the next
reader is often you.

**`expected_version`** — the version you read. If the wording changed between
your reading it and your deciding, the rejection is refused:

```
409  knowledge has moved to version 2; the decision was made about version 1
```

Re-read and decide again. The check exists because a decision about wording
nobody is showing you any more is not a decision about the item as it now
stands.

**Rejection is terminal.** A rejected item never returns to `proposed`. It is
retained — what the project decided against is part of what it knows, and a
candidate that could quietly reappear would make reviewing pointless.

## Correcting

`kae_correct_knowledge`. Use it when a candidate is nearly right: the correction
becomes a new version, the previous one is superseded, and the history shows
both.

Correcting is not editing. Nothing is overwritten.

## What review does not do

**It does not verify who you are.** The `reviewer` field is caller-supplied and
unattested ([#83](https://github.com/crismag/KAE-Memory/issues/83)). Treat
attribution as advisory.

**It does not decide anything for you.** Nothing promotes itself through age,
repetition, or agreement between agents. Ten agents proposing the same statement
produce ten candidates.

## After reviewing

Readiness recalculates from confirmed knowledge. If it does not move, that is
usually correct — confirming one item in an area that needs three does not
complete it.

## Related

- [Knowledge lifecycle](../concepts/knowledge-lifecycle.md)
- [Provenance and evidence](../concepts/provenance-and-evidence.md)
- [Errors](../reference/errors.md) — why 409 rather than 422
