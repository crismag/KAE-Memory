# CRIS-CIE Slim — Test and Risk Assessment

Status: **evidence-based**, 2026-08-01. Companion to `CRIS_CIE_SLIM_CURRENT_STATE.md`.

Suite executed: **284 tests across 35 files, all passing.** Coverage **59%** overall, ≈90% excluding the untracked `kae/` package.

## Test count is not the quality measure

284 passing tests with 90% coverage on committed code looks like a well-tested system. The classification below shows what those tests actually establish.

## Classification

| Class | Present | Evidence |
| --- | --- | --- |
| Unit tests of isolated helpers | **Many** — the bulk of the suite | `test_scoring`, `test_question_backlog`, `test_templates`, `test_embeddings` |
| Contract/schema tests | **Some** | `test_discovery_model`, `test_package_validator`, `test_session_model` |
| Provider-response fixture tests | **Yes** | `test_providers`, `test_model_client` via `MockClient`/`FixtureClient` |
| State-transition tests | **Some** | `test_checkpoint_engine`, `test_session_model`, `test_workflow_modes` |
| Integration tests | **CLI-level only** | `test_cli`, `test_interview_cli`, `test_workflow_demo` — in-process, offline providers |
| End-to-end interview tests | **Only against `mock`/`fixture`** | `test_ai_interview`, `test_interview_correctness` |
| Quality / scenario evaluations | **Absent** | no test asserts interview *quality* against a scenario |
| Failure / recovery tests | **Very thin** | missing-key and missing-SDK paths; nothing for corruption, concurrency, or partial writes |

## Do the tests reproduce implementation assumptions?

**Substantially, yes** — and this is the central risk.

The scoring tests verify that coverage arithmetic matches the discovery model. They do **not** ask whether the model is the right one. So `test_scoring` passes while the live run produces the outcome in the current-state report:

> readiness **100%**, `ready_for_generation`, gate **Clear** — with the same report's rubric returning relevance **fail** and efficiency **fail**, and two areas scoring 100% because they contain **no required fields**.

The tests confirm the implementation computes what the model says. The model says a project with zero integration and zero implementation detail is ready to generate. **A green suite is therefore consistent with an unsound result**, which is precisely why test count cannot stand in for acquisition quality.

The same pattern holds for the interview: `test_ai_interview` runs against `MockClient`, which returns pre-shaped turns. It proves the runtime parses, governs, and records correctly. It proves nothing about whether a real model asks good questions — that evidence exists only in `out/live/`, which is a recorded artifact, not a test.

## Untested behaviour that affects knowledge integrity

Ordered by consequence.

**1. The entire `kae/` package — 1,741 statements, 0% coverage, untracked.**
`knowledge_model.py` states a design contract: *"Every field value is sourced from a confirmed user statement, not inferred. Inferences and assumptions are recorded separately and labeled as such."* **Nothing verifies either clause.** This is the code most likely to be considered for KAE, and it is the least evidenced code in the repository.

**2. Live-provider extraction.** No test exercises `AnthropicClient`, `OpenAIClient`, `OllamaClient`, or `ClaudeCliClient` against a real endpoint. Malformed-response repair (`repair_ai_turn`) is tested only with hand-written malformed strings — not with the shapes real models actually emit.

**3. Concurrency on session files.** `session_store.py` writes JSON with no locking. Two processes on one session silently lose data. Untested, and unguarded. For a system whose value proposition is durable project knowledge, this is a correctness hazard, not a robustness nicety.

**4. Corrupted or partially written session state.** No test truncates a session file, interrupts a write, or loads a session from a newer schema version.

**5. Idempotency.** No concept exists anywhere. A retried turn creates a second record. There is no key, no fingerprint, no constraint.

**6. Supersession and correction semantics.** The v1.3 work claims corrections; no test asserts that the original answer survives as evidence after a correction, which is the property that makes provenance trustworthy.

**7. Contradiction retention.** `_CONTRADICTION_PROBES` in `scoring.py` is three hand-written negation/affirmation pairs over three fields. It will detect the cases it was written for and effectively nothing else. Presented in output as contradiction detection.

**8. Generated-output correctness.** No test asserts that a generated artifact contains only grounded statements, or that assumptions are labelled. Given zero provenance references in generated documents, an ungrounded statement cannot be detected by inspection either.

## Risk register

| # | Risk | Severity | Evidence | Mitigation if any Slim asset is adopted |
| --- | --- | --- | --- | --- |
| R1 | **Readiness certifies incompleteness.** 7 populated fields → "ready_for_generation". Empty areas score 100%. | **Critical** | `out/live/quality_report.md` | Never import Slim readiness. KAE-Memory remains sole readiness authority. |
| R2 | **A competing knowledge model enters KAE.** `kae/KnowledgeState` is a second authoritative-shaped store. | **Critical** | untracked, 0% covered, 1,741 stmts | Prohibit import. Acquisition state lives in Memory. |
| R3 | **Fixture output mistaken for capability.** The flagship package is `provider: echo`, self-described as "the ideal demo output". | **High** | `demo_manifest.json` | Never demo from `examples/outputs/`. Any demo names its provider. |
| R4 | **Generated context has no provenance.** Zero evidence references in any generated document. | **High** | grep across generated `.md` | KAE packages must trace every substantive statement; do not reuse Slim generation. |
| R5 | **Untracked code is 45% of the tree.** A clone differs materially from this working copy. | **High** | `git status` | Commit or discard before any decision depends on it. |
| R6 | **Silent data loss under concurrency.** No locking on session JSON. | **High** | `session_store.py` | Retire file persistence entirely. |
| R7 | **No idempotency.** Retries duplicate. | **Medium** | absent throughout | Memory's MCP-M1 idempotency covers this once acquisition runs through Memory. |
| R8 | **Contradiction detection is three hard-coded probes.** | **Medium** | `scoring.py` | Use Memory's findings; do not present Slim's as detection. |
| R9 | **Provider failures are terminal.** No retry, backoff, or rate-limit handling. | **Medium** | `model_client.py` | Memory's worker already has leases and retry. |
| R10 | **Two-month-stale main plus large uncommitted divergence.** | **Medium** | `724ac65`, 2026-05-29 | Establish which tree is authoritative before reassessment. |
| R11 | **Version 1.0.0 implies production readiness.** | **Low** | `pyproject.toml` | Documentation correction. |

## What would have to be true to trust Slim's acquisition claims

None of these hold today.

1. The `kae/` package is committed and covered by tests that verify its stated design contract.
2. A readiness model that counts evidence quality, not populated fields, and cannot score an empty area at 100%.
3. At least one scenario benchmark with a live provider, scored against criteria fixed **before** the run.
4. Generated artifacts carrying provenance for every substantive statement.
5. Concurrency and idempotency guarantees on whatever holds acquisition state.
6. Contradiction detection that generalises beyond three hand-written probes.

## Bottom line

The suite is honest about what it covers and silent about what matters. It verifies arithmetic, parsing, and CLI plumbing well. It does not — and structurally cannot, in its current shape — provide evidence about acquisition quality, knowledge integrity, or generated-output trustworthiness.

**The one genuine piece of quality evidence in the repository is `out/live/` — a recorded live run — and it simultaneously demonstrates a good interview and an unsound readiness verdict.**
