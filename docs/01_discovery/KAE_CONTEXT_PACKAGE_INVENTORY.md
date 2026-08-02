# KAE Development Context Packages — Cross-Repository Artifact Inventory

Status: **evidence-based analysis**, 2026-08-01. Investigation only; nothing here authorizes implementation.

Sources inspected: `cris-cie-slim/documentation`, `cris-cie-slim/prompts`, `KAE-Studio` (committed **and** uncommitted, unmodified), `KAE-Memory/development/tasks`, `KAE-Memory/docs`.

## The central product question

> Can KAE produce a package that lets a capable AI development tool understand what to build, why, how the system is divided, what each module must do, what it depends on, how success is verified, and which decisions remain unresolved — without requiring the user to repeat the entire project history?

**The best existing answer is already in this repository**, and it is not what was expected. See §4.

## 0. Six-way classification — required before anything else

The referenced directories mix six materially different things. Conflating them is the main hazard in this whole design, because only one of them is authoritative and only two of them KAE should generate.

| Class | Definition | Authority | KAE's relationship |
| --- | --- | --- | --- |
| **Authoritative knowledge** | What the system durably believes, with provenance and revision | **KAE-Memory** | Owns it |
| **Generated document** | A rendering of knowledge at a pinned revision | Derived — never edited in place | **Generates** |
| **Reusable template** | The shape a generated document takes | Versioned generator input | Maintains |
| **AI prompt** | Instruction text issued to a model, parameterised | Versioned generator input | Maintains and **generates instances** |
| **Tool configuration** | Client-specific files (`CLAUDE.md`, `.cursor/rules/`, `AGENTS.md`) | Derived, tool-shaped | **Generates** |
| **Repository-local human override** | Hand-authored, intentionally outside KAE | The human | **Must never overwrite** |
| **Post-implementation work product** | Produced *during* development: completion notes, retrospectives | The implementer | **Ingests as evidence**, does not generate |

**Failing to separate the last two from generated documents is how a generator destroys human work.** Publication must be able to tell them apart before it writes anything.

## 1. Cross-repository inventory

### 1a. `cris-cie-slim/documentation` — 19 files, 1,649 lines

`AI_TOOL_USAGE.md` · `ARTIFACT_PROFILES.md` · `CLI_REFERENCE.md` · `CONFIGURATION.md` · `DEMO_GUIDE.md` · `EXAMPLES.md` · `GETTING_STARTED.md` · `LIMITATIONS.md` · `methodology.md` · `MODES.md` · `OUTPUTS.md` · `PUBLIC_PRIVATE_BOUNDARY_REVIEW.md` · `QUICKSTART.md` · `RELEASE_NOTES.md` · `ROADMAP.md` · `SCOPE.md` · `TEST_PLAN_V0_2.md` · `TROUBLESHOOTING.md` · `USAGE.md`

**Correction to the premise: this is documentation *of the Slim tool*, not a project context package.** `CLI_REFERENCE`, `CONFIGURATION`, `GETTING_STARTED`, `TROUBLESHOOTING`, `QUICKSTART`, `RELEASE_NOTES` document how to operate Slim. They are the analogue of KAE-Memory's own README — not of an output KAE would generate for a customer's project.

Three files are relevant as *design input* rather than output examples:

- **`ARTIFACT_PROFILES.md`** — the idea that a package has named profiles selecting which artifacts are produced. Directly reusable concept.
- **`OUTPUTS.md`** — the artifact taxonomy Slim targets.
- **`methodology.md`** — the acquisition process description.

**Classification:** tool documentation (16), design input (3). **Nothing here is an example of a KAE output package.**

### 1b. `cris-cie-slim/prompts` — 13 files

This *is* output-shaped material, and it is the most directly relevant thing in Slim.

| File | Class | Note |
| --- | --- | --- |
| `system_interviewer.md`, `gap_reviewer.md`, `artifact_generator.md` | **AI prompt** (role-level) | Three implicit expert perspectives — the closest thing to role profiles found anywhere |
| `tasks/interview_turn.md`, `generate_question.md`, `classify_gap.md`, `summarize_answers.md`, `draft_artifact.md`, `critique_artifact.md`, `compress_context.md` | **AI prompt** (task-level, **versioned**) | Header `<!-- task: classify_gap \| version: 1 -->` with `$field_id`-style parameters |
| `claude/project.md`, `copilot/instructions.md`, `cursor/rules.md` | **Tool configuration** | Per-tool instruction files |

