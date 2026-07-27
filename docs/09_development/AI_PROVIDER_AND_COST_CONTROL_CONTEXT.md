# AI Provider and Cost-Control Development Context

## Purpose

This file gives future human and coding agents the minimum context needed to
extend KAE-Memory's model-provider support without turning the current demo into
an unbounded SaaS cost centre.

Load ADR-0008 before implementing anything described here.

## Current approved state

- Agent execution depends on `ExtractionPort`.
- `DeterministicExtractionAdapter` is used by tests and is the documented demo
  fallback.
- `BedrockExtractionAdapter` is the only approved live extraction adapter.
- `ExtractionResult` already records the model and optional usage data.
- CI must not contact a model provider.
- M7 is the current milestone and remains focused on worker recovery.

## Product direction

KAE-Memory is intended to sell durable engineering memory and workflow, not to
resell unlimited model tokens. A future deployment may therefore support Bring
Your Own Key (BYOK): the customer supplies approved provider credentials and pays
that provider directly.

The same principle may later extend to self-hosted infrastructure, including a
customer-managed CockroachDB deployment. This is a deployment and commercial
direction, not current implementation scope.

## Required boundaries

```text
Agent workflow
    -> ExtractionPort
        -> provider adapter
            -> provider SDK

Public request
    -> authentication
    -> application usage governor
    -> transactional allowance reservation
    -> ExtractionPort
    -> reconcile actual usage
```

Agent code must not know:

- which provider is selected;
- how credentials are obtained;
- who pays the provider bill;
- how quotas are stored;
- which provider SDK is in use.

## Future provider adapter acceptance criteria

A new provider adapter is acceptable only when it:

1. implements the existing extraction contract without leaking SDK types;
2. maps provider failures to the existing typed extraction errors;
3. returns the provider and model identity;
4. reports measured token usage when available;
5. enforces the same structured-output and domain validation guarantees, or
   documents and tests an equivalent mechanism;
6. has deterministic fixtures and no live CI dependency;
7. never logs or persists credentials;
8. includes a capability matrix identifying unsupported features.

## Future BYOK acceptance criteria

BYOK implementation is not complete merely because an API-key textbox exists. A
bounded implementation must cover:

- provider allow-list and model allow-list;
- credential validation without exposing the secret;
- approved secret storage or local-only credential handling;
- opaque credential references in application state;
- credential deletion and rotation;
- tenant or workspace isolation;
- redaction in logs, errors, reports, traces, and support output;
- clear ownership of provider charges;
- refusal to invoke when the credential cannot be resolved safely.

## Future usage-governor acceptance criteria

Before operator-funded inference is exposed publicly, implement an application
usage governor with both per-owner and global protection.

Minimum controls:

| Control | Requirement |
| --- | --- |
| Request count | bounded per user or workspace and period |
| Input size | rejected before provider invocation when over limit |
| Maximum output | fixed or policy-bounded for each model |
| Token allowance | reserved transactionally before invocation |
| Reconciliation | actual usage replaces the reservation after completion |
| Concurrency | bounded per owner and globally |
| Global circuit breaker | can disable all paid calls immediately |
| Invocation ledger | records owner, run, provider, model, usage, and outcome |

The reservation must be atomic. Two simultaneous requests must not both consume
the same remaining allowance.

Conceptual rule:

```text
estimated input tokens + configured maximum output tokens
    <= remaining allowance
```

When provider-native token counting is unavailable, use a conservative estimate
and retain the maximum-output reservation until actual usage is known.

## Suggested future persistence concepts

These names are illustrative, not an approved schema:

```text
provider_configuration
credential_reference
usage_policy
usage_period
usage_reservation
model_invocation
```

Do not create these tables during M7. Their schema belongs to the milestone that
first exposes operator-funded public inference or BYOK configuration.

## Deployment modes to preserve

The architecture should remain compatible with three eventual modes:

1. **Self-hosted/community:** customer provides database and model credentials.
2. **KAE-hosted with BYOK:** KAE hosts application and database; customer provides
   model credentials.
3. **Managed/enterprise:** either customer-managed or operator-managed model
   credentials under explicit commercial limits.

These are product options, not commitments for the hackathon release.

## What to do now

- Keep Bedrock behind `ExtractionPort`.
- Preserve model and usage metadata.
- Do not broaden the live-provider implementation.
- Do not add a BYOK UI or quota schema.
- Continue M7 recovery work.
- Revisit this context only when a bounded requirement authorises another
  provider, public paid inference, or deployment packaging.

## What not to claim

Do not claim that KAE currently supports BYOK, OpenAI, direct Anthropic, Ollama,
customer-managed CockroachDB, hard cost caps, or public multi-tenant inference.
The architecture permits those directions; the product does not yet implement
them.
