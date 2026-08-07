# Clarifications and unknowns

Two ways KAE-Memory says it does not know something. They are different, and the
difference is useful.

**An unknown** is a knowledge item. Extraction met something the evidence did
not settle and recorded that, rather than guessing.

**A clarification** is a question derived from a gap in the project's coverage.
Nobody writes it; it falls out of comparing what a discovery area needs against
what has been confirmed.

---

## Unknowns

Kind `unknown`, lifecycle `proposed`, like any other candidate.

They come from extraction declining to invent. Asked to derive knowledge from a
sentence that does not contain it, a model can produce something plausible or it
can say what it could not determine. The second is more useful: a plausible
guess enters the project as a candidate someone may confirm without noticing it
was never said.

An unknown names a question with the evidence attached. Answering it usually
takes one sentence.

## Clarifications

Derived from findings — an area with no confirmed knowledge, or fewer confirmed
items than it needs.

Listing them **materialises** them, which is why it is a `POST` and not a `GET`.
A `GET` that mutates is one a browser prefetch performs again
([ADR-0023](../../specifications/ADR/ADR-0023-http-and-mcp-as-peer-adapters.md)).

Their wording is machine-facing on purpose — *"Discuss scope and boundaries and
confirm at least 1 item(s)"* is a description of a gap, not a question to read
aloud. Turning it into something worth asking a person is a conversational
layer's job, which is CIE's, not this component's.

## Assumptions

A third state, between the two. Something the project is proceeding on without
having confirmed.

Recorded explicitly so it is visible rather than implicit. An assumption can be
accepted, which is a decision someone made; it does not become confirmed
knowledge by going unchallenged.

## What moves readiness

Confirming knowledge in an area. Not asking questions, not answering them,
not the length of a conversation.

Readiness reflects what people have agreed to. A project can hold a long
transcript, many candidates and every clarification answered, and still read 0%
if nothing has been confirmed — and that number is correct.

## Answering

A clarification takes an answer with a disposition. **Deferring is not
answering:** it records that someone was asked and did not decide, which is a
different fact and stays open.

The distinction matters more than it looks. A question closed by deferral looks
settled to everything downstream, and the thing nobody decided quietly becomes
something nobody will be asked about again.

## Related

- [Knowledge lifecycle](knowledge-lifecycle.md) · [Glossary](../glossary.md)
- [MCP tools](../reference/mcp-tools.md) — `kae_get_clarifications`,
  `kae_answer_clarification`, `kae_list_assumptions`, `kae_record_assumption`