Two genuinely valuable patterns:

1. **Versioned, parameterised prompt templates with an explicit version marker.** A generated package must record which prompt version produced it; Slim already stamps this.
2. **A declared artifact sequence with dependency order** — `claude/project.md` instructs generation of seven artifacts *in order*: ProjectBrief → Requirements → ArchitectureGuide → ImplementationPlan → DeveloperContext → AICodingPrompt → OpenQuestions. That ordering is an artifact dependency graph expressed as a prompt.

### 1c. `KAE-Memory/docs` — 31 files, 6,627 lines

The richest example, and the one that actually accelerated this project.

| Group | Files | Class |
| --- | --- | --- |
| `00_project` | `CURRENT_PROJECT_STATE.md`, `PROJECT_BRIEF.md` | Product definition + **live status** |
| `01_discovery` | `PROBLEM_DEFINITION.md` + this evaluation set | Discovery / evaluation |
| `02_requirements` | `KAE_WITH_MEMORY_FUNCTIONAL_REQUIREMENTS.md`, `MVP_REQUIREMENTS_BASELINE.md` | Requirements register |
| `05_product` | 8 files — vision, scope, UI, demo narrative, open questions, alignment review | Product definition + open questions |
| `06_architecture` | `THREE_SYSTEM_ARCHITECTURE_CONTEXT.md`, `AGENT_AND_MCP_FUNCTIONAL_MODEL.md`, `MEMORY_AND_DATA_OPERATING_MODEL.md`, `MCP_ACCESS_POLICY.md`, `ARCHITECTURE_WORKPLAN.md` | Architecture + operational instruction |
| `09_development` | 6 files — development plan, execution roadmap, AI provider/cost, AWS baseline, release checklist | Implementation plan + operational instruction |
| `10_prompts` | `TASK_CONTEXT_TEMPLATE.md` | **Reusable template** |
| root | `CONTEXT_INDEX.md` | **Repository governance — the keystone** |
| `specifications/ADR/` | 19 ADRs | Architectural decisions |

### 1d. `KAE-Memory/development/tasks` — 5 files

`TASK-001-domain-contracts` · `TASK-006-m5-persistence` · `TASK-007-m6-agent-collaboration` · `TASK-008-m7-resilience-recovery` · `TASK-009-m8-semantic-retrieval` (+ `TASK-010` on the MCP-M1 branch).

**Class: development task — and post-implementation work product.** Each carries `**Status:** complete, <date>` and a "Completion notes" section written *after* implementation. TASK-009's notes record that the evaluation fixture proves less than its ADR implied. That is evidence produced by development flowing back — exactly the loop KAE must ingest, and exactly what KAE must not overwrite on regeneration.

### 1e. `KAE-Studio` — 27 committed docs + 15 uncommitted paths

Committed: the full definition set (product vision, user workflow, discovery interviews, project model, module specification, system boundary, data ownership, API contract, MCP service, knowledge scopes, pattern library, delivery, 6 ADRs, capability matrix, vertical slice, implementation directive, UI generation context).

Uncommitted and **left untouched**: `src/`, `screenshots/`, `scripts/`, `PROTOTYPE_NOTES.md`, build configuration, modified `README.md`.

`PROTOTYPE_NOTES.md` is worth singling out — it is a **post-implementation work product** recording decisions taken during building, documentation conflicts discovered, and what remains mocked. A generator that regenerated `docs/` and clobbered it would destroy the most useful thing produced that day.

## 2. Development-context package taxonomy

Consolidating all four sources into the artifact types KAE should produce.

