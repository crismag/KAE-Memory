# TASK-007 — M6 Agent Collaboration

**Status:** ready after ADR-0006 approval
**Milestone:** M6 · **Prompt:** AGENT-01

## Objective

Give the Requirements and Architecture agents behaviour, so that two agents
collaborate through durable memory rather than through conversation.

## Business purpose

M5 proved memory survives process death. M6 proves it is *useful*: that one
agent's confirmed output becomes another agent's input, with the handoff carried
entirely by the database.

## Success condition

> The Architecture Agent uses validated requirements created in an earlier
> session.

Not merely retrieves them — consumes them as its authoritative input and cites
them in what it writes.

## Related approved context

- `docs/02_requirements/MVP_REQUIREMENTS_BASELINE.md` — FR-004, FR-005, FR-009
- `specifications/ADR/ADR-0006-extraction-contract.md` — provider, prompt,
  schema, validation, failure mapping. **Authoritative.**
- `specifications/AGENT_EXECUTION_MODEL.md` — role scopes and prohibitions
- `specifications/ADR/ADR-0005-m5-physical-schema.md` — what a run may store
- `docs/05_product/UNIFIED_DEMO_NARRATIVE.md` — beats 2 to 4

## Expected outputs

- `ExtractionPort` protocol in the application layer.
- `DeterministicExtractionAdapter` returning committed fixtures.
- `BedrockExtractionAdapter` using the Anthropic SDK's Bedrock client, with
  `output_config.format` structured outputs per ADR-0006.
- Versioned system prompts `requirements.v1` and `architecture.v1`, committed to
  the repository.
- Requirements Agent: message → candidate knowledge, each with a source quote.
- Architecture Agent: **confirmed** requirements → decisions citing them.
- Context assembly that gives the Architecture Agent confirmed knowledge only.
- Output validation before any write, including the source-quote check.
- Provider failure mapping onto the run failure codes.
- Tests, including the cross-session collaboration proof.

## Constraints

- **No test may make a live model call.** CI runs against the deterministic
  adapter only.
- **Do not send `temperature`, `top_p`, `top_k`, or `budget_tokens`** — all four
  are rejected by the current models. Determinism comes from the fixture adapter,
  not from sampling configuration.
- Bedrock model IDs carry the `anthropic.` prefix. `anthropic.claude-opus-5` is
  the default.
- Check `stop_reason` before reading response content — a refusal returns HTTP 200
  with empty or partial content.
- `MemoryService` must not import the provider SDK. The port is the boundary.
- Knowledge writes and run status changes stay in one transaction (FR-010).
- No agent confirms knowledge, including its own.
- The Architecture Agent must not consume unconfirmed candidates or raw
  conversation as authoritative input. A missing input is reported as a gap.
- Only two roles in this task. The Review Agent is M9.
- No embeddings, vector columns, or semantic retrieval — that is M8.
- Prompts are additive: a correction is `v2`, never an edit to `v1`.

## Known decision the implementer must surface, not silently resolve

ADR-0006 sets the extraction `kind` enum to `actor`, `goal`, `rule`,
`constraint`, `requirement`, `decision`, `unknown`, `assumption`. The domain's
`KnowledgeItem.kind` is a free string today, and the product documents use a
partly different vocabulary for what the memory panel displays.

Decide whether `kind` becomes a domain enum or stays a validated string, apply it
consistently, and state which in the pull request. Do not let two vocabularies
survive — that is the drift the terminology table forbids.

## Allowed file scope

- `src/kae_memory/application/`
- `src/kae_memory/agents/` (new)
- `src/kae_memory/domain/` — only if the `kind` decision requires it
- `tests/`
- this task file for completion notes

## Prohibited changes

- revisions `0001` and `0002`
- user interface of any kind
- embeddings, vector columns, semantic retrieval
- the Review Agent
- cloud infrastructure or deployment configuration
- live provider calls in tests

## Acceptance criteria

1. The Requirements Agent turns a message into candidate knowledge, each item
   carrying a verified quote from that message.
2. Fabricated source quotes fail the run rather than producing knowledge.
3. The Architecture Agent consumes only confirmed requirements and cites them.
4. AT-006 passes: the Architecture Agent uses requirements confirmed in an
   earlier session.
5. Every provider failure maps to a typed run failure code.
6. The full suite runs offline.
7. `make check` passes.

## Required tests

- Cross-session collaboration: confirm requirements in session one, derive
  architecture in session two, assert the citation link.
- Source-quote verification rejects a fabricated quote.
- Schema validation rejects malformed output before any write.
- Each provider failure mode maps to the expected run status and error code.
- The Architecture Agent ignores unconfirmed candidates.
- Prompt and schema versions are recorded on the run.

## Stop conditions

Stop and report rather than guessing if: the `kind` vocabulary cannot be
reconciled without changing published behaviour; structured outputs cannot express
a required constraint; or the Bedrock client's behaviour differs from ADR-0006.

## Definition of completion

`make check` is green, AT-006 passes, no test touches the network, and the pull
request states the `kind` decision and its reasoning.
