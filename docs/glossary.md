# Glossary

The words KAE-Memory uses, meaning what the code means by them. Where a term is
also an everyday word, the everyday sense is not the one that applies.

Two distinctions carry most of the confusion, so they come first.

**Kind and lifecycle are independent.** *What* something is (`assumption`,
`rule`, `unknown`) is not *how firmly it is held* (proposed, validated). An
assumption can be proposed or confirmed. `unknown` is a kind, not a status.

**Recording is not agreeing.** Anything submitted becomes a candidate. A person
confirms it, or it stays a candidate. Nothing an agent submits changes what the
project holds as agreed.

---

## Project and conversation

**Project** — the unit everything belongs to. Knowledge, sessions, modules,
readiness and deliverables are scoped to one, and nothing crosses between them.

**Session** — one continuous stretch of conversation about a project. A project
may have several over its life; what was established in one is available in the
next, which is the point of the service.

**Message** — one turn in a session, stored as it was said. A message from a
person queues extraction. A message from an agent does not, deliberately: an
agent's output re-entering as evidence for its own next inference manufactures
confidence out of nothing.

**Observation** — something submitted as evidence, through
`kae_submit_observation` or a conversation message. Evidence, not conclusion.

---

## Knowledge

**Knowledge item** — one thing the project holds, with a kind, a lifecycle
state, a version history, and provenance back to what produced it.

**Kind** — what an item is. Eight, from `KnowledgeKind`:

| Kind | What it records |
|---|---|
| `actor` | A person or system that participates |
| `goal` | Something the project is trying to achieve |
| `rule` | Something that must hold |
| `constraint` | A limit the solution has to respect |
| `requirement` | Something the system must do |
| `decision` | A choice that was made |
| `assumption` | Something taken as true without confirmation |
| `unknown` | Something extraction could not determine and did not guess |

`unknown` is worth dwelling on. It is the model reporting the limit of what the
evidence supports, rather than filling a gap with something plausible. An
`unknown` is often more useful than a confident guess, because it names a
question someone can answer.

**Lifecycle state** — how firmly an item is held. Four, from `LifecycleState`:

| State | Meaning | Can become |
|---|---|---|
| `proposed` | A candidate. Derived or submitted, not agreed | `validated`, `rejected` |
| `validated` | A person confirmed it | `superseded` |
| `rejected` | A person refused it | *(terminal)* |
| `superseded` | Replaced by a later version | *(terminal)* |

`validated` is the internal word for what the interfaces call **confirmed**.
Both appear; they are the same thing.

Rejected and superseded are terminal. Nothing returns from them, and rejected
items are **retained** rather than deleted — what a project decided against is
part of what it knows.

**Proposed knowledge** — an item in `proposed`. Everything extraction produces
starts here.

**Confirmed knowledge** — an item in `validated`. Only a person's review puts it
there. See [Reviewing knowledge](workflows/review-knowledge.md).

**Correction** — replacing an item's content with a new version. The previous
version is kept; history is append-only, and supersession never deletes.

**Provenance** — the chain from an item back to the message, document or run
that produced it. Retrievable through `GET /v1/knowledge/{id}/trace`.

> **Limitation.** The `reviewer` recorded against a confirmation is
> caller-supplied and unattested. Provenance is reliable about *what* was
> confirmed and *when*, and only as reliable as the caller about *who*. See
> [VG-3](../specifications/VERIFICATION_GATES.md).

**Extraction** — deriving candidate knowledge from evidence. **Asynchronous:** a
run is queued and completes on its own schedule, so a message may be stored
before anything is derived from it. Without model access, extraction falls back
to a deterministic fixture and run summaries say so.

**Classification** — assigning an item to a discovery area.

---

## Gaps and questions

**Clarification** — a question derived from what the project does not yet know.
Generated from findings, not authored by a person. Listing them **materialises**
them, which is why it is a POST and not a GET.

**Discovery area** — a topic a project needs to cover: problem and value, users
and stakeholders, scope, functional requirements, quality attributes, domain
model, constraints, acceptance criteria, interfaces, delivery context.

**Readiness** — how much of the project's discovery areas are covered.
**Advisory, never a gate.** An area holding only candidates is *partial* and
earns half credit; one meeting its minimum of confirmed items is *sufficient*
and earns full. So it moves on extraction and moves further on agreement — but
it does not move because a conversation was long, only because the conversation
produced knowledge.

**Blocker** — something recorded as preventing progress, tracked separately from
gaps.

---

## Retrieval and context

**Retrieval** — finding relevant knowledge or document chunks, by meaning rather
than keyword.

> **Limitation.** The relevance threshold was fitted to a small corpus and the
> margin is narrow. See [VG-2](../specifications/VERIFICATION_GATES.md) and
> [Retrieval and search](workflows/retrieve-and-search.md).

**Context assembly** — building a bounded package of what an agent needs for a
task, rather than everything the project knows. Reports what it could not
resolve instead of omitting it silently.

**Context package** — the result. Bounded, and it names its own gaps.

---

## Structure and output

**Module** — a named part of the system being built. Modules carry relationships
and can be traversed for build order.

> Modules are reachable **over MCP only**, by decision — see
> [Modules and dependencies](concepts/modules-and-dependencies.md).

**Relationship** — a typed link between modules, such as a dependency.

**Deliverable** — a recorded output with an identity, a manifest and provenance.

**Manifest** — what a deliverable contains, with per-artifact hashes.

**Rendered / published** — rendered means produced; published means written to a
destination. Distinct states: something can be rendered and never published.

---

## Interfaces

**Adapter** — a way in. Two: **MCP** and **HTTP**, peers over the same
application services (ADR-0023).

**MCP tool** — one callable operation on the MCP adapter. 30 declared; 13 of
them change state.

**Capability** — a declared unit of function, recorded with where it should be
reachable. 43 declared: 25 on both adapters, 12 HTTP-only, 5 MCP-only, 1
internal. See the [capability matrix](reference/capability-matrix.md).

**Response tier** — how much detail a response carries. Detail levels are
`summary`, `standard`, `diagnostic`; prose levels `none`, `minimal`, `concise`,
`standard`; profiles `economy`, `regular`, `detailed`, `custom`.

**Application contract** — a supported interface. The way clients act on
KAE-Memory.

**Persistence schema** — the database tables. **Not an interface.** Domain rules
live in application code, not in the schema, so a direct write produces state no
rule ever checked (ADR-0027).

**Provider** — the database engine. **PostgreSQL with pgvector** is the target,
hosted on Amazon RDS. See [persistence and providers](architecture/persistence-and-providers.md).

---

## Neighbours

**KAE-Studio** — the product interface. A separate repository. KAE-Memory
renders nothing (ADR-0026).

**CIE** — the interview and conversation layer. A separate repository.

**KAE-Ecosystem** — private, holding cross-repository planning and
infrastructure. Not required to use KAE-Memory.

---

*Terms are defined here once. Other pages link rather than restate: a definition
copied is a definition that drifts.*