| # | Artifact type | Scope | Consumer | Class |
| --- | --- | --- | --- | --- |
| 1 | Project charter / brief | Project | Human + agent | Generated |
| 2 | Current project state | Project | **Both — loaded first** | Generated (live) |
| 3 | Stakeholder register | Project | Human | Generated |
| 4 | Scope and non-goals | Project | Both | Generated |
| 5 | Requirements register | Project | Both | Generated |
| 6 | Business workflows | Project | Both | Generated |
| 7 | System architecture | Project | Both | Generated |
| 8 | Architecture decision record | Project | Both | Generated + human-confirmed |
| 9 | Domain/data model | Project | Both | Generated |
| 10 | Integration contracts | Project | Both | Generated |
| 11 | Module inventory | Project | Both | Generated |
| 12 | Module dependency graph | Project | Both | Generated |
| 13 | Module specification | **Module** | Both | Generated |
| 14 | Interface specification | Module | Both | Generated |
| 15 | Acceptance criteria | Both | Both | Generated |
| 16 | Test context | Module | Agent | Generated |
| 17 | Implementation plan / phases | Project | Human | Generated |
| 18 | Milestone definition | Project | Human | Generated |
| 19 | **Development task** | Module | **Agent** | Generated → becomes work product |
| 20 | Risk register | Project | Human | Generated |
| 21 | Open questions / blockers | Both | Both | Generated |
| 22 | Operational instruction | Project | Human | Generated |
| 23 | **Context index** | Project | **Both — governs loading** | Generated |
| 24 | Agent instruction (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules/`) | Project | Agent | Generated, tool-specific |
| 25 | Task context template | Project | Generator | Template |
| 26 | Reusable task prompt | — | Generator | Prompt |
| 27 | Readiness / review report | Both | Human | Generated |
| 28 | Repository governance | Project | Both | Generated |

## 3. How these files actually accelerated development

Assessed against what happened in this project, not against formatting.

**Established product direction:** `PROJECT_BRIEF.md`, `KAE_WITH_MEMORY_PRODUCT_VISION.md`, KAE-Studio `PRODUCT_VISION.md`. Rewritten repeatedly as intent sharpened — evidence that direction documents must be *regenerable*, not hand-maintained.

**Prevented architecture drift:** the ADRs, decisively. `ADR-0004` (MCP inspection-only) prevented handing agents SQL. `ADR-0006` (ADR-0006 in Studio, Memory-owned conversation) prevented a duplicate conversation store. **ADRs with rejected alternatives were the highest-value artifacts in the entire set** — they stopped work that would otherwise have been done and undone.

**Bounded implementation scope:** `TASK-XXX` files, through four sections that most task documents omit — **Allowed file scope**, **Prohibited changes**, **Stop conditions**, **Required tests**.

**Sequenced work:** `CODEX_CLAUDE_EXECUTION_ROADMAP.md`, `DEVELOPMENT_PLAN.md`, the M0–M11 register.

**Captured decisions and non-goals:** 19 ADRs plus explicit non-goal sections. The Studio prototype's "honest placeholder" screens exist *because* non-goals were written down.

**Gave an agent enough context to implement:** `TASK_CONTEXT_TEMPLATE.md` + one `TASK-XXX` + `CURRENT_PROJECT_STATE.md`. **Not the whole `docs/` tree.**

**Duplicated or contradictory:** Studio's `UI_GENERATION_CONTEXT.md` (six destinations) vs `USER_WORKFLOW.md` (eleven) — found only when the prototype was built. `VERTICAL_SLICE.md` contradicted ADR-0002/0003 and carried a stale-scope banner for a while. Two ADR-0004s exist, one per repository, both about MCP.

**Became stale:** `VERTICAL_SLICE.md`, `IMPLEMENTATION_DIRECTIVE.md` phase order, `DATA_OWNERSHIP.md` conversation ownership — all needed correction *after* later decisions landed. **Staleness was detected by a human noticing, never by the documents themselves.** That is precisely the gap a lineage model closes.

**Repeatedly re-explained despite existing documents:** the Studio/Memory ownership boundary — restated in ADR-0001, `SYSTEM_BOUNDARY.md`, `CLAUDE.md`, `DATA_OWNERSHIP.md`, and again in ADR-0006 because the earlier statements were wrong rather than unclear. Lesson: **repetition across documents is not redundancy, it is an unreconciled contradiction waiting to surface.**

**Useful only to humans:** demo narratives, release checklists, alignment reviews, roadmaps.

**Specifically useful to coding agents:** `CONTEXT_INDEX.md`, `CURRENT_PROJECT_STATE.md`, `TASK-XXX`, `CLAUDE.md`, `TASK_CONTEXT_TEMPLATE.md`, module specifications.

## 4. The keystone finding

`docs/CONTEXT_INDEX.md` opens:

> "This repository uses layered, selective context. **Load only the layers required for the current activity.**"

and `docs/10_prompts/TASK_CONTEXT_TEMPLATE.md`:

> "Copy this file for one issued development task. **Do not hand an agent the whole context package.**"

and `CONTEXT_INDEX.md` again:

> "Nothing in this repository authorises implementation on its own. If the current state page and another document disagree, **the current state page is correct** and the other document needs updating."

**This is the answer to the central product question, and it is the opposite of "generate a big folder".** The value is not volume. It is:

1. **Layered, selective loading** — an index that says which layer to load for which activity.
2. **One page that wins conflicts** — a designated current-state document that overrides every other document.
3. **Per-task context, not whole-package context** — a template that extracts exactly what one task needs.
4. **Explicit non-authorisation** — documents state that they do not authorise implementation by themselves.

A KAE package that emits thirty coherent documents but no index, no precedence rule, and no per-task extraction **will not accelerate an agent** — it will fill its context window with material it cannot prioritise. The dominant failure mode of large generated packages is not missing information; it is undifferentiated information.

## 5. Minimum artifact set before implementation can safely begin

Nine artifacts. Fewer than expected, and deliberately so.

| # | Artifact | Why it is load-bearing |
| --- | --- | --- |
| 1 | **Context index** | Without it the rest is an undifferentiated pile |
| 2 | **Current project state** | Resolves conflicts; states what actually exists |
| 3 | **Scope and non-goals** | The single largest source of wasted agent work |
| 4 | **Requirements register with stable IDs** | Tasks and tests reference them |
| 5 | **Module inventory + dependency graph** | Determines what can be built and in what order |
| 6 | **Module specification** for the module being built | Responsibilities, non-responsibilities, interfaces, data |
| 7 | **Acceptance criteria** for those requirements | Otherwise "done" is unverifiable |
| 8 | **Open decisions carried as open** | Prevents the agent inventing an answer |
| 9 | **Agent instruction file** (`CLAUDE.md` / `AGENTS.md` / `.cursor/rules/`) | Encodes the rules above in the tool's own idiom |

Architecture guides, roadmaps, risk registers, and stakeholder registers are valuable to humans and **not** required before implementation begins.

## 6. Extended profiles

Each profile is the minimum set plus additions.

| Profile | Adds | Rationale |
| --- | --- | --- |
| **Small internal tool** | Nothing — minimum set, often one module | Ceremony exceeds value |
| **Frontend-only application** | Screen specifications, navigation map, design tokens, API dependencies consumed | UI definition becomes primary |
| **Service / API** | Interface contracts, error semantics, versioning guarantees, data ownership | The contract *is* the product |
| **Integration-heavy** | Per-integration contract (initiator, protocol, auth, retry ownership, field authority, versioning, timeout, acceptance), plus failure behaviour per module | The integration interview's ten questions become mandatory |
| **Distributed system** | Consistency model, transaction boundaries, idempotency requirements, failure and partition behaviour, observability | Exactly what a single-node design omits |
| **Data-intensive** | Data model with ownership and lineage, retention and privacy classification, volume and growth, migration strategy | Data ownership becomes the primary boundary |
| **Multi-module product** | Full dependency graph, build order, cross-cutting constraints, per-module packages, interface register | The graph becomes load-bearing rather than informational |

## 7. What must not be duplicated

KAE-Memory owns: evidence · structured knowledge and versions · corrections and supersession · provenance · confirmation state · relationships and dependencies · readiness · findings · retrieval · context assembly · **generated-artifact lineage**.

Generated documents, templates, prompts, and tool configuration are **derived**. A generated document is never the authority for its own content, and editing one must never be the way project knowledge changes.
