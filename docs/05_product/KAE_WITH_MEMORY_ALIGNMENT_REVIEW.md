# KAE with Memory — alignment review

**Status:** review of the four-document product package against the implemented
system, the approved MVP baseline, and the sixteen accepted ADRs. Reviewed
2026-07-28 against `main` at `1577ac9`.

**Verdict:** the package is coherent in intent and safe in tone — every document
carries a proposed-status header and none claims unimplemented capability as
built. It is **not yet usable as planning input**, because a reader cannot tell
which of its forty-six requirements already exist, one memory class has no
representation anywhere in the system, and four different acceptance lists
compete to define the same proof.

Twelve gaps follow, ordered by how much damage each would do if the package were
handed to an implementer as-is.

---

## G1 — Two requirement registers, no mapping between them

**Severity: blocking.** This is the gap that would cause real waste.

`KAE_WITH_MEMORY_FUNCTIONAL_REQUIREMENTS.md` states forty-six functional and
twelve non-functional requirements as *proposed*. At least **fifteen of them are
already implemented and covered by acceptance tests** under the approved
baseline:

| Proposed | Already approved as | State |
| --- | --- | --- |
| KWM-FR-001 persist input before interpretation | FR-003 | implemented |
| KWM-FR-002 preserve conversations | FR-002, FR-003 | implemented |
| KWM-FR-004 extract structured knowledge | FR-004 | implemented |
| KWM-FR-005 retain source provenance | FR-004 | implemented |
| KWM-FR-010 project isolation | FR-001 | implemented |
| KWM-FR-012 lifecycle governance | FR-005 | implemented |
| KWM-FR-013 immutable history | FR-006 | implemented |
| KWM-FR-014 conflict representation | FR-015, ADR-0012 | implemented |
| KWM-FR-019 write-back validation | ADR-0004 | implemented |
| KWM-FR-028 memory-grounded review | FR-015 | implemented |
| KWM-FR-033 durable AgentRun | FR-010 | implemented |
| KWM-FR-034 continuation after interruption | FR-011 | implemented |
| KWM-FR-035 idempotent retry | FR-012 | implemented |
| KWM-FR-036 MCP boundary | FR-014, ADR-0004 | implemented |
| KWM-FR-038 human approval gates | FR-005 | partially — confirmation only |

Restating an implemented requirement as *proposed* is worse than omitting it: it
invites someone to build a second implementation of provenance or lifecycle
beside the one that exists, and it makes the genuinely new requirements harder to
find in the list.

**Resolution.** Every KWM requirement needs a disposition — *satisfied by FR-nnn*,
*extends FR-nnn*, or *new*. The promotion path in the development plan does this;
until it is applied, the register should not be used to scope work.

## G2 — Directive memory has no representation anywhere

**Severity: blocking for the memory model.**

Of the four memory layers, three map onto implemented tables:

| Layer | Implementation | State |
| --- | --- | --- |
| Event | `messages` | partial — see G3 |
| Knowledge | `knowledge_items`, `knowledge_versions`, `knowledge_relationships` | implemented |
| Execution | `agent_runs` with leases, tokens, checkpoints | implemented |
| **Directive** | **nothing** | **absent** |

There is no directive table, no domain type, no lifecycle, and no authority
field. `KnowledgeKind` has eight values and none of them is an instruction.

This matters more than a missing table. Directive memory is what the precedence
model in §5 of the operating model rests on — *"current explicit user instruction
> approved project decision > confirmed requirement"* — and today every
`VALIDATED` knowledge item has exactly equal standing. The precedence model
cannot be implemented, tested, or even approximated against the current schema.

**Resolution.** Directive memory is the single largest new concept in the package
and deserves its own ADR before anything else in it is built. Two shapes are
plausible — a `KnowledgeKind` extension with an authority column, or a separate
`directives` table with its own lifecycle — and the choice determines whether
readiness, retrieval, and blueprint all need to change.

## G3 — Event memory claims more than the system captures

**Severity: high.**

The operating model lists prompts, responses, tool calls and outputs,
repository observations, and approvals as event memory. The system persists
**messages only**. `AgentRun` stores `input_context` and `output_summary` as
`JSONB` summaries; the prompt sent to a provider and the response received are
never written down.

KWM-FR-003 asks for exactly this — *"prompts, responses, tool invocations, tool
results, execution status, and artifact references"* — and adds *"subject to
retention and redaction policy"*, which does not exist either.

