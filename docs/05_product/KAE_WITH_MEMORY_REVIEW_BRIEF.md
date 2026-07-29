# KAE with Memory — product-definition review brief

**Status:** received 2026-07-28. **Direction-setting input, not implementation
authority.** No review work has been performed against it yet.

**Target correction.** The brief names PR #30 on branch
`docs/kae-with-memory-product-definition`. That PR **merged on 2026-07-28** as
commit `1577ac9`, so the review it asks for now applies to those four documents
as they stand on `main`, and its output belongs in a **new** pull request.

**What this document is.** The originating instruction for refining the KAE with
Memory product-definition package. It is stored verbatim so the review, when it
happens, can be checked against what was actually asked rather than against a
recollection of it. Nothing here authorises implementation: the authoritative
statement of what exists remains
[`../00_project/CURRENT_PROJECT_STATE.md`](../00_project/CURRENT_PROJECT_STATE.md),
and the authorised requirement set remains
[`../02_requirements/MVP_REQUIREMENTS_BASELINE.md`](../02_requirements/MVP_REQUIREMENTS_BASELINE.md).

---

## Objective

Review and refine the new KAE with Memory product-definition package.

The purpose of this work is to define how KAE should function after the current
persistent-memory foundation is ready.

KAE must not remain only:

- a memory service;
- a product-discovery assistant;
- a requirements extractor;
- a knowledge browser;
- or a chatbot that recalls prior sessions.

KAE is intended to become a practical AI software-development system that can:

- receive a software or business idea;
- understand and clarify it;
- acquire knowledge from conversations, instructions, files, repositories, tools,
  agents, and execution results;
- preserve that knowledge in durable shared memory;
- plan and structure a software project;
- generate requirements, architecture, tasks, and implementation context;
- perform or coordinate implementation;
- review and test the result;
- reuse knowledge acquired in one phase during other phases;
- continuously update its understanding as the project changes.

### The central product claim

> KAE does not simply generate software from a prompt. It continuously learns the
> project it is building, persists what it learns, and makes that knowledge
> available to every agent and every later engineering activity.

Memory is therefore not a secondary archive. It is the shared engineering
substrate that allows KAE to behave as one continuing software-development
intelligence instead of a collection of disconnected agent sessions.

## Existing repository state

The current repository has already implemented substantial foundations:
persistent projects, sessions, messages, and knowledge; immutable knowledge
versions and provenance; lifecycle states; human confirmation; supersession
without deletion; Requirements and Architecture agents; Review Agent and quality
findings; durable AgentRun records; renewable leases and fenced worker claims;
worker checkpoints and recovery after worker death; CockroachDB-backed semantic
retrieval; readiness scoring and blockers; an HTTP API; cross-run and
cross-session memory proofs.

The current approved product framing is still primarily an AI Product Discovery
Workspace: a user begins with an incomplete idea and leaves with validated
engineering knowledge and a traceable development blueprint.

The new package expands the longer-term direction beyond discovery and blueprint
generation into actual software planning, development, review, and evolution.

### Important constraint

**Do not treat proposed future functionality as already implemented.** Verify
every capability against `src/kae_memory/`, `tests/`, `migrations/`,
`specifications/`, and `docs/00_project/CURRENT_PROJECT_STATE.md`.

The repository currently authorises **only three agent roles**: Requirements,
Architecture, and Review. Additional agents described in the package are
candidate future roles and are **not** implementation authority.

## Files in the package

Review these files together as one package.

1. **`docs/05_product/KAE_WITH_MEMORY_PRODUCT_VISION.md`** — the wider product
   proposition; how persistent memory supports active software development; the
   continuous acquire–persist–retrieve–apply–validate loop; how KAE differs from
   ordinary coding agents and passive knowledge repositories; user-visible proof
   moments; the relationship between the current discovery workspace and the
   wider product.
2. **`docs/06_architecture/MEMORY_AND_DATA_OPERATING_MODEL.md`** — what KAE may
   store; raw activity versus trusted project knowledge; the four memory layers;
   scope, authority, provenance, status, versioning, and supersession; retrieval
   and context assembly; write-back from agents; conflicting, stale, unverified,
   and superseded information; strict project isolation.
