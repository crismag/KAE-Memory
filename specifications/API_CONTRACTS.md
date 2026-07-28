# API Contracts

**Status:** superseded in part. The open decisions below were settled by
[`ADR/ADR-0014-http-api-contract.md`](ADR/ADR-0014-http-api-contract.md), and the
implemented contract is the OpenAPI document the running API serves at
`/openapi.json`. This file remains the conceptual framing.

## Contract principles

- Separate commands that change state from queries that retrieve state.
- Require project and actor identity for protected operations.
- Use stable resource identifiers and explicit versions.
- Make write operations idempotent where retries are expected.
- Return typed, actionable errors.
- Preserve provenance and trace metadata across boundaries.

## Candidate resource groups

- Projects
- Agents
- Knowledge items
- Requirements
- Decisions
- Relationships
- Executions
- Context bundles
- Snapshots

## Candidate commands

- Create project
- Register agent
- Submit knowledge
- Validate or reject knowledge
- Supersede knowledge
- Link entities
- Start and complete execution
- Create snapshot

## Candidate queries

- Retrieve current item
- Retrieve item history
- Search project knowledge
- Traverse trace relationships
- Retrieve conflicts and gaps
- Assemble task context
- Inspect execution and audit history

## Error model

Errors should distinguish validation failure, unauthorised operation, missing resource, version conflict, duplicate/idempotent request, policy rejection, dependency unavailable, and internal failure.

## Event expectations

Important state changes may publish events such as knowledge submitted, validated, rejected, superseded, relationship created, execution completed, and conflict detected. Event transport is not yet selected.

## Open decisions

Settled by ADR-0014: protocol style, authentication (none, and the API is unsafe
to expose publicly because of it), pagination shape, schema evolution, and
consistency semantics.

Still open: event delivery beyond Server-Sent Events, public versus internal
exposure, rate limiting, and HTTP-level idempotency keys — the last deferred
because `start_run` is already idempotent on a caller-supplied key, so the
durable path is protected.
