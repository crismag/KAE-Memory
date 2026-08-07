# Errors

Every HTTP failure uses one envelope:

```json
{"error": {"code": "version_conflict", "message": "...", "detail": {}}}
```

`code` is stable and is what to branch on. `message` is for a person and may be
reworded. `detail` carries structured context where there is any.

---

## The codes

From `src/kae_memory/api/errors.py`, in the order they are matched — most
specific first.

| Code | Status | Means | What to do |
|---|---|---|---|
| `version_conflict` | **409** | The item moved after you read it | Re-read and decide again |
| `invalid_lifecycle_transition` | **409** | The transition is not one the lifecycle permits | Read the current state; the move may already have happened |
| `invalid_run_transition` | **409** | Same, for an agent run | Re-read the run |
| `invalid_identifier` | **422** | A malformed id | Fix the request |
| `domain_invariant_violated` | **422** | The request would break a domain rule | Fix the request; `detail` says which rule |
| `resource_not_found` | **404** | No such project, item or session | Check the identifier and the project scope |
| `unauthenticated` | **401** | Missing or unrecognised token | See [configuration](configuration.md) |
| `project_not_found` | **404** | The token is valid but not scoped to that project | Use a token scoped to it |
| `internal_error` | **500** | Unclassified failure | Report it — a 500 here is a defect, not a usage error |

---

## Why 409 and not 422

Worth understanding, because it changes what your client should do.

**422 says the request was wrong.** Fix it and retry.

**409 says the request was right when you made it, and the world moved.** Nothing
about the request needs correcting — the state does. Retrying the identical
request will fail identically until you re-read.

`version_conflict` is the clearest case. Rejecting a knowledge item requires the
version the reviewer read. If the wording changed after they read it and before
they decided, the rejection is refused:

```
409  knowledge has moved to version 2; the decision was made about version 1
```

That is not pedantry. **The reviewer decided about wording nobody is showing
them any more**, and the system cannot tell whether they would decide the same
about the new text. Re-reading and deciding again is the only honest resolution,
and the error says so rather than accepting a decision about a version that no
longer exists.

---

## The ones that are not errors

Three responses look like failures and are not.

**A capability gap.** Where a capability is deliberately absent from an adapter,
the response says so rather than returning an empty result. An empty list means
*nothing here*; a gap means *this adapter does not answer that*, and the
difference matters. See the [capability matrix](capability-matrix.md).

**An empty extraction result.** Extraction is asynchronous. A message stored a
moment ago may have no derived knowledge yet because the run has not finished —
not because it failed. Check the run rather than resubmitting.

**A readiness of 0%.** Readiness reflects confirmed knowledge. A project with a
long conversation and nothing confirmed is legitimately at zero, and that is the
number doing its job.

---

## Idempotency

Several write paths accept an idempotency key. A replayed request with the same
key returns the original outcome instead of creating a second record — one thing
said once stays one piece of evidence, and downstream counts stay right.

> Behaviour **under concurrent** duplicate submission is exercised on PostgreSQL
> and sequentially. See [#90](https://github.com/crismag/KAE-Memory/issues/90).

---

## Related

- [MCP tools](mcp-tools.md) · [HTTP API](http-api.md)
- [Knowledge lifecycle](../concepts/knowledge-lifecycle.md) — what the 409s protect