3. **`docs/06_architecture/AGENT_AND_MCP_FUNCTIONAL_MODEL.md`** — how agents
   access and contribute memory; current approved agents versus possible future
   agents; bounded task context; structured write-back; orchestration and
   approval boundaries; MCP and external-tool responsibilities; the rule that MCP
   must not bypass KAE domain contracts.
4. **`docs/02_requirements/KAE_WITH_MEMORY_FUNCTIONAL_REQUIREMENTS.md`** — a
   proposed functional and non-functional requirement register; expected
   behaviour for acquisition, storage, retrieval, cross-agent use, correction,
   implementation, review, and recovery; scenarios that can later become
   acceptance tests and milestone slices.
5. **`docs/CONTEXT_INDEX.md`** — indexes the package, explains when to load it,
   states that it is proposed product-shaping context, and prevents coding agents
   from reading it as implementation authorisation.

### The four memory layers

| Layer | Meaning |
| --- | --- |
| Event memory | What happened |
| Knowledge memory | What KAE understands |
| Directive memory | What future work must follow |
| Execution memory | What work is happening and what should happen next |

KAE may retain broad source material: conversations, user messages,
instructions, model prompts and responses, agent inputs and outputs, tool
invocations and results, documents, source-code observations, repository
metadata, requirements, decisions, plans, tests, failures, retries, checkpoints,
implementation discoveries, review findings, and generated artifacts.

**Stored information must not automatically become authoritative knowledge.**

> Conversation: *"Maybe we should use DynamoDB."*
> Later approved decision: *"CockroachDB is the authoritative persistence layer."*

Both should remain stored, but they must not be retrieved as equally
authoritative instructions.

## Product intent to preserve

These ideas are load-bearing and must remain clear throughout the documentation.

### 1. KAE must create software

KAE cannot be presented only as something that answers questions about an
existing project. It must eventually help a user move:

```text
Idea -> Discovery -> Requirements -> Architecture -> Plan -> Tasks
     -> Implementation -> Testing -> Review -> Deliverables -> Continued evolution
```

It should deliver value similar to, or greater than, systems that turn an idea
into a structured and understandable software-development starting point.

### 2. Memory must remain central

Memory must not be reduced to chat history. It must: persist beyond a context
window; survive process and session boundaries; not be overwritten by newer
prompts; preserve historical versions; remain queryable; be shared across agents;
be available at both project and detailed implementation level; distinguish
active from prior or superseded knowledge; preserve source evidence; and support
recovery and replay.

### 3. Knowledge must be actively applied

Storage alone does not prove KAE's value. Before an agent performs work, KAE
should assemble relevant context from memory.

> **Task:** implement password reset.
>
> **Retrieved memory:** authentication requirements; current user schema; email
> provider decision; token security policy; API conventions; logging standards;
> test framework; previous review findings.
>
> **Written back after implementation:** endpoint created; schema updated; tests
> added; new constraint discovered; one assumption invalidated; affected
> documentation identified.

```text
Acquire -> Persist -> Classify -> Retrieve -> Apply -> Validate -> Update -> Reuse
```

### 4. Agents must share project understanding

Agents should not rely on giant conversational handoffs. Each agent should
receive a bounded context package containing only the authoritative and relevant
information needed for its task. All agents read and write through KAE
application contracts.

```text
User input -> persistent source capture -> extraction -> candidate knowledge
  -> validation -> planning -> architecture -> task context assembly
  -> implementation -> testing and review -> discoveries written back
  -> project knowledge updated
```

### 5. Raw memory and trusted knowledge are different

KAE may store almost anything, but must preserve the distinctions between: raw
observation, candidate interpretation, confirmed fact, approved directive,
assumption, decision, contradiction, rejected item, superseded item, execution
state, and generated artifact.

**A vector match must never be treated as proof of authority.** Retrieval should
consider project scope, memory type, authority, lifecycle status, recency,
applicability, provenance, confidence, relationship to the active task,
contradiction state, supersession, and token budget.

### 6. Corrections must not erase history

> Old value: *reporting cycle is fixed at 30 days.*
> New value: *reporting cycle is configurable.*

KAE should preserve the original statement and its source, mark it superseded,
establish the replacement relationship, make the new statement active, ensure
later agents retrieve the current statement by default, and retain the old
statement for audit and explanation.

### 7. CockroachDB must be necessary, not decorative

