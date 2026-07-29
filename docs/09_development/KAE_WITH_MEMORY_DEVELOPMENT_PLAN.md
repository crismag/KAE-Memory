# KAE with Memory — development plan

**Status:** proposed staging from the current discovery workspace to the wider
product. **Not implementation authority.** Each stage becomes real only when its
requirements are promoted into the baseline and its milestone is recorded in
`project-model.yaml`.

Derived from the alignment review, which found twelve gaps between the product
package and the implemented system. Three of them — the unmapped requirement
register, the absent directive memory, and the four competing acceptance lists —
block planning until they are resolved, and Stage 0 exists to resolve them.

---

## Where the work starts from

M0–M9 are complete or nearly so. The system today can take an idea from a
message, extract candidates, confirm them, classify and score readiness, report
findings, generate a traceable blueprint, and trace any statement back to the
words that produced it — over an HTTP API, with a separate durable worker, on
CockroachDB.

Three things remain outstanding **inside the current milestones**, and none of
the stages below should start before they close:

| Outstanding | Milestone | Why it blocks |
| --- | --- | --- |
| Live retrieval evaluation | M8 | Retrieval quality is unmeasured at chance level. Every stage below assumes retrieval works |
| Generated client and workspace UI | M9 | The proof moments are user-visible or they are not proof |
| Deployment, supervision, signal handling | M10 | Stages 3+ imply long-running work |

## Staging principle

Each stage must end in something a person can watch happen. A stage that only
adds schema is not a stage; it is part of the stage that uses it.

The order below is driven by dependency, not ambition. Repository understanding
precedes implementation because an agent that writes code without knowing the
codebase produces exactly the incoherence this product exists to prevent.

---

## Stage 0 — Make the package planable

**Milestone:** M12 · **Depends on:** nothing · **Ends when:** the register maps
cleanly onto the baseline and one acceptance set exists.

Documentation and governance only; no application code.

1. **Disposition every KWM requirement** — *satisfied by FR-nnn*, *extends
   FR-nnn*, or *new*. Fifteen are already implemented (alignment review, G1).
2. **Collapse the four acceptance lists into one `AT-nnn` set**, derived from the
   brief's seven proof scenarios.
3. **Resolve terminology** — replace synonyms with existing domain terms, define
   the four genuinely new ones in `CONTEXT_INDEX.md`, fix the `K-142` example
   identifiers that contradict ADR-0005.
4. **Record the agent triage** — five agents, one deterministic service, two
   capabilities, one orchestrator stage (G7).
5. **Split the scope hierarchy** into levels that exist and levels that need an
   access-control decision (G5).

**ADR:** none. This stage removes the need for guessing, it does not decide
anything.

## Stage 1 — Directive memory and authority

**Milestone:** M13 · **Depends on:** Stage 0, OQ-019, OQ-020 · **Ends when:** a
current instruction outranks a confirmed requirement in retrieval, visibly.

The single largest new concept in the package, and the prerequisite for most of
the rest. Today every `VALIDATED` knowledge item has equal standing, so the
precedence model cannot be expressed at all.

- decide directive representation and authority (**ADR required**);
- persist directives with scope, precedence, lifecycle, and provenance;
- extend retrieval to filter and rank on lifecycle, scope, and authority — not
  vector distance alone;
- expose precedence in the API so a user can see *why* one instruction won.

**Proof:** a user instruction that contradicts an earlier confirmed requirement
changes what the next agent does, and both remain queryable.

**Risk:** this touches readiness, blueprint, and review, all of which currently
assume knowledge is the only authoritative class.

## Stage 2 — Event capture and evidence

**Milestone:** M14 · **Depends on:** OQ-023 · **Ends when:** an agent's output
can be explained by showing exactly what it was sent.

- **retention and redaction policy first** — prompt capture must not ship before
  it, because storing transcripts without a redaction rule is how a secret
  reaches a database;
- persist prompts, responses, tool invocations, and results as evidence;
- link evidence to the `AgentRun` that produced it;
- expose retrieval explanation: which memory items were supplied, and why.

**Proof:** open any agent run and read the exact context it received.

## Stage 3 — Repository understanding

**Milestone:** M15 · **Depends on:** Stages 1–2, OQ-026 · **Ends when:** KAE can
answer "why does this component exist?" about a real codebase.

- decide repository ownership and access (**ADR required**);
- read-only repository access through MCP or a connector;
- a Repository Understanding agent producing component inventory, dependencies,
  conventions, and code-to-requirement mappings (**ADR required** — a fourth
  role, and FR-009 authorises three);
- persist code knowledge with the same lifecycle and provenance as any other.

**Proof:** import this repository, then ask why `events.py` exists and get an
answer traced to ADR-0009.

Read-only deliberately. Understanding a codebase is valuable on its own and
carries none of the execution risk that Stage 5 does.

## Stage 4 — Planning and task context

**Milestone:** M16 · **Depends on:** Stage 3 · **Ends when:** an agent receives a
bounded context package instead of a project dump.

- a Planning agent turning approved requirements and architecture into
  dependency-aware tasks (**ADR required** — fifth role);
- task-context assembly with an explicit budget, drawing on directives,
  requirements, architecture, repository facts, and known contradictions;
- the context envelope visible to a user before the work runs.

**Proof:** two tasks in the same project receive demonstrably different context,
and each is small enough to read.

