# ADR-0006 — Extraction provider, prompt contract, and output schema

- **Status:** accepted
- **Date:** 2026-07-27
- **Closes:** OQ-012
- **Scope:** the M6 extraction path only. Not embeddings (M8), not generation (M9).
- **Amended by:** [`ADR-0010`](ADR-0010-provider-neutral-extraction-and-byok-direction.md),
  which lifts the deferral of cross-provider abstraction below. Bedrock remains
  the only approved live adapter; the port must not become Bedrock-specific.

## Context

M6 needs the Requirements Agent to turn a user message into typed candidate
knowledge, and the Architecture Agent to turn confirmed requirements into
decisions. Three things were undecided: which provider and model, what the prompt
contract looks like, and what shape the output takes and how it is validated.

The deployment target is AWS (FR-016), so the provider decision is effectively
already constrained. What is not constrained — and what this decision fixes — is
how output is validated before it reaches durable memory, and how the workflow
stays deterministic in tests and in the demonstration.

## Decision

### 1. Provider — Claude on Amazon Bedrock

Claude models on Amazon Bedrock, reached through the Anthropic SDK's Bedrock
client rather than a raw `bedrock-runtime` `InvokeModel` call.

- Client: `AnthropicBedrockMantle` (Python: `anthropic[bedrock]`), constructed
  with an explicit AWS region.
- **Model IDs on Bedrock carry an `anthropic.` prefix.** A bare first-party ID
  is a 400 on that endpoint.

| Role | Model ID (Bedrock) |
| --- | --- |
| Default for all three agents | `anthropic.claude-opus-5` |
| Cost-tuning alternative, if evaluation justifies it | `anthropic.claude-sonnet-5` |

Start on `anthropic.claude-opus-5`. Moving to Sonnet is an evaluation result, not
a default — and it is a one-line change because the port isolates it.

Authentication uses the standard AWS credential chain. No Anthropic API key is
introduced, and the model credential is separate from both the SQL credential and
the MCP service-account key (ADR-0004).

### 2. Port — the provider sits behind an interface

```text
ExtractionPort (protocol)
  ├── DeterministicExtractionAdapter   fixtures; tests and demo fallback
  └── BedrockExtractionAdapter         the real provider
```

The application depends on the port. `MemoryService` never imports the provider
SDK. Swapping models, or falling back to fixtures during the demonstration, is a
composition-root change.

### 3. Output schema — structured outputs, not prose parsing

