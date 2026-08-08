# System context

Where KAE-Memory sits, and what it is not responsible for.

```mermaid
flowchart TB
    person([Person])
    agent([Coding agent /<br/>MCP client])

    subgraph kae[KAE ecosystem]
        studio[KAE-Studio<br/><i>product interface</i>]
        cie[CIE<br/><i>conversation and interview</i>]
        memory[<b>KAE-Memory</b><br/>durable project knowledge]
        artifacts[KAE-Artifacts<br/><i>generation and publishing</i>]
    end

    db[(PostgreSQL<br/>+ pgvector)]
    model[Model provider<br/><i>extraction</i>]

    person --> studio
    studio --> cie
    cie --> memory
    studio -->|HTTP| memory
    studio -->|HTTP| artifacts
    memory -.->|assembled context| artifacts
    agent -->|MCP| memory
    memory --> db
    memory -.->|async| model
```

The dotted line into KAE-Artifacts is **not yet wired**. See
[What is not here](#what-is-not-here).

---

## Who owns what

| Component | Owns | Does not |
|---|---|---|
| **KAE-Studio** | Everything a person looks at | Hold durable project state |
| **CIE** | Deciding what to ask and how | Persist knowledge |
| **KAE-Memory** | Durable knowledge, retrieval, context assembly | Render anything, or decide what a project should do |
| **KAE-Artifacts** | Turning knowledge into files, and publishing them | Hold knowledge, or decide what a project knows |

KAE-Memory is headless by decision
([ADR-0026](../../specifications/ADR/ADR-0026-kae-memory-is-headless.md)). It
ships no interface and builds none.

## Two kinds of client

**Agents** connect over MCP. They submit observations, read briefings, and ask
for module-scoped context. Some capabilities exist only here, because an
implementing agent is the consumer.

**Applications** connect over HTTP. Studio is the one that exists. Some
capabilities exist only here for the same reason in reverse.

The adapters are peers over the same application services
([ADR-0023](../../specifications/ADR/ADR-0023-http-and-mcp-as-peer-adapters.md)),
and the [capability matrix](../reference/capability-matrix.md) is the record of
where each difference is deliberate.

## The model is not the architecture

Extraction calls a model provider **asynchronously**, from the worker. Nothing a
client calls waits on it.

And nothing a model returns becomes project truth on its own — it becomes a
candidate. That boundary is why KAE-Memory can use a model without inheriting a
model's confidence.

Without provider access, extraction falls back to a deterministic fixture and
records that it did.

## Artifact generation, and what is not yet connected

KAE-Artifacts turns assembled knowledge into files — requirements, project
context, agent context, integration specifications — and publishes them to a
GitHub branch and draft pull request or to S3. It is implemented, and it does
**not** import a KAE-Memory type: it takes a provider-neutral structure that any
caller can fill in, and its own edge adapter converts an assembled context into
that structure.

That direction is deliberate. Generation depending on Memory's schema would make
every change here a change there.

**Not yet wired, and named so nobody assumes otherwise:**

| Missing link | Owner |
|---|---|
| Studio calling assemble-context and handing the result to KAE-Artifacts | KAE-Studio |
| A publication reference recorded back against the project | KAE-Memory |
| An HTTP client adapter for GitHub or S3 | KAE-Artifacts |

The third is what stands between the pipeline and a live publication. Until all
three exist, "Memory knowledge became a pull request" is a design, not a path
anyone has walked.

## What is not here

**Cloud provisioning.** This repository creates no cloud resources and ships no
provisioning automation. Deployment coordination for the wider ecosystem lives
outside the public component.

**A user interface.** Studio's, separately.

**Artifact generation.** KAE-Artifacts', as above. Memory holds what a project
knows; it does not render that into documents.

**Interview intelligence.** CIE's. KAE-Memory produces clarifications from
structural gaps; turning those into a conversation is not its job, and its
clarification text is machine-facing because of that.

## Related

- [Components](components.md) · [Persistence and providers](persistence-and-providers.md)
- [Security boundaries](security-boundaries.md)