The claim is not false in the documents, which are careful to be proposals. But
the gap is load-bearing: **explainability (KWM-NFR-009) and tool evidence
(KWM-FR-037) are unachievable without it**, and both are named as acceptance
conditions elsewhere in the package.

**Resolution.** Sequence it: retention and redaction policy is a prerequisite for
prompt capture, not a follow-up to it. Storing model transcripts without a
redaction rule is how a secret reaches a database.

## G4 — Four competing acceptance lists

**Severity: high, and cheap to fix.**

The same proof is defined four times, differently:

| Source | Form |
| --- | --- |
| Review brief | 7 proof scenarios |
| Functional requirements §8 | 5 scenarios, A–E |
| Memory operating model §14 | 8 numbered acceptance steps |
| Agent and MCP model §15 | 8 numbered demonstration steps |

None contradicts another, but there is no canonical set, so no acceptance test
can cite one. The repository's existing convention is a single `AT-nnn` register
in `project-model.yaml`; none of the four lists uses it.

**Resolution.** One list, expressed as `AT-nnn` entries, derived from the brief's
seven scenarios because that list is the most behavioural. The other three become
references to it.

## G5 — The scope hierarchy contradicts approved scope

**Severity: medium.**

The operating model proposes eight scope levels from Organisation down to
AgentRun. `MVP_SCOPE.md` explicitly excludes **teams, multi-user projects,
sharing, roles, and permissions**, and the MVP assumes a single trusted operator.
Organisation and workspace scope therefore have no meaning in the current system,
and no access-control model exists to give them one.

The document does say future organisation-wide knowledge requires a separate
approved model. The gap is that the *precedence* and *task-context* sections then
use the full hierarchy as though all eight levels were available.

**Resolution.** Split the hierarchy into the levels that exist today — project,
repository, component, milestone, task, run — and the levels that require an
access-control decision first.

## G6 — Repository construction contradicts the MVP scope boundary

**Severity: medium — a real product decision, not a documentation slip.**

The vision (§5.6) states KAE should *"construct or update a repository in bounded,
reviewable slices"*. `MVP_SCOPE.md` excludes *"code generation, execution, or
autonomous delivery"* and states plainly: **the three authorised agents write
knowledge, not code.**

Both can be true across time, but nothing currently records that the boundary is
expected to move, or what would authorise moving it. A reader comparing the two
documents finds a flat contradiction with no bridge.

**Resolution.** The development plan's staging is that bridge, and the boundary
should move only with an ADR covering workspace ownership and code-execution
isolation. Until then the vision statement needs a forward marker.

## G7 — Agent role inflation is described but not resisted

**Severity: medium.**

The agent model lists ten candidate roles. FR-009 authorises three, and the
document says so. But the brief asks a question the document does not answer:
*should these be agents at all?*

Reviewing them against what the system already shows:

| Candidate | Better shape | Why |
| --- | --- | --- |
| Discovery / Interview | **Agent** | Distinct responsibility, distinct prompt, produces knowledge |
| Planning | **Agent** | Produces durable task decomposition |
| Repository Understanding | **Agent** | Distinct read scope and output |
| Implementation | **Agent** | Needs its own tool permissions and isolation |
| Testing | **Agent** | Distinct evidence and failure semantics |
| Knowledge Curator | **Deterministic service** | Deduplication, supersession proposals, and staleness are computable; ADR-0015 already showed classification proposes while calculation decides |
| Documentation | **Capability** | An output format of other roles, not a responsibility |
| Security / Compliance | **Capability of Review** | A lens on the same artefacts, not a separate write scope |
| Deployment / Release | **Orchestrator stage** | Sequencing and gates, not model judgement |

That is five agents, not ten. The distinction the repository already uses is the
right test: **a role exists when it has a distinct write scope and prohibition
set**, not when it has a distinct job title.

**Resolution.** Record the triage above in the agent model, and require each new
role to arrive with its own ADR — as ADR-0015 did for Review.

## G8 — Retrieval cannot yet filter on the things precedence depends on

**Severity: medium.**

`ChunkRepository.search` filters on project, knowledge kind, and embedding
version. The precedence model needs lifecycle state, scope, authority,
supersession, and contradiction state as well — none of which are on the chunk
row.