Extraction requests constrain the response with `output_config.format` using a
`json_schema`. The model returns validated JSON; there is no regex, no
markdown-fence stripping, and no "please respond only with JSON" prompt-begging.

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["items"],
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["kind", "content", "confidence", "source_quote"],
        "properties": {
          "kind": {
            "type": "string",
            "enum": ["actor", "goal", "rule", "constraint", "requirement",
                     "decision", "unknown", "assumption"]
          },
          "content": {"type": "string"},
          "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
          "source_quote": {"type": "string"},
          "rationale": {"type": "string"}
        }
      }
    }
  }
}
```

- `additionalProperties: false` is **required** on every object by the structured
  outputs contract.
- `source_quote` must be a span from the submitted message. It is what makes
  FR-004's message-to-knowledge link auditable, and it is checked in validation
  (below) rather than trusted.
- `confidence` is an enum, not a number. Model confidence is supporting
  information and never substitutes for human confirmation (FR-005).
- Numeric and string constraints (`minLength`, `maximum`, …) are **not supported**
  by structured outputs. Enforce those in the domain layer, which already does.

### 4. Validation — before any write, in the domain

Structured outputs guarantee the shape, not the truth. Every item is additionally
checked in the application layer before it becomes a `KnowledgeItem`:

1. `kind` is in the approved enum;
2. `content` is non-empty after stripping;
3. `source_quote` actually occurs in the source message — a fabricated quote
   fails the run rather than producing untraceable knowledge;
4. the item count is within a configured ceiling.

A validation failure fails the whole batch. Partial writes are not permitted —
knowledge and run status commit together (FR-010), so a batch either lands
entirely or not at all.

### 5. Prompt contract — versioned, cached, and recorded

- Each role has a **versioned** system prompt: `requirements.v1`,
  `architecture.v1`, `review.v1`. Prompts live in the repository, not in the
  database.
- The prompt version and schema version are recorded in `agent_runs.input_context`
  so any knowledge item can be traced to the exact prompt that produced it.
- The system prompt and schema are stable across requests and carry a
  `cache_control` breakpoint; the message being extracted goes last, after the
  breakpoint. Prefix caching is a prefix match — putting anything volatile
  (timestamps, message IDs, run IDs) ahead of the breakpoint silently defeats it.
- Prompts are additive: correcting one means `requirements.v2`, not editing v1,
  so historical provenance stays accurate.

### 6. Determinism does not come from sampling parameters

**`temperature`, `top_p`, and `top_k` are rejected by the current models** — a
request carrying them returns 400. The roadmap's "deterministic test fixtures"
therefore cannot be implemented as `temperature=0`, which is the obvious and
wrong reading.

Determinism comes from the adapter, not the sampling configuration:

- tests run exclusively against `DeterministicExtractionAdapter`, which returns
  recorded fixtures and never opens a socket;
- the demonstration has the same adapter available as a documented fallback;
- fixtures are captured from real responses and committed, so they drift only
  when someone deliberately re-records them.

No test in CI may depend on a live model call.

### 7. Request configuration

| Setting | Value | Reason |
| --- | --- | --- |
| Thinking | on (the default on Claude Opus 5) | Omitting the parameter runs adaptive thinking |
| `effort` | start at the `high` default, then sweep down | `low`/`medium` are strong on this model and are the main cost lever |
| `max_tokens` | generous | It caps thinking **plus** response text, so a tight value truncates mid-answer |
| Streaming | when `max_tokens` is large | Avoids SDK HTTP timeouts |
| `tool_choice` | unused | Extraction returns a document, not a tool call |

Do **not** send `temperature`, `top_p`, `top_k`, or `budget_tokens` — all four are
rejected.

### 8. Failure behaviour

Provider outcomes map onto the run failure codes in
[`../AGENT_EXECUTION_MODEL.md`](../AGENT_EXECUTION_MODEL.md):

| Outcome | `error_code` | Retryable |
| --- | --- | --- |
| Provider unavailable, throttled, or 5xx | `provider_unavailable` | yes, bounded |
| Timeout | `provider_timeout` | yes, bounded |
| `stop_reason: "refusal"` | `provider_refused` | no |
| `stop_reason: "max_tokens"` — truncated | `output_truncated` | yes, once, with a higher ceiling |
| Schema validation failure | `invalid_output` | yes, bounded |
| Source-quote check failure | `unverifiable_output` | no |
| Retry budget exhausted | `retry_budget_exhausted` | terminal — `abandoned` |

**`stop_reason` is checked before reading response content.** A refusal returns a
successful HTTP 200 with empty or partial content, so code that indexes the first
content block unconditionally breaks on it.

Non-retryable outcomes surface as quality findings rather than silent failures.

### 9. What is never stored

Per ADR-0005, `agent_runs` records bounded structured state only. Specifically
**not** stored: full prompts, raw provider responses, credentials, or model
internals. Stored: prompt and schema version, model ID, token usage, the
validated output summary, and typed failure information.

## Bedrock capability boundaries

Available on Bedrock and used here: structured outputs, adaptive thinking and
effort, prompt caching, token counting, tool use.

**Not available on Bedrock** — do not design around them: the Files API, the
Batches API, server-side web search and web fetch, code execution, and automatic
prompt caching (manual `cache_control` breakpoints work; the automatic top-level
form does not).

One provider-specific trap for later milestones: on Bedrock, a forced
`tool_choice` requires thinking to be explicitly disabled. Extraction does not use
forced tool choice, so M6 is unaffected — but any future tool-forcing path must
account for it.

## Explicitly deferred

- **Embeddings.** M8, separate decision (OQ-014). Bedrock hosts embedding models,
  but neither the model nor the index is chosen here.
- **Generation.** Blueprint prose is M9.
- **Provider fallbacks and cross-provider abstraction.** One provider, one port
  for this milestone. Amended by ADR-0010: provider neutrality is approved as
  direction, and no second live adapter is authorised before M11.
- **Batch extraction.** The Batches API is unavailable on Bedrock, and the demo is
  interactive.

## Consequences

**Positive.** Output shape is guaranteed by the API rather than by parsing. The
provider is one adapter behind a port, so the model choice is reversible and tests
never touch the network. Provenance is complete: every knowledge item resolves to
a run, a prompt version, and a quoted span of a real message. No new credential
class is introduced.

**Negative.** Bedrock lacks several first-party features, so anything later that
needs the Files or Batches API requires a provider decision to be revisited.
Structured outputs cannot express numeric or length constraints, so validation is
split between the schema and the domain. First use of a new schema pays a
compilation latency cost before the 24-hour schema cache warms.

**Accepted risk.** Extraction quality is unmeasured (KG-002). The source-quote
check catches fabricated attribution but not a plausible misreading, which is
exactly what human confirmation exists for.

## Related

- [`../AGENT_EXECUTION_MODEL.md`](../AGENT_EXECUTION_MODEL.md) — run status, retry, and continuation
- [`ADR-0004-mcp-inspection-only.md`](ADR-0004-mcp-inspection-only.md) — write boundary and credential separation
- [`ADR-0005-m5-physical-schema.md`](ADR-0005-m5-physical-schema.md) — what `agent_runs` may store
- [`../../docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md`](../../docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md)
