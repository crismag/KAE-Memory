# Retrieval Architecture

**Status:** behavioural specification; the MVP subset is approved as FR-007 and
FR-013, 2026-07-27.

## Goal

Return the smallest trustworthy set of project knowledge needed for a declared task while preserving provenance, lifecycle state, conflicts, and traceability.

## Retrieval modes

- **Direct lookup:** exact project entity or identifier.
- **Structural retrieval:** entity type, status, ownership, stage, or relationship filters.
- **Trace retrieval:** follow supports, derives-from, implements, validates, blocks, and supersedes links.
- **Semantic retrieval:** relevance by meaning when structural queries are insufficient.
- **Temporal retrieval:** current state, state at time, or history.
- **Agent-role retrieval:** context shaped for requirements, architecture, implementation, testing, or review work.

## Context assembly pipeline

1. Authenticate actor and project access.
2. Record purpose, task, role, and requested scope.
3. Apply lifecycle and policy filters.
4. Retrieve structural and trace-linked candidates.
5. Optionally add semantic candidates.
6. Rank by approval state, direct trace relevance, freshness, and task fit.
7. Include unresolved conflicts and explicit gaps.
8. Apply bounded size or token budget.
9. Emit a reproducible ContextBundle manifest.

## Required output metadata

Every returned item should expose identifier, type, version, lifecycle state, provenance, relationship to the request, and whether it is current, superseded, conflicting, or inferred.

## Quality requirements

Retrieval must not present stale or rejected content as current truth. Compression must preserve requirement identifiers, decisions, constraints, conflicts, and source references. Missing knowledge must be explicit rather than filled by the retriever.

## MVP boundary

Approved for the MVP (FR-007, FR-013):

- direct lookup, structural retrieval, and trace retrieval;
- semantic retrieval using **one** approved embedding model and **one** index strategy;
- single-project scope on every query, with no cross-project reads;
- provenance, version, and lifecycle state returned with every result;
- an explanation of why each result was included.

Explicitly outside the MVP: hybrid ranking, reranking cascades, corpus-wide optimisation, learned relevance tuning, summarisation models, and caching layers. Retrieval that cannot answer confidently must say so rather than widen its scope.

## Open decisions

Ranking weights, embedding provider and model, vector index location, token budgeting, cache policy, evaluation dataset, and measurable precision/recall targets. The embedding and index choices are OQ-014 and block the semantic-retrieval milestone.
