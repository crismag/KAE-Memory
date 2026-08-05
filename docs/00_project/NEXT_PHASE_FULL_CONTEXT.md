# KAE-Memory Next-Phase Context

**Baseline:** `main` at `49c713e` on 2026-08-05  
**Status:** contributor handoff; verify the commit before implementation

## Purpose

KAE-Memory's major backend and MCP build-out is complete. The next phase is not
another general backend roadmap. It is a controlled transition from building the
memory engine to using it as the headless knowledge foundation for the KAE
product experience.

This file is the complete orientation. Implementation work must use one of the
focused action files below rather than treating this document as one large task.

## Product objective

KAE turns incomplete source material and an evolving interview into confirmed,
reusable, AI-ready project knowledge. The intended journey is:

1. create or select a project;
2. acquire documents, repositories, working-folder material, or curated input;
3. extract proposed knowledge with provenance;
4. interview the user to resolve gaps and ambiguity;
5. confirm, reject, or correct the proposals;
6. expose contradictions, blockers, decisions, and clarifications;
7. calculate readiness transparently;
8. assemble bounded, revision-pinned context;
9. describe and later render a development context package; and
10. reuse the retained knowledge across sessions, tools, and agents.

The output is not a transcript. It is an organised, traceable development
context that can include requirements, decisions, constraints, architecture,
modules, tasks, dependencies, configuration guidance, lineage, and prompts.

## Verified repository state

The codebase contains:

- selectable PostgreSQL/pgvector and CockroachDB persistence (ADR-0022);
- migrations through revision `0011`;
- durable projects, sessions, messages, runs, knowledge versions, provenance,
  review history, readiness, classifications, and operational updates;
- deterministic and Bedrock-backed extraction adapters;
- Titan V2 embeddings plus restartable re-embedding and measured retrieval;
- confirm, reject, and correct knowledge lifecycle operations;
- clarifications connected to extraction, confirmation, and readiness;
- document ingestion and bounded, hashed context assembly;
- deterministic package descriptions without rendering or publication;
- HTTP API, worker, local STDIO MCP server, deployment assets, and runbooks;
- T1 through T24 complete, including response compaction, pagination, integrity
  verification, and observation classification; and
- T25.2 complete: tools accept `project_key` as a stateless alternative to
  `project_id`. Server-side active-project state remains conditional and absent.

The last recorded full PostgreSQL quality evidence is 792 passing tests, 92%
coverage, clean Ruff, format, and strict mypy. T24 subsequently added code and
migration `0011`; rerun the current full gate before using the older count as a
release claim.

## Provider posture

PostgreSQL with pgvector is the practical development provider. CockroachDB
support is retained through the provider adapter and provider-aware migrations,
but the expired cloud trial is not a reason to delay product work. Provider
selection is explicit configuration. Tests must never infer a provider from a
URL or silently contact an external database. Embedding spaces with different
models, dimensions, or versions must never be mixed.

## Repository boundaries

### KAE-Memory owns

- durable project knowledge, lifecycle, provenance, and audit history;
- retrieval, classification, clarification, readiness, and assembly;
- backend configuration definitions, validation, and effective-value resolution;
- backend service messages;
- product-neutral Python, worker, API, CLI, and MCP control surfaces.

KAE-Memory is a headless service. Creating a project must not implicitly create
knowledge, sessions, or ingestion jobs.

### KAE-Studio owns

- the user interface and chat/interview experience;
- project setup and source-selection interaction;
- review, confirmation, readiness, blocker, and decision presentation;
- package preview, orchestration, and download interaction; and
- any future settings presentation.

### cris-cie-slim contributes

Specialised requirements and development-analysis agent behaviour that Studio
can orchestrate while Memory supplies durable context and write-back contracts.

## Immediate direction

1. Establish governed backend configuration and service-message controls.
2. Audit the embedded frontend, preserve useful requirements, and remove it from
   KAE-Memory when backend and demonstration dependencies are disproved.
3. Integrate KAE-Studio through a thin real workflow rather than extending the
   old KAE-Memory UI.
4. Keep genuine engine gaps explicit: module modelling and graph traversal,
   artifact rendering/publication, remote MCP tenancy/authentication, and live
   deployment proof are not complete.

## Focused action files

| Focus | File | Use when |
| --- | --- | --- |
| Configuration and messages | [`focus/CONFIGURATION_AND_MESSAGES.md`](focus/CONFIGURATION_AND_MESSAGES.md) | Auditing magic numbers, settings, loaders, validation, or backend messages |
| Frontend separation | [`focus/FRONTEND_SEPARATION.md`](focus/FRONTEND_SEPARATION.md) | Assessing or removing `frontend/` and related build/deploy assumptions |
| Studio integration | [`focus/STUDIO_INTEGRATION.md`](focus/STUDIO_INTEGRATION.md) | Building the first product workflow across Studio and Memory |
| Engine and proof gaps | [`focus/ENGINE_AND_PROOF_GAPS.md`](focus/ENGINE_AND_PROOF_GAPS.md) | Planning only the remaining backend capabilities or operational proofs |

## Constraints

- Preserve provider independence and embedding-space integrity.
- Preserve provenance, review history, deterministic assembly, and response
  integrity fields.
- Do not implement a settings UI or administration-policy framework here.
- Do not mechanically centralise every numeric literal.
- Do not store secrets in committed YAML or JSON.
- Do not make active-project focus an authorisation boundary.
- Do not add package bytes or publication side effects to Memory without a new
  persistence and ownership decision.
- Verify claims against code and the current checklist before updating status.
- Issue one bounded action context per implementation pull request.

## Superseded context handling

Historical milestone, hackathon, and architecture documents remain useful as
decision history. They are not the current queue. Where they disagree with this
file, `CURRENT_PROJECT_STATE.md`, ADR-0022, or the live MCP checklist, treat the
older claim as historical and update it before relying on it for implementation.

