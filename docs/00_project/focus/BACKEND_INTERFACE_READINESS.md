# Focus Action — Backend Interface Readiness

## Repository ownership

This task belongs to **KAE-Memory**.

KAE-Memory owns domain behavior, persistence, application services, and the
backend adapters that expose those capabilities. KAE-Studio owns UI behavior,
client adapters, interview orchestration, and publication execution.

## Outcome

Make HTTP a first-class product adapter for KAE-Studio while retaining MCP as
the first-class agent adapter. Both adapters must invoke the same application
services and preserve equivalent domain behavior.

Parity means capability and invariant parity, not identical transport envelopes.

## Verified starting point

The MCP surface exposes substantially more of the application layer than the
HTTP `/v1` API. In particular, HTTP does not yet expose the complete retrieval,
document-ingestion, clarification, context-assembly, and classification
capabilities required by Studio.

Classification is also under-exposed: classified spans and operational records
are visible only indirectly, their lifecycle actions are incomplete, and
classifier-version supersession exists below the interface without a complete
caller path.

The HTTP API has no authentication boundary suitable for a remotely deployed
Studio client. No automated capability/parity register currently prevents MCP
and HTTP from drifting.

## Architectural decision to record

Create an ADR establishing:

- HTTP is KAE-Studio's backend transport.
- MCP is the coding-agent transport.
- Both are adapters over shared application services.
- Intentional adapter exceptions must be declared in a capability registry.
- Studio-specific view models and UI behavior do not enter KAE-Memory.

Do not make the browser an MCP client.

## Work packages

### 1. Capability inventory and route plan

Build an evidence-backed matrix from application services to MCP tools and HTTP
routes. Classify every gap as required for Studio, agent-only, internal, or
deferred.

At minimum assess:

- knowledge search and filtered reads;
- document ingestion and processing state;
- clarifications: list, answer, and resulting knowledge/readiness transitions;
- context assembly and deterministic package description;
- classified observations and operational state;
- confirmation, rejection, and correction coverage;
- project briefing/projection;
- project-scoped conversation reads and session projection.

### 2. HTTP exposure of existing capabilities

Add versioned HTTP routes only after their contracts are agreed. Reuse existing
application services; do not duplicate lifecycle, validation, readiness, or
idempotency logic in routers.

Required routes must support bounded responses, pagination/filtering where data
can grow, explicit revision identity, and honest queued/partial states.

### 3. Classification lifecycle closure

Provide independent, filterable, pageable reads for classified observations and
operational state. Define and expose permitted accept, reject, resolve, and
supersede transitions.

Wire classifier-version replacement to
`ClassificationRepository.supersede_older_versions` and preserve review
history. Verify every reachable domain state has an intentional command path or
is explicitly internal.

### 4. HTTP trust boundary

Before non-local Studio integration:

- require an approved bearer-token or API-key mechanism;
- enforce tenant/project authorization separately from authentication;
- retain explicit CORS allowlists;
- set request-size, rate, and timeout boundaries;
- keep database, provider, GitHub, storage, and publishing credentials out of
  the browser;
- return safe external errors and correlation identifiers.

Local development may use a documented development mode, but remote deployment
must fail closed.

### 5. Adapter capability and contract tests

Add a declared capability registry or parity matrix that fails when a capability
required on both adapters is exposed by only one.

Tests must prove that HTTP and MCP reach the same application behavior for:

- validation and lifecycle transitions;
- idempotency;
- revision and provenance semantics;
- readiness-affecting writes;
- partial/queued/error states.

Transport-specific serialization may differ.

## Separate architectural initiatives

The following are dependencies, not route-only work:

- first-class modules, relationship operations, traversal, and scoped readiness;
- durable deliverable identity and metadata;
- publication records and lifecycle;
- project-scoped interview projections if they require new durable semantics.

Do not invent these concepts inside an HTTP router merely to satisfy the current
Studio prototype.

## Explicit exclusions

- Studio components, hooks, frontend state, or page models;
- AI-provider orchestration;
- artifact rendering or destination writes;
- settings UI;
- direct compatibility with every provisional method in Studio's mock
  interfaces.

## Acceptance criteria

- An ADR records HTTP and MCP adapter roles.
- The capability registry identifies required and intentional adapter exposure.
- Studio-required existing services have versioned HTTP contracts.
- Classification has a complete, tested interface lifecycle.
- Remote HTTP access has authentication and authorization boundaries.
- Cross-adapter tests detect future unintended divergence.
- No KAE-Studio implementation is added to this repository.

## First implementation instruction

Inventory the nine application services against the actual MCP tools and HTTP
routes, then draft the adapter ADR and route contract matrix. Do not start route
implementation until the Studio consumer contract has been reconciled in
KAE-Studio.
