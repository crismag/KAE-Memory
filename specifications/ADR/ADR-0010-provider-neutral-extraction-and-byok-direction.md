# ADR-0010 — Provider-neutral extraction and BYOK product direction

- **Status:** accepted
- **Date:** 2026-07-27
- **Scope:** architectural direction only. No BYOK UI, credential storage, quota
  service, billing, multi-tenant administration, or additional provider adapter is
  authorised by this decision.
- **Amends:** ADR-0006 section 9 and its explicit deferral of cross-provider
  abstraction.
- **Numbering:** recorded as ADR-0010. ADR-0008 and ADR-0009 were taken by the
  embedding and frontend decisions while this was in review.

## Context

KAE-Memory currently performs extraction through `ExtractionPort`, with a
`DeterministicExtractionAdapter` for tests and demonstration fallback and a
`BedrockExtractionAdapter` for real model calls. This already isolates the
application from the provider SDK.

The first demonstrable release is intentionally constrained to one real model
provider. However, making Amazon Bedrock the permanent product credential and
billing boundary would create an avoidable operating-cost obligation for the KAE
operator. CockroachDB is also a paid managed service once free allowances are
exceeded. The product therefore needs a deployment direction in which customers
can supply and pay for their own model-provider credentials, while KAE sells the
memory, orchestration, provenance, recovery, and engineering workflow.

This decision distinguishes architectural compatibility from implementation
scope. The provider boundary must not be made Bedrock-specific, but the current
milestone must not expand into a multi-provider or billing workstream.

## Decision

### 1. Keep `ExtractionPort` as the application boundary

Agent and application code continues to depend on `ExtractionPort`, never on a
Bedrock, Anthropic, OpenAI, or other provider SDK. The current extraction request,
result, validation, prompt-version, schema-version, and typed-error contracts
remain authoritative.

The existing port is sufficient for the current extraction use case. This ADR
does not introduce a wider generic `AIProvider` interface prematurely.

### 2. Bedrock remains the only real adapter for the demonstration

The first demonstrable release continues to use:

```text
ExtractionPort
  ├── DeterministicExtractionAdapter   tests and documented fallback
  └── BedrockExtractionAdapter         approved live demo adapter
```

No OpenAI, direct Anthropic, Ollama, Azure OpenAI, Gemini, or other live adapter is
required before M11. AWS integration remains part of the demonstration goal.

### 3. BYOK is an approved post-demo product direction

A later product increment may allow a user, workspace, deployment administrator,
or self-hosted installation to select an approved provider and supply the
corresponding credential. The credential owner pays the model-provider bill.

BYOK means:

- KAE does not require all customer inference to run through an operator-owned
  key or AWS account;
- provider selection occurs at configuration or composition boundaries, not in
  agent logic;
- a deployment may still offer operator-managed credentials as a separately
  controlled mode;
- self-hosted and enterprise deployments may supply both their own model provider
  and their own database infrastructure.

BYOK does **not** mean accepting arbitrary credentials without validation,
secret-handling controls, provider allow-lists, auditability, or usage limits.

### 4. Usage governance is required before operator-funded public inference

Before a public or shared deployment invokes a paid model using an
operator-managed credential, the application must enforce usage limits before the
provider call. The eventual design must support at least:

- per-request input and maximum-output limits;
- per-user or per-workspace periodic allowances;
- an account-wide or deployment-wide circuit breaker;
- transactional reservation before invocation and reconciliation against actual
  usage afterward;
- immutable invocation records containing provider, model, measured usage,
  status, and owning run, but never the credential itself.

Provider-side throttling and cloud billing alerts are defence-in-depth controls,
not the authoritative quota mechanism.

No quota implementation is authorised in M7. M7 remains exclusively concerned
with durable worker continuation and recovery.

### 5. Credentials are references, not durable project memory

Provider credentials must never be written to knowledge items, messages,
`agent_runs.input_context`, logs, fixture files, reports, or repository
configuration. Later implementations must use an approved secret store or local
credential mechanism and persist only an opaque credential reference or provider
configuration identifier where necessary.

### 6. Capabilities may be provider-specific

KAE must not assume every provider supports the same structured-output, token
counting, prompt caching, thinking, tool-use, embedding, streaming, or batch
features. Adapters may expose only the capabilities required by their port and
must fail explicitly when a required capability is unavailable.

Provider abstraction does not require flattening all provider behaviour into an
imaginary common denominator. Domain-level outputs and failures are normalised;
provider-specific request construction stays inside the adapter.

## Consequences

**Positive**

- The current implementation remains focused: one live adapter, deterministic
  tests, and no change to M7.
- Agent logic is protected from provider lock-in.
- A future BYOK deployment can keep model inference costs with the credential
  owner rather than making KAE subsidise heavy usage.
- Self-hosted and enterprise deployment models remain viable.

**Negative**

- Supporting another provider later still requires an adapter, capability tests,
  provider-specific secret handling, and evaluation of output quality.
- BYOK creates security, support, and user-experience obligations; it is not a
  zero-cost feature.
- Database, authentication, storage, and compute costs remain even when model
  usage is customer-funded.

**Accepted risk**

- The first release remains dependent on Bedrock for its live AWS demonstration.
  The deterministic adapter remains the fallback if the provider is unavailable.
- Usage governance is not yet implemented because no public operator-funded
  service is part of the current MVP.

## Explicitly deferred

- additional live provider adapters;
- provider-selection user interface;
- API-key collection and validation;
- secret-manager integration for user-supplied keys;
- per-user quotas, token reservation, usage ledger, and cost dashboards;
- subscriptions, billing, metering, and commercial packaging;
- customer-managed CockroachDB configuration;
- broad provider routing or automatic cheapest-model selection.

These items require a bounded post-demo requirement and task context. They must
not be absorbed into M7, M8, M9, M10, or M11 without an explicit scope change.

## Implementation guardrails

Until a later requirement authorises BYOK implementation:

1. Do not rename or generalise `ExtractionPort` solely to anticipate future
   providers.
2. Do not add provider SDK dependencies without an approved adapter task.
3. Do not place secrets in project state or durable memory.
4. Preserve provider and model identifiers plus measured usage in extraction
   results where the provider supplies them.
5. Keep live-provider tests opt-in; CI remains network-free.
6. Treat any public operator-funded demo as blocked until an application-level
   usage governor exists.

## Related

- [`ADR-0006-extraction-contract.md`](ADR-0006-extraction-contract.md)
- [`ADR-0007-worker-runtime-and-leases.md`](ADR-0007-worker-runtime-and-leases.md)
- `CURRENT_PROJECT_STATE.md`
- `DEVELOPMENT_PLAN.md`