CockroachDB remains the authoritative durable layer for projects, sessions,
messages, knowledge, versions, provenance, relationships, agent runs,
checkpoints, leases, execution state, semantic chunks and vectors, and readiness
and review state. The architecture should demonstrate why **both** transactional
durability and semantic retrieval matter.

### 8. MCPs are integration boundaries, not the domain model

MCP may be useful for repository access, documentation lookup, cloud inspection,
issue and pull-request operations, file systems, external knowledge sources, and
test and deployment tools.

**MCP tools must not directly mutate authoritative KAE domain state.** External
observations and MCP results are captured as evidence and pass through KAE
application services before becoming durable knowledge or directives. The
existing CockroachDB MCP policy stands: inspection and management only, no direct
domain writes.

## Required review work

### A. Check conceptual consistency

Determine whether the four documents describe one coherent product. Look for
contradictions between the product vision, memory model, agent model,
requirements, current approved MVP, existing architecture decisions, and
repository terminology.

Pay particular attention to whether the documents alternate between incompatible
framings: KAE as passive memory; as product-discovery tool; as autonomous
software factory; as engineering knowledge operating system; as multi-agent
development environment.

The intended framing is coherent: **KAE is a software-development system whose
differentiating capability is persistent, governed, shared engineering memory.**

### B. Protect the current implementation boundary

Verify the documentation does not falsely claim KAE already writes application
source code, owns a repository workspace, produces pull requests, runs tests
against generated software, deploys applications, contains all candidate future
agents, supports arbitrary MCP servers, or performs fully autonomous delivery.

Future capabilities should read as *proposed*, *candidate*, *planned*, *future*,
*requires ADR*, or *requires approved task*.

### C. Refine terminology

Use existing repository terminology wherever possible: Engineering Memory,
Project, Session, Message, Evidence, Knowledge, Candidate Knowledge, Confirmed
Knowledge, Provenance, Supersession, Traceability, Blueprint, AgentRun,
Continuation, Quality finding.

Avoid synonyms that fragment the domain language. Where new terms are necessary,
define them explicitly and decide whether they belong in `docs/CONTEXT_INDEX.md`.

### D. Review the memory taxonomy

Assess whether the four-layer model is complete and understandable. Answer:

- Is event memory distinct enough from execution memory?
- Are instructions best represented as directive memory?
- Where do generated artifacts belong?
- Where do repository snapshots and code summaries belong?
- Is user preference memory project-, user-, or organisation-scoped?
- How should inferred knowledge differ from explicit knowledge?
- How should memory promotion occur?
- What qualifies a memory item as authoritative?
- How should contradiction and supersession interact?
- What is retained verbatim versus normalised?
- What data should be embedded?
- What data should be retrievable only through structured queries?
- What should never be inserted into model context automatically?

**Do not redesign the database schema** in this review unless a clear requirement
demands it. Capture schema implications as open architecture questions.

### E. Review agent boundaries

Assess whether candidate responsibilities should be dedicated agents,
deterministic services, tools, orchestrator stages, or capabilities shared by
multiple agents. **Avoid a design with many named agents that map one-to-one to
software-development job titles.**

For each proposed role clarify: purpose, inputs, memory reads, allowed tools,
outputs, memory writes, human approval requirements, and failure and retry
behaviour.

Candidate future responsibilities named in the package: Discovery or Interview,
Planning, Repository Understanding, Implementation, Testing, Documentation,
Security or Compliance, Deployment, and Knowledge Curator or Consolidation.

### F. Review MCP strategy

For each integration category — source repository and Git hosting, file systems,
issue tracking, documentation and standards, cloud infrastructure, database
administration, test execution, build systems, deployment systems, external
research — establish what it may read, what it may execute, what evidence must be
captured, what requires human approval, what must pass through a KAE application
contract, and what must never be trusted automatically.

**Do not hard-code the product around MCP.** MCP is one adapter mechanism.

### G. Review proposed requirements

For each requirement, determine whether it is foundational, an MVP extension, a
near-term capability, a long-term capability, a duplicate, too vague, too broad,
an implementation detail rather than a requirement, or something that requires an
ADR, a data-model change, a security decision, or user-experience definition.

Each requirement should have a stable identifier, one primary behaviour, a clear
actor or triggering condition, an observable outcome, no hidden implementation
assumption unless deliberately architectural, and compatibility with the existing
domain model.

