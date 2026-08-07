# Provenance and evidence

Every statement KAE-Memory holds can say where it came from. That is the
difference between a project that knows something and one that merely contains
text saying it.

---

## Evidence and derivation are separate

**Evidence** is what someone said or supplied: a message, a submitted
observation, an ingested document. Stored verbatim.

**Knowledge** is what was derived from it: typed, versioned, with a lifecycle.

They are stored apart, and derivation never overwrites evidence. A wrong
extraction is a wrong candidate — it does not corrupt the record of what was
actually said, and it can be rejected without losing the sentence that produced
it.

## Tracing a statement

```
GET /v1/knowledge/{item_id}/trace
```

Resolves an item to the evidence behind it. Use it when a statement looks
surprising, before assuming it is wrong: often the sentence it came from
explains it.

## What provenance covers

| Reliable | |
|---|---|
| **What** was derived | the item, its kind, its versions |
| **From what** | the message, document or run |
| **When** | recorded at each version |
| **Which run** | including whether a model or the offline fixture produced it |

| Not reliable | |
|---|---|
| **Who** confirmed it | `reviewer` is caller-supplied and unattested |

That last row is a real limitation, not a caveat for form's sake. An
authenticated caller can attribute a confirmation to a person who never made it,
and nothing detects it ([#83](https://github.com/crismag/KAE-Memory/issues/83)).
Treat reviewer attribution as advisory.

## Versions are history, not overwrite

A correction adds a version and supersedes the previous one. Nothing is edited
in place, and nothing is deleted — including rejected items.

So "what did this project believe in March, and why" has an answer. A store that
overwrote would only be able to answer what it believes now.

## Where the model was, and was not

Extraction produces candidates and records which run produced them. If the run
used the offline fixture rather than a model, the run says so
(`"model": "deterministic-fixture"`).

Worth checking before treating derived knowledge as a model's reading of the
evidence — the pipeline completes either way, and only the run record
distinguishes them ([#84](https://github.com/crismag/KAE-Memory/issues/84)).

## Why this rather than a similarity score

A vector store can tell you a passage resembles your query. It cannot tell you
whether anyone agreed with it, who disagreed, what it replaced, or whether the
sentence behind it was a requirement or a stray remark.

Provenance is what makes derived knowledge auditable rather than merely
plausible. It is also what makes rejection meaningful: a rejected candidate
keeps its evidence, so the same sentence can be read again later without the
project forgetting it once decided against that reading.

## Related

- [Knowledge lifecycle](knowledge-lifecycle.md)
- [Glossary](../glossary.md)
- [Access and mutation policy](../reference/access-and-mutation-policy.md)
