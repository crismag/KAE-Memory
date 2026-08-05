# Focus Action — KAE-Studio Integration

## Outcome

Prove the KAE product experience through one thin workflow using real
KAE-Memory contracts. Studio owns interaction; Memory owns durable knowledge and
invariants.

## First vertical slice

1. Create or select a project in Studio.
2. Submit a bounded document or curated input.
3. Call Memory ingestion and display that extraction is queued, not complete.
4. Show proposed knowledge with provenance.
5. Confirm, reject, or correct one item.
6. Display readiness, blockers, and one clarification.
7. Submit an answer and show the extraction/confirmation transition honestly.
8. Assemble context pinned to a revision.
9. Preview the deterministic package description.

## Contract rules

- Studio supplies the active `project_id`; `project_key` is the stateless human-
  friendly alternative. Memory holds no active-project session by default.
- A recorded source, queued run, proposed item, confirmed item, and readiness
  change are different states and must remain visibly distinct.
- Studio never writes Memory tables directly or reimplements lifecycle rules.
- Artifact rendering and download orchestration remain outside Memory's current
  package-description operation.
- Mock adapters may support isolated UI tests, but the slice is not complete
  until it passes against a real local Memory service.

## Acceptance criteria

- The entire slice works across repository boundaries with documented setup.
- Refresh or reconnect does not require reconstructing authoritative state from
  browser memory.
- Every displayed knowledge claim can reach its Memory provenance.
- Failure and partial states do not read as success.
- No frontend implementation is added to KAE-Memory.

## First implementation instruction

Freeze the smallest API/MCP contract used by this slice, then implement project
creation through first proposal review. Expand only after that integration is
green.

