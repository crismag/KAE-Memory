# KAE with Memory — open questions

**Status:** product questions raised by the KAE with Memory package that must be
answered before the work they govern can be planned or built. Registered as
`OQ-019` onward in `project-model.yaml`, following the repository's existing
open-question convention.

A question is listed here when a wrong answer would be expensive to reverse.
Anything decidable by a careful implementer at the time is not a question.

---

## Blocking the next stage

### OQ-019 — What is directive memory, physically?

The precedence model depends on instructions outranking confirmed knowledge, and
nothing in the schema expresses that. Two shapes:

- extend `KnowledgeKind` with a directive value plus an authority column on the
  knowledge item;
- a separate `directives` table with its own lifecycle, scope, and precedence.

The choice determines whether readiness, retrieval, blueprint, and the review
findings all change. **Needs an ADR before any stage-2 work.**

### OQ-020 — Does authority belong to the item or to the retrieval policy?

Related but distinct. Authority could be a stored property of a memory item, or a
ranking rule applied at retrieval time against properties that already exist
(kind, lifecycle, provenance, scope).

Storing it invites drift between the stored value and the reason for it.
Computing it keeps one source of truth but makes precedence harder to explain to
a user. ADR-0012 chose *computed* for readiness; the same reasoning may apply.

### OQ-021 — What is the canonical acceptance set?

Four lists currently describe the same proof (alignment review, G4). Which
becomes the `AT-nnn` register, and do the existing AT-001..AT-009 stay
unchanged? Answering this unblocks writing any acceptance test for the wider
product.

## Memory model

### OQ-022 — Where do generated artifacts live?

Code, documents, and test files produced by KAE have no representation. Options:
knowledge items with a new kind, an `artifacts` table, or references to an
external repository with only metadata held here. This interacts with OQ-026.

### OQ-023 — What is retained verbatim, and for how long?

Prompts, responses, and tool outputs are named as event memory and are not
captured today. Retention, redaction, and deletion policy do not exist. **Prompt
capture must not ship before this is answered** — storing model transcripts
without a redaction rule is how a secret reaches a database.

### OQ-024 — What may be embedded, and what must stay structured-only?

Everything embeddable is not everything that should be embedded. Secrets,
superseded items, and rejected candidates arguably should never enter the vector
index at all, and today the chunk table has no lifecycle column to exclude them.

### OQ-025 — Is user preference memory project-, user-, or organisation-scoped?

The MVP has no user or organisation concept, so this cannot be answered inside
the current model. It depends on OQ-028.

## Autonomy and execution

### OQ-026 — Who owns the repository KAE works in?

Does KAE create and hold a workspace, operate on a user's clone, or push to a
remote it never holds? This determines the isolation model, the credential model,
and whether generated code ever executes on KAE's infrastructure.

### OQ-027 — What is the code-execution isolation boundary?

If an implementation agent runs tests, something executes untrusted generated
code. Container, sandbox, user's machine, or not at all. **No implementation
stage can be planned before this.**

### OQ-028 — What is the tenancy and access model?

The MVP assumes a single trusted operator with no authentication. Organisation
and workspace scope, cross-project memory, and approval gates for *other people's*
actions all presuppose identity. This is the root question behind OQ-025 and much
of the scope hierarchy.

### OQ-029 — What are the autonomy levels, and who sets them?

Approval-of-action does not exist today; only knowledge confirmation does. Which
actions always require a human, which are configurable, and where the setting
lives.

## Product and commercial

### OQ-030 — Who is the target user?

The discovery workspace suggests a product owner or founder. Bounded
implementation and repository understanding suggest an engineer. The two imply
different interfaces, different defaults, and different proof moments.

### OQ-031 — Does KAE compete with coding agents or orchestrate them?

The vision says KAE should perform *or coordinate* implementation. Performing it
means owning execution, isolation, and quality. Coordinating means integrating
with tools the user already has. The answer changes the MCP strategy
substantially.

### OQ-032 — What is the memory quality bar?

The operating model proposes ten quality measures. None has a threshold, and the
one measurable today — retrieval recall — sits at chance level offline and has
never been measured live. Without a threshold, "retrieval quality" cannot fail.

---

## Answered by existing decisions

Recorded so they are not reopened:

| Question | Settled by |
| --- | --- |
| May MCP write domain state? | No — ADR-0004, restated in the package |
| Is CockroachDB authoritative? | Yes — ADR-0003, ADR-0011 |
| Does correction delete history? | No — FR-006, implemented supersession |
| May a model confirm knowledge? | No — FR-005, confirmation is a human act |
| May a model record a contradiction? | No — ADR-0015 |
| Does the browser own a run? | No — ADR-0009, ADR-0014 |
| How many agent roles are authorised? | Three — FR-009, until an ADR adds one |
