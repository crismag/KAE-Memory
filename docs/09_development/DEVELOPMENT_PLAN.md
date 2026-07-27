# Development Plan

## Objective

Take KAE-Memory from an implemented memory foundation to a demonstrable
product slice that proves persistent engineering memory, without allowing coding
agents to invent product or architecture decisions.

## Delivery strategy

Build vertical, independently verifiable slices. Each milestone below maps to a
status entry in [`../00_project/CURRENT_PROJECT_STATE.md`](../00_project/CURRENT_PROJECT_STATE.md)
and to a slice in [`CODEX_CLAUDE_EXECUTION_ROADMAP.md`](CODEX_CLAUDE_EXECUTION_ROADMAP.md).
A milestone is complete when its exit condition is demonstrable, `make check` is
green, and the project model is updated.

| ID | Milestone | Status |
| --- | --- | --- |
| M0 | Foundation | ✔ |
| M1 | Domain | ✔ |
| M2 | Persistence | ✔ |
| M3 | Product Experience | ✔ |
| M4 | Repository Realignment | ✔ |
| M5 | Persistent Memory Proof | ✔ |
| M6 | Agent Collaboration | ► current |
| M7 | Resilience and Recovery | open |
| M8 | Semantic Retrieval | open |
| M9 | Workspace and Reporting | open |
| M10 | AWS Demonstration | open |
| M11 | Demo Ready and Release | open |

## Completed groundwork

Phases previously labelled bootstrap, requirements, architecture, and work
breakdown are complete and are recorded as milestones M0–M3: repository and CI
foundation, domain contracts, knowledge persistence, and product experience
definition. Their outputs are the specifications, ADR-0001 to ADR-0003,
`src/kae_memory/`, and the product documents in `docs/05_product/`.

## M4 — Repository realignment ✔ complete

**Outcome:** repository documentation describes the system that exists, and the
quality gate is green again.

**Work:**

- update the project model, README, requirements baseline, MVP scope, project
  brief, development plan, execution roadmap, and context index;
- add the first-loaded current-state page;
- fix timezone normalisation on knowledge rehydration;
- clear the ruff and formatting findings;
- add `alembic.ini` and `migrations/env.py` so revision 0001 is executable;
- commit `uv.lock`;
- test `run_transaction` retry, backoff, and exhaustion.

**Exit condition:** `make check` passes on `main`, and a new contributor can
state the project's position in under a minute from `CURRENT_PROJECT_STATE.md`.

**Permitted changes:** documentation, plus the defect fixes listed above.

## M5 — Persistent memory proof ✔ complete

**Outcome:** the memory claim is proven end to end before any interface exists.

**Delivered:** revision `0002` with projects, sessions, agent runs, messages,
relationships, and provenance links; domain contracts and repositories for each;
`MemoryService` as the single write boundary; provenance resolving to a real run.

**Success condition met:** Agent A writes something and Agent B retrieves it in
another run, verified in `tests/application/test_cross_run_proof.py`.

**Exit condition met:** AT-001 and AT-003 pass, alongside AT-005 and AT-007 at
the contract level.

## M6 — Agent collaboration ► current

**Outcome:** two agents collaborate through memory, not through conversation.
The contracts exist; this milestone gives them behaviour.

**Work:** Requirements Agent, Architecture Agent, deterministic extraction adapter
behind a port, human confirmation flow, context assembly, workflow state.

**Decided:** ADR-0006 — Bedrock behind an `ExtractionPort`, structured JSON outputs, fixture-based determinism.

**Success condition:** the Architecture Agent uses validated requirements created
in an earlier session.

**Exit condition:** AT-002 and AT-006 pass.

## M7 — Resilience and recovery

**Outcome:** compute is disposable.

**Work:** idempotency keys, bounded retry with backoff, durable run status, lease
expiry and reclaim, failure simulation, continuation from the last committed
checkpoint.

**Decided:** ADR-0007 — fencing-token leases, 30-second duration, additive revision `0003` for the lease columns. Waits only on M6.

**Success condition:** a new worker resumes after the previous execution stops.

**Exit condition:** AT-005 and AT-007 pass. This is the milestone the demo is
built on — do not let it slip.

## M8 — Semantic retrieval

**Outcome:** recall that finds knowledge the user did not name exactly.

**Work:** one approved embedding model, vector columns and index, semantic search
combined with structured filters, single-project scope, result explanations.

**Decided:** ADR-0008 — Titan Text Embeddings V2 at 1024 dimensions, `VECTOR(1024)`, cosine, one index. Needs a CockroachDB v25.4+ cluster for the vector tests.

**Exit condition:** a concept search returns related evidence, requirements, and
decisions with their sources and the reason each was included.

## M9 — Workspace and reporting

**Outcome:** the backend chain becomes visible as the product.

**Work:** the discovery workspace over real API state — start, discovery, memory
explorer, quality, and blueprint views; Review Agent and its findings; project
memory summary, agent execution history, traceability, unresolved conflicts,
validation coverage, and the recovery demonstration report; screenshots and demo
script captured as screens land.

**Blocked by:** OQ-011 frontend decision and its ADR.

**Exit condition:** AT-004 passes and the ten-beat narrative can be walked
locally.

## M10 — AWS demonstration

**Outcome:** the chain is deployed and compute is provably disposable.

**Work:** one container service, one worker, Secrets Manager or Parameter Store,
CloudWatch logs carrying run identifiers, `GET /health`, reproducible deployment,
documented teardown.

**Blocked by:** OQ-016 AWS runtime choice.

**Exit condition:** AT-008 and AT-009 pass — terminating the worker task results
in the interrupted run resuming with no duplicated knowledge and no manual
intervention.

## M11 — Demo ready and release

**Outcome:** a demonstration that survives a live audience and a package a
stranger can run.

**Work:** resettable demo environment, seed and cleanup commands, fallback outputs,
rehearsal, architecture diagram, deployment and local-development guides, security
notes, known limitations, presentation deck, demo video showing recovery, Devpost
narrative, release tag.

**Exit condition:** the ten-beat narrative runs twice from a clean reset, and a
reviewer who has never seen the project reproduces it from the documentation
alone.

## Critical path

```text
Realign repository and restore green build
  -> prove durable memory end to end
  -> prove two agents collaborating through it
  -> prove recovery after the worker dies
  -> add semantic recall
  -> make the chain visible as the product
  -> deploy the chain
  -> package and rehearse the demonstration
```

Memory before agents, agents before resilience, resilience before interface. The
interface is built last because it shows the chain, and there is no point showing
a chain that has not been proven.

## Controlled implementation loop

For each task:

1. issue one task-context bundle from `docs/10_prompts/TASK_CONTEXT_TEMPLATE.md`;
2. implement only within the allowed file scope;
3. run `make check` and the required tests;
4. review against requirements and architecture;
5. classify deviations rather than absorbing them;
6. update `project-model.yaml` and `CURRENT_PROJECT_STATE.md` before issuing the
   next task.

## Work not yet executable

| Work | Missing input |
| --- | --- |
| UI implementation | OQ-011 frontend decision and ADR |
| Project, session, message, relationship, AgentRun tables | OQ-010 physical schema |
| Real extraction | OQ-012 provider, prompt contract, and output schema |
| Readiness scoring | OQ-013 readiness model |
| Semantic retrieval | OQ-014 embedding model and index strategy |
| Worker and recovery | OQ-015 runtime and lease mechanism |
| AWS deployment | OQ-016 runtime choice |
