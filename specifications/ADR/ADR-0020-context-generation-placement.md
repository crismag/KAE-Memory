# ADR-0020 — Context assembly is a Memory service; rendering is a separate delivery worker

- **Status:** proposed
- **Date:** 2026-08-01
- **Depends on:** [`ADR-0012`](ADR-0012-blueprint-readiness-model.md), [`ADR-0016`](ADR-0016-blueprint-generation-and-trace.md), [`ADR-0018`](ADR-0018-mcp-engineering-context-server.md), [`ADR-0019`](ADR-0019-cris-cie-slim-relationship.md)
- **Evidence:** `KAE_CONTEXT_PACKAGE_INVENTORY.md`, `KAE_PACKAGE_MODEL.md`, `KAE_PACKAGE_DELIVERY_AND_TOOLING.md` — historical evidence, held as archived development context

## Context

KAE's sellable output is a repository-ready development context package: specifications, decisions, plans, tasks, prompts, and tool instructions sufficient for a coding agent to implement the software consistently.

Four placements were considered for the generation logic: inside KAE-Memory as an application service; a separate delivery worker over versioned Memory context; partially in KAE-Studio; or another bounded component.

Two facts constrain the answer.

**Assembly and rendering are different concerns with different change rates.** Deciding *which knowledge belongs in a bounded module context, at which revision, with which trace references* is a knowledge operation — it requires the graph, the readiness rules, and provenance. Deciding *what the Markdown looks like for Cursor versus Claude Code* is a presentation concern that will change whenever a tool changes, which is often.

**Lineage must be authoritative.** An artifact's `source_knowledge`, `knowledge_revision`, and content hash are what make staleness computable. If those are recorded anywhere but Memory, staleness becomes a heuristic.

## Decision

**Split the responsibility at the assembly/rendering boundary.**

### 1. Context assembly is a KAE-Memory application service

Memory answers: *given this scope, this purpose, and this revision, which knowledge, decisions, evidence, and trace references constitute the bounded context?*

It returns a structured, versioned **context assembly** — not files. This extends `BlueprintService` (`ADR-0016`), which already renders confirmed knowledge with `grounded`/`derived`/`assumption` labels and full trace, with scope and purpose parameters.

### 2. Rendering is a separate delivery worker

A delivery component consumes a context assembly and produces files: templates, tool-specific shaping, prompt instantiation, package layout, manifest.

It holds **no knowledge logic**. It cannot decide what belongs in a package; it renders what assembly returned. Templates and prompts are versioned inputs, recorded in every manifest.

### 3. Lineage is recorded in KAE-Memory

Package identity, source knowledge per artifact, revision, generator and template and prompt versions, content hashes, publication outcome. Staleness is computed by Memory using the existing monotonic `knowledge_revision` and the comparison already implemented by `ReadinessSnapshot.is_stale_against`.

### 4. Publication is Studio's delivery subsystem

GitHub, local workspace via the installed agent, or S3 — per `ADR-0003` in KAE-Studio. Memory records that publication happened; it performs no commits, filesystem writes, or object transfers.

### 5. Authoritative generation logic is never in the browser

Studio composes, previews, selects targets, and publishes. It does not decide package contents. A browser-side generator would place knowledge decisions outside Memory and make them unversionable.

### 6. Readiness gates generation but does not forbid it

Five profiles — project definition, architecture, module implementation, integration, release planning (`KAE_PACKAGE_MODEL.md` §5). A package may generate below a threshold **provided** it declares confirmation state and carries unresolved gaps.

**Generation may be incomplete; it may never be silent.** This directly answers the failure found in `ADR-0019`, where an area with no required fields scored 100% and the package was declared ready.

## Consequences

### Positive

- Renderers and tool templates evolve independently of knowledge semantics — Cursor changing its rules format does not touch Memory.
- Lineage and staleness are exact, not heuristic, and reuse a mechanism that already exists and is tested.
- MCP, Studio, and the delivery worker consume **one** assembly contract, so a bounded module context is identical whichever client asks.
- Assembly is testable without rendering; rendering is testable against fixture assemblies.
- No browser-side generation, so packages cannot be produced from state Memory does not hold.

### Negative

- A new component to build, version, and deploy, with a contract between it and Memory.
- Two-step latency: assemble, then render.
- Template and prompt versioning becomes mandatory metadata, adding manifest surface.
- Purpose- and scope-bounded assembly is a structural gap in Memory today; this decision depends on closing it.

### Accepted risk

The assembly contract is likely to churn while the artifact taxonomy settles. Mitigated by versioning it (`kae.package.v1`) and by keeping the first milestone deliberately narrow.

## Alternatives rejected

**Everything inside KAE-Memory.** Rejected: tool-specific templates and prompt shaping would land in the knowledge service and change with every editor release, coupling the durable core to the most volatile requirement.

**Everything in a standalone generator reading Memory's API.** Rejected: assembly needs the graph, readiness rules, and provenance. A generator would reimplement them or query around them — the second source of truth `ADR-0019` was written to prevent.

**Partially in KAE-Studio.** Rejected explicitly. Package composition is a knowledge decision; placing it in the product UI makes it unavailable to MCP clients and CLI, and unversionable.

**Render in the browser and publish from there.** Rejected: credentials in the frontend, no server-side lineage, and no way to generate the same package for a non-Studio client.

## Required KAE-Memory changes

1. **Purpose- and scope-bounded context assembly** — extends `BlueprintService`; the load-bearing addition.
2. **Artifact and package lineage** — package manifest, per-artifact `source_knowledge`, content hash, revision.
3. **Publication records** — target, reference, outcome, hash.
4. **Staleness query** — which artifacts are outdated at the current revision, granular per artifact.
5. **Readiness profiles** — five scoped profiles, replacing one project-wide figure.
6. Modules, relationship write and traversal, module-scoped readiness — prerequisites for module packages.
7. `KnowledgeKind` and `RelationshipType` extension.

Items 6 and 7 are already recorded as structural gaps; 1–5 are new obligations created by this decision.

## Non-goals

Rendering logic in Memory · knowledge decisions in Studio or the browser · a second generator reading around the assembly contract · publication performed by Memory · treating a generated document as authoritative for its own content · overwriting human-authored or post-implementation files.

## Follow-up

- Define the assembly contract (`CIE-EVAL-3` schemas) before building either side.
- First end-to-end milestone: one module package, one target, full manifest and lineage.
- Decide whether the delivery worker ships inside KAE-Memory's repository as a separate process, or its own.
