# API Contracts

**Status:** conceptual contract; endpoint syntax is not approved.

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

Protocol style, authentication mechanism, pagination, filtering syntax, event delivery, schema evolution, public versus internal contracts, and consistency semantics per operation.