This is the stage that most directly earns the product claim. Bounded context is
what makes shared memory better than a long conversation.

## Stage 5 — Bounded implementation

**Milestone:** M17 · **Depends on:** Stage 4, OQ-027, OQ-029 · **Ends when:** one
approved task produces a reviewable change set.

**The stage that moves the MVP scope boundary.** `MVP_SCOPE.md` currently
excludes code generation and states that the three authorised agents write
knowledge, not code. That exclusion must be amended by an approved requirement,
not quietly outgrown.

- decide code-execution isolation (**ADR required**);
- decide approval gates for actions, not just knowledge (**ADR required**);
- an Implementation agent with one task, bounded file scope, and explicit
  acceptance criteria (**ADR required** — sixth role);
- structured write-back: artifacts changed, constraints discovered, assumptions
  invalidated.

**Proof:** one small feature implemented from confirmed knowledge, with the
change set reviewable and every decision traceable.

## Stage 6 — Validation and grounded review

**Milestone:** M18 · **Depends on:** Stage 5 · **Ends when:** the Review Agent
compares an implementation against confirmed requirements rather than reading
code in isolation.

- a Testing agent deriving tests from requirements and contracts (**ADR
  required** — seventh role, and the last one this plan proposes);
- test execution evidence persisted as event memory;
- Review extended to compare artifacts against confirmed knowledge.

**Proof:** a generated implementation that contradicts a confirmed requirement is
caught, with the finding linked to both the requirement and the code.

## Stage 7 — Discovery propagation

**Milestone:** M19 · **Depends on:** Stage 6 · **Ends when:** a constraint found
during implementation changes what the project knows.

- write-back promoted to candidate knowledge with provenance to the run;
- impact identification across requirements, architecture, tests, and
  documentation via the relationship layer M5 built and M9 first read;
- affected areas surfaced as review findings.

**Proof:** implementing feature A surfaces a constraint that changes the plan for
feature B, without the user restating it. **This is the product claim.**

## Stage 8 — Integrated workflow

**Milestone:** M20 · **Depends on:** Stages 1–7 · **Ends when:** the whole loop is
walkable in one interface.

Plan, implement, review, correct, continue — with readiness, findings, and
blueprint updating as it goes. No new capability; the stage exists because a
coherent interface over eight stages of capability is itself work.

---

## Requirement promotion path

No KWM requirement becomes authoritative by being written down. Each moves
through:

```text
Proposed in the KWM register
  -> dispositioned against the baseline (Stage 0)
  -> assigned to a stage
  -> given an AT-nnn acceptance test
  -> promoted into MVP_REQUIREMENTS_BASELINE.md with an FR-nnn identifier
  -> recorded in project-model.yaml
  -> implemented
```

A requirement may not be implemented from the KWM register directly. The register
is a source of candidates, and `MVP_REQUIREMENTS_BASELINE.md` remains the only
authorised set — the same rule that has held since M4.

## Architecture decisions this plan needs

Ordered by when the stage that needs them starts. None is written yet.

| # | Decision | Stage | Why it cannot be deferred |
| --- | --- | --- | --- |
| 1 | Directive memory and authority precedence | 1 | Nothing in the schema expresses instruction authority |
| 2 | Context assembly and retrieval policy | 1 | Retrieval ranks on distance alone today |
| 3 | Evidence capture, retention, and redaction | 2 | Prompt capture is unsafe without it |
| 4 | Repository workspace ownership | 3 | Determines isolation and credentials |
| 5 | Agent capability and role model | 3 | FR-009 authorises three roles; the plan adds four |
| 6 | Agent write-back contract | 4 | Structured results are the alternative to prose handoffs |
| 7 | Code-execution isolation | 5 | Untrusted generated code must run somewhere |
| 8 | Human approval gates for actions | 5 | Only knowledge confirmation exists today |
| 9 | Artifact and evidence model | 5 | Generated files have no representation |
| 10 | Tenancy, identity, and cross-project scope | later | Blocks organisation scope and preference memory |

## What this plan deliberately does not do

- **It does not schedule.** No dates, no estimates. The milestone register has
  never carried them and inventing them here would be the first fiction in it.
- **It does not authorise a single agent role.** Seven are named; each needs its
  own ADR, as Review did.
- **It does not commit to the brief's eight-stage sequence verbatim.** The brief
  asked that its roadmap be checked against the milestone register rather than
  adopted as written; this plan reorders repository understanding ahead of
  implementation for that reason.
- **It does not resolve the open questions.** Fourteen are registered, and four
  block Stages 1, 2, 3, and 5 respectively.

## Related

- [`../05_product/KAE_WITH_MEMORY_ALIGNMENT_REVIEW.md`](../05_product/KAE_WITH_MEMORY_ALIGNMENT_REVIEW.md) — the twelve gaps this plan sequences
- [`../05_product/KAE_WITH_MEMORY_OPEN_QUESTIONS.md`](../05_product/KAE_WITH_MEMORY_OPEN_QUESTIONS.md) — OQ-019 onward
- [`../05_product/KAE_WITH_MEMORY_REVIEW_BRIEF.md`](../05_product/KAE_WITH_MEMORY_REVIEW_BRIEF.md) — the originating instruction
- [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) — M0–M11, which this continues
- [`../02_requirements/MVP_REQUIREMENTS_BASELINE.md`](../02_requirements/MVP_REQUIREMENTS_BASELINE.md) — the only authorised requirement set
