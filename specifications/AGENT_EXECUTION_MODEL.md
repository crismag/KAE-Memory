# Agent Execution Model

**Status:** approved, and implemented as of M5.

`AgentRun`, the status model, idempotency, retry, and continuation are live in
`src/kae_memory/domain/execution.py` and `src/kae_memory/application/`. Agent
*behaviour* — what each role actually does — is M6.

Defines the durable execution contracts that make bounded multi-agent work
recoverable. Complements [`AGENT_COLLABORATION.md`](AGENT_COLLABORATION.md),
which defines roles and the collaboration protocol.

Nothing here authorises arbitrary agent swarms, general coding-agent hosting, or
unrestricted autonomous orchestration. Three predefined roles, bounded runs,
human confirmation.

## 1. AgentRun

An **AgentRun** is a durable record of one agent execution. It is a
first-class persisted entity, not a log line.

An AgentRun records:

| Field | Purpose |
| --- | --- |
| `id` | stable identifier, referenced by every knowledge version the run produces |
| `project_id` | owning project; no cross-project execution |
| `agent_id` | which registered agent identity ran |
| `role` | requirements, architecture, or review |
| `session_id` | the session the run belongs to |
| `status` | see the status model below |
| `input_context` | the ContextBundle the run was given, or a stable reference to it |
| `output_summary` | typed result, or the deviation report if the run did not complete |
| `attempt` | attempt number within the run's continuation chain |
| `idempotency_key` | caller-supplied key that makes re-submission safe |
| `started_at`, `updated_at`, `completed_at` | timing, all timezone-aware |
| `failure_reason` | populated only for `failed` and `abandoned` |

The existing `ExecutionId` value object becomes the AgentRun identifier, so
provenance already recorded on knowledge versions resolves to a real run.

### Status model

```text
pending -> running -> succeeded
              |
              +----> interrupted -> running (resumed)
              |
              +----> failed -> running (retried)
              |
              +----> abandoned
```

- **pending** — accepted and durably recorded, not yet started.
- **running** — claimed by a worker with a lease.
- **interrupted** — the worker stopped without reporting an outcome. Eligible for
  resumption by a different worker.
- **failed** — the run reported an error. Eligible for bounded retry.
- **succeeded** — terminal. Outputs are committed.
- **abandoned** — terminal. Retry budget exhausted or the run was cancelled.

Terminal states are never reopened. A new attempt is a new entry in the same
continuation chain, not a mutation of a finished one.

## 2. Durability requirements

1. An AgentRun is persisted **before** the agent does any work. A run that is not
   recorded did not happen.
2. Knowledge writes and the AgentRun status change that accompanies them commit
   in **one transaction**. There is no state in which knowledge exists without an
   accountable run, or a run claims success without its outputs.
3. Compute is disposable. Killing a worker at any point must leave the database
   in a state from which another worker can continue.
4. Recovery uses only durable state. It must never depend on in-process memory,
   local disk, or conversational context.

## 3. Idempotency

- Every run submission carries an **idempotency key**. Submitting the same key
  for the same project returns the existing run rather than creating a second.
- Re-running an interrupted or failed run must not duplicate knowledge. Knowledge
  writes are keyed by run and logical item so that a replayed attempt converges
  on the same result.
- A user submitting the same message twice produces one message record.

## 4. Retry and continuation

- Retry is **bounded**. A run has a maximum attempt count; exceeding it moves the
  run to `abandoned` and raises a visible finding rather than looping.
- Retries use exponential backoff. Serialization failures (SQLSTATE 40001) are
  already retried at the transaction boundary and are **not** run-level failures.
- Interrupted runs are reclaimed by lease expiry, not by a human pressing a
  button. A worker that stops holding its lease releases the run automatically.
- Continuation resumes from the last committed checkpoint. Partial output that
  was never committed is discarded, not reconstructed.

## 5. Agent roles

Exactly three roles are authorised for the MVP.

### Requirements Agent

- **Reads:** the project brief and user messages in the current project.
- **Writes:** candidate requirement knowledge and explicit gaps.
- **Must not:** write architecture decisions, or confirm its own output.

### Architecture Agent

- **Reads:** *confirmed* requirements only. It must not consume unconfirmed
  candidates or raw conversation as authoritative input.
- **Writes:** architecture decisions, each citing the requirements it derives
  from.
- **Must not:** invent requirements. A missing input is reported as a gap.

### Review Agent

- **Reads:** requirements and decisions across sessions.
- **Writes:** quality findings — unresolved gaps, contradictions, unsupported
  statements, and validation coverage.
- **Must not:** silently correct what it finds. Findings are proposals for human
  attention.

No agent confirms knowledge. Confirmation is a human act.

## 6. Write boundary

All agent writes go through KAE application contracts. Agents must not hold raw
database credentials or mutate tables directly. See
[ADR-0027](ADR/ADR-0027-application-contracts-are-the-write-path.md).

## 7. Failure behaviour

| Failure | Required behaviour |
| --- | --- |
| Worker killed mid-run | run becomes `interrupted` by lease expiry; another worker resumes |
| Model provider unavailable | run fails with a typed reason; bounded retry; deterministic fixture available for tests and demo |
| Malformed model output | run fails validation before any write; nothing is persisted |
| Duplicate submission | idempotency key returns the existing run |
| Database serialization failure | retried inside the transaction boundary; invisible to the run |
| Database unavailable | run stays `pending` or `interrupted`; no work is reported as done |
| Retry budget exhausted | run becomes `abandoned` and surfaces as a quality finding |

## 8. Acceptance

- **AT-005** — a run terminated mid-execution is resumed by a different worker
  and completes, with no duplicated knowledge.
- **AT-006** — the Architecture Agent consumes requirements confirmed in an
  earlier session and cites them in its output.
- **AT-007** — replaying a submission with the same idempotency key produces one
  run and one set of knowledge.
