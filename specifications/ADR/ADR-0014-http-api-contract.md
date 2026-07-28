# ADR-0014 — HTTP API contract

- **Status:** accepted
- **Date:** 2026-07-28
- **Closes:** the open decisions in `API_CONTRACTS.md`
- **Depends on:** [`ADR-0009`](ADR-0009-discovery-workspace-frontend.md), [`ADR-0004`](ADR-0004-mcp-inspection-only.md)
- **Milestone:** M9 — the first step of ADR-0009's sequence, API contract →
  generated client → UI

## Context

`API_CONTRACTS.md` was written as a conceptual contract and says so: *"endpoint
syntax is not approved."* It left protocol style, authentication, pagination,
filtering, event delivery, schema evolution, public versus internal contracts,
and per-operation consistency undecided.

ADR-0009 settled two of those — **versioned REST/JSON**, and **Server-Sent
Events** for run updates — while deciding the frontend. This decision settles the
rest, because the client is generated from the contract and cannot be generated
from an unapproved one.

## Decision

### Framework and shape

**FastAPI**, served by **uvicorn**, as an optional `api` extra. The core stays a
library (ADR-0002): `pip install kae-memory` gets the domain, persistence, and
application layers with no web framework attached.

FastAPI is chosen for one reason that outranks the others — it emits an
**OpenAPI document from the same type annotations the code is already checked
against**. ADR-0009 requires a generated client, and a hand-maintained schema
beside `mypy --strict` types is a second source of truth that will drift.

### Versioning

Every resource lives under `/v1`. `GET /health` is deliberately **unversioned**:
FR-017 specifies that path, and an operational probe should not move when the
business contract does.

Additive change — new fields, new endpoints — happens within `/v1`. Removing or
retyping a field requires `/v2`. Clients must ignore unknown fields.

### Authentication: none, and the API must say so

The MVP scope defers authentication, teams, roles, and multi-user projects, and
FR-017 requires `/health` to work without it. So there is **no authentication**.

That is a scope decision, not an oversight, and it makes this API **unsafe to
expose publicly**. Any deployment must keep it behind a network boundary. This is
recorded here and in the deployment README rather than left for someone to infer
from missing middleware.

The application layer already refuses to let this become a data-integrity
problem: every write goes through `MemoryService` or `ReadinessService`, which
own the invariants (ADR-0004). The API is a transport, not a second place where
rules live.

### Error model

One envelope for every failure, with a stable machine-readable `code`:

```json
{ "error": { "code": "knowledge_not_found", "message": "...", "detail": {} } }
```

| Condition | Status | Code family |
| --- | --- | --- |
| Request body fails validation | 422 | `validation_failed` |
| Referenced resource does not exist | 404 | `*_not_found` |
| Domain invariant violated | 422 | `domain_invariant_violated` |
| Illegal lifecycle or run transition | 409 | `invalid_*_transition` |
| Retry budget exhausted, dependency down | 503 | `dependency_unavailable` |
| Anything else | 500 | `internal_error` |

Domain errors map by **type**, not by string matching. `DomainInvariantError`,
`InvalidLifecycleTransitionError`, and `InvalidRunTransitionError` already exist
and already carry the meaning; the API translates them rather than re-deriving
them.

A 409 is used where the conflict is a *state* conflict the client could resolve
by re-reading — confirming already-confirmed knowledge, resuming a finished run.
A 422 is used where the request was simply not valid input.

### Long operations never hold a request open

ADR-0009 is explicit: **the browser does not own the run.** Starting agent work
returns `202 Accepted` with a durable run identifier. The client polls
`GET /v1/runs/{id}` or subscribes to the event stream.

This is not a performance choice. A run that lives only as long as an HTTP
connection is a run that a closed laptop can lose, which is the exact failure
this project exists to eliminate.

### Pagination

Cursor-based, not offset-based: `?limit=&cursor=`, with `next_cursor` in the
response. Offsets skip and duplicate rows under concurrent inserts, and this API
sits over a distributed store where concurrent inserts are ordinary.

Default limit 50, maximum 200. **Not implemented in this slice** — list
endpoints currently return whole collections, which is honest for demonstration
volumes and dishonest at scale. Recorded so the client is not generated against a
shape that must change.

### Consistency

Every request is one transaction through the application layer, with the existing
bounded retry on CockroachDB serialization failures. Reads are not wrapped in
snapshots across endpoints: a client that wants a consistent view of readiness
reads a **snapshot**, which is already immutable and already carries the
knowledge revision it describes.

### Not decided here

Event *delivery* beyond SSE, public API exposure, rate limiting, and idempotency
keys on HTTP writes. The last one matters and is deliberately deferred:
`MemoryService.start_run` is already idempotent on a caller-supplied key, so the
durable path is protected. HTTP-level replay protection for the remaining writes
belongs with authentication, which does not exist yet.

## Consequences

**Positive.** The client can be generated from a schema that cannot drift from
the code. The contract is versioned before anyone depends on it. Errors are
machine-readable, so the UI can distinguish "confirm it again" from "reload the
page". The library stays installable without a web server.

**Negative.** FastAPI and pydantic enter the dependency tree, and pydantic
schemas duplicate some domain dataclass shape. That duplication is deliberate —
transport shape and domain shape change for different reasons — but it is real
work to keep aligned.

**Accepted risk.** No authentication. The API is safe only behind a network
boundary, and nothing in the code enforces that. It must be stated in every
deployment instruction rather than assumed.

**Deferred cost.** Unpaginated list endpoints will need a breaking change if they
ship to a client before pagination lands. The shape is recorded above so the
generated client anticipates it.

## Related

- [`ADR-0009-discovery-workspace-frontend.md`](ADR-0009-discovery-workspace-frontend.md) — the client this contract feeds
- [`ADR-0004-mcp-inspection-only.md`](ADR-0004-mcp-inspection-only.md) — writes go through application contracts
- [`ADR-0013-portable-runtime-and-optional-aws.md`](ADR-0013-portable-runtime-and-optional-aws.md) — the entrypoint this delivers
- [`../API_CONTRACTS.md`](../API_CONTRACTS.md) — the conceptual contract this decides