Separately, and more importantly: **retrieval quality is still unmeasured.** The
offline evaluation scores `recall@8: 50%` against a chance level of `44%`, and
the live Titan run has never executed. KWM-NFR-004 asks retrieval to *"minimise
the use of irrelevant, superseded, cross-scope, or unsupported memory"* — a
requirement that cannot be assessed until the live evaluation runs.

**Resolution.** Run the live evaluation before designing hybrid retrieval on top
of an unmeasured ranker. Chunk-level lifecycle and authority filtering is a
schema change and belongs with the directive-memory ADR.

## G9 — Terminology introduces synonyms the domain already names

**Severity: medium — this is the failure mode this project has caught three times.**

| Package term | Existing term | Note |
| --- | --- | --- |
| Write-back envelope | `StepResult`, `WriteKnowledgeRequest` | Same concept, new name |
| Task context envelope | — | Genuinely new; needs defining |
| Artifact | — | Genuinely new; no representation |
| Validated observation | Confirmed knowledge | Synonym; drop |
| Authority | — | New, and unimplemented (see G2) |
| Memory class | — | New; relates to but is not `KnowledgeKind` |
| `K-142` identifiers | UUID `KnowledgeItemId` | Example style contradicts the schema |

The example in §7 of the operating model uses `K-142` and `K-287`. Knowledge
identifiers are application-generated UUIDs (ADR-0005), deliberately, because
sequential keys create range hotspots. A worked example in a schema-adjacent
document should not model an identifier scheme the schema rejects.

**Resolution.** Replace synonyms with existing terms; define the four genuinely
new terms in `CONTEXT_INDEX.md`; fix the example identifiers.

## G10 — The project model does not know this direction exists

**Severity: medium.**

`project-model.yaml` is the durable source of project state, and it contains no
reference to the KAE with Memory package: no decisions, no open questions, no
milestones beyond M11, no requirement register entry. `CURRENT_PROJECT_STATE.md`
likewise describes only the discovery workspace.

A future session loading the model as authoritative would not learn that the
product direction has widened.

**Resolution.** This review, the open-questions register, and the development plan
are recorded in the model as this commit's history entry, with the open questions
carried as `OQ-019` onward.

## G11 — "Human approval gates" is broader than what exists

**Severity: low.**

KWM-FR-038 lists approval for requirements, decisions, conflicts, destructive
changes, security trade-offs, and release actions. What exists is knowledge
confirmation (FR-005) and contradiction resolution. There is no approval concept
covering an action — only knowledge.

**Resolution.** Treat approval-of-action as new, dependent on the directive and
execution model, and defer it to the stage that introduces bounded implementation.

## G12 — Provider independence is claimed more strongly than tested

**Severity: low.**

KWM-FR-032 and KWM-NFR-008 require provider independence. `ExtractionPort` and
`EmbeddingPort` do give it structurally, and ADR-0010 records the direction. But
only one live provider adapter has ever been exercised, and the offline path is a
fixture — so portability is a property of the design rather than a demonstrated
fact.

**Resolution.** State it as a design property until a second provider runs.

---

## What the package gets right

Worth recording, because a review that only lists faults misrepresents the work:

- **Every document carries an accurate status header.** None claims unimplemented
  capability as built — the constraint the brief was most concerned about is met.
- **The distinction between stored material and authoritative knowledge is stated
  clearly and repeatedly**, including the DynamoDB example, which is the sharpest
  illustration of the point in the whole package.
- **MCP boundaries are consistent with ADR-0004.** No document proposes a direct
  domain write, and the read/propose/execute split is a genuine improvement on the
  existing inspection-only policy.
- **The correction-without-forgetting behaviour matches the implemented
  supersession model exactly**, including retrieval defaulting to the active
  version.
- **The candidate-role section refuses to authorise itself**, which is the
  behaviour that keeps a vision document safe to leave in a repository.

## Recommendation

The package should **stay as accepted product-shaping context** and should not be
promoted into the requirement baseline in its current form. G1, G2, and G4 are
prerequisites for planning; the rest can be resolved as their stages arrive.

The development plan in
[`../09_development/KAE_WITH_MEMORY_DEVELOPMENT_PLAN.md`](../09_development/KAE_WITH_MEMORY_DEVELOPMENT_PLAN.md)
sequences that work. Unresolved product questions are registered in
[`KAE_WITH_MEMORY_OPEN_QUESTIONS.md`](KAE_WITH_MEMORY_OPEN_QUESTIONS.md).