### H. Identify proof scenarios

The product must eventually demonstrate that memory changes the *quality* of
software development. At minimum, preserve and refine:

1. **Cross-agent reuse** — a requirement discovered by one agent is retrieved and
   applied by another without the user repeating it.
2. **Correction without forgetting** — an earlier instruction is superseded; later
   work uses the replacement while the original remains available as evidence.
3. **Implementation discovery propagation** — an implementation agent discovers a
   constraint affecting architecture, tests, documentation, and later tasks; KAE
   stores and propagates it.
4. **Grounded review** — the Review Agent compares implementation outputs with
   confirmed requirements and decisions rather than reviewing code in isolation.
5. **Bounded implementation context** — an implementation agent receives
   task-specific context rather than the entire project history.
6. **Durable continuation** — a worker dies during development work; another
   resumes from committed state without losing acquired knowledge.
7. **Project coherence** — a later feature reuses existing authentication,
   logging, retry, data-access, and testing patterns because KAE retrieves prior
   project knowledge.

## Expected deliverables

**Documentation improvements only. No application functionality.**

- corrected and refined versions of the four documents;
- any necessary improvements to `docs/CONTEXT_INDEX.md`;
- a concise list of unresolved product questions;
- a proposed promotion path for requirements;
- a recommended follow-up ADR list;
- a recommended staged product roadmap from the current MVP to KAE with Memory;
- a final consistency review.

Optionally `docs/05_product/KAE_WITH_MEMORY_OPEN_QUESTIONS.md`, covering product
scope, autonomy boundaries, memory authority, user and organisation scope,
repository ownership, tool execution, approval gates, agent roles, model
providers, MCP integrations, security and secrets, generated-code
responsibility, testing and deployment, and commercial target user.

### Follow-up architecture decisions

**Do not write ADRs in that PR unless explicitly authorised.** Identify
candidates such as: memory classes and authority precedence; context assembly and
retrieval policy; agent capability and role model; agent write-back contract;
repository workspace ownership; external tool and MCP execution boundary; human
approval gates; software artifact and evidence model; user, organisation, and
cross-project memory scope; generated-code execution and isolation.

### Roadmap direction

A possible progression, to be checked against the current milestone register
rather than committed as written:

| Stage | Capability |
| --- | --- |
| 1 | Persistent discovery — projects, sessions, messages, knowledge, agents, review, retrieval |
| 2 | Development blueprint — traceable requirements, architecture, contracts, tasks |
| 3 | Repository understanding — import or create a repository, analyse structure, persist code knowledge |
| 4 | Bounded implementation — one approved task plus relevant memory |
| 5 | Validation — run tests, compare results with requirements and decisions |
| 6 | Knowledge write-back — capture implementation discoveries, update project memory |
| 7 | Iterative development — use accumulated knowledge for the next feature |
| 8 | Integrated product workflow — plan, implement, review, correct, continue through one interface |

## Acceptance criteria for the review

The review is ready when:

1. A reader can clearly explain what KAE is expected to become.
2. Memory is central without making KAE sound like only a memory database.
3. KAE is clearly expected to perform real software-development work.
4. Raw conversations and trusted project knowledge are clearly distinguished.
5. The relationship among event, knowledge, directive, and execution memory is
   clear.
6. Cross-agent retrieval and write-back are explicitly defined.
7. Implemented and proposed capabilities are not confused.
8. Candidate agents are not prematurely authorised.
9. MCP boundaries remain consistent with KAE application contracts.
10. Requirements are observable and can later become acceptance tests.
11. The current discovery workspace remains a valid first product slice.
12. The documents provide enough context for later ADRs and milestone planning.
13. No application code changes are introduced.
14. No existing accepted ADR is silently contradicted.
15. `CURRENT_PROJECT_STATE.md` remains authoritative for present implementation
    status.

## Required final output

1. Files changed
2. Major conceptual improvements
3. Contradictions resolved
4. Requirements refined
5. Open questions retained
6. ADRs recommended
7. Roadmap recommendation
8. Anything intentionally deferred
9. Validation performed
10. Whether the package is ready to merge

> Do not simply approve the existing text. Act as a product architect and
> engineering-context reviewer. Tighten the product definition so that later
> coding agents can use it without mistaking vision for implementation authority.
