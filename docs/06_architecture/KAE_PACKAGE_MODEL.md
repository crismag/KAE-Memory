# KAE Development Context Package — Model, Readiness, and Lineage

Status: **proposed design**, 2026-08-01. Companion to `../01_discovery/KAE_CONTEXT_PACKAGE_INVENTORY.md`. No implementation is authorized.

Covers: canonical-knowledge-to-artifact mapping · project and module package specifications · artifact dependency graph · readiness profiles · lineage and staleness.

## 1. Package manifest

Every package carries a manifest. Without it, a package cannot be traced, invalidated, or safely regenerated.

```yaml
package:
  package_id:            uuid
  project_id:            uuid              # KAE-Memory project
  scope:                 project | module
  module_key:            MOD-APR           # when scope is module
  profile:               service_api       # artifact profile (§7 of the inventory)
  target_tool:           claude | codex | cursor | generic
  target:                                  # destination descriptor, not credentials
    kind:                github | local | s3
    reference:           crismag/example · docs/kae/

lineage:
  knowledge_revision:    47                # the exact revision rendered
  generated_at:          2026-08-01T12:00:00Z
  generator_version:     1.4.0
  prompt_versions:       { draft_artifact: 3, critique_artifact: 2 }
  template_versions:     { module_spec: 2 }

contents:
  artifacts:
    - path:              modules/approval-workflow.md
      artifact_type:     module_specification
      content_hash:      sha256:…
      source_knowledge:  [MOD-APR, FR-APR-001, …]   # every node rendered
      statement_count:   14
      traced_statements: 14

integrity:
  confirmation_state:                      # never silently omitted
    confirmed:           31
    proposed:            6
    contested:           1
  unresolved_critical_gaps:
    - id: OD-011
      question: Which role holds approval authority?
      blocks: [MOD-APR, SR-APR-001]
  compatibility:
    package_schema:      kae.package.v1
    minimum_reader:      1.0
```

**Two manifest rules are non-negotiable.**

- `source_knowledge` must be complete per artifact. An artifact that cannot name the knowledge it rendered cannot be invalidated when that knowledge changes.
- `confirmation_state` and `unresolved_critical_gaps` are **always present**, never empty-by-omission. A package must not silently present proposed or disputed information as approved fact.

## 2. Canonical knowledge → artifact mapping

Left column is KAE-Memory-owned. Right column is derived. Nothing flows right-to-left except through evidence.

| Artifact | Canonical knowledge required | Human approval | Scope | Becomes generation-ready when |
| --- | --- | --- | --- | --- |
| Context index | Package composition, module inventory | No | Project | Any package generates |
| Current project state | Readiness snapshot, findings, phase, milestone | No | Project | Always (it *is* the status) |
| Project charter | Objectives, problem, value | Recommended | Project | Problem + ≥1 objective confirmed |
| Stakeholder register | Stakeholders, actors | No | Project | ≥1 stakeholder confirmed |
| Scope and non-goals | In-scope, out-of-scope statements | **Yes** | Project | ≥1 of each confirmed |
| Requirements register | Requirements, satisfies edges, status | **Yes** for confirmed set | Project | ≥1 requirement confirmed |
| Business workflows | Workflows, steps, realized_by | No | Project | ≥1 workflow confirmed |
| System architecture | Modules, interfaces, decisions, constraints | **Yes** | Project | Architecture readiness met (§5) |
| ADR | Decision, alternatives, consequences | **Yes** | Project | Decision confirmed |
| Domain/data model | Data entities, owns_data edges | No | Project | Every entity has exactly one owner |
| Integration contracts | Interfaces, integration requirements | **Yes** | Project | Integration readiness met (§5) |
| Module inventory | Modules, decomposition decisions | **Yes** | Project | Decomposition curated |
| Dependency graph | depends_on edges | No | Project | Graph acyclic |
| **Module specification** | Module, requirements, interfaces, data, deps, rules, failure behaviour, tests, open decisions, readiness | **Yes** | Module | Module implementation readiness met (§5) |
| Interface specification | Interface, owner, protocol, auth, retry, versioning | **Yes** | Module | Contract fields answered |
| Acceptance criteria | Acceptance tests, verified_by | **Yes** | Both | ≥1 test per delivered requirement |
| Test context | Acceptance tests, module data, fixtures | No | Module | Acceptance criteria exist |
| Implementation plan | Phases, work packages, scheduled_in | **Yes** | Project | Build order derivable |
| Development task | Requirements, module, file scope, tests, stop conditions | **Yes** | Module | Module readiness met |
| Risk register | Risks, assumptions | No | Project | ≥1 risk or assumption |
| Open questions | Open decisions, blocked_by, findings | No | Both | Always |
| Readiness report | Readiness snapshot, findings | No | Both | Always |
| Agent instruction | Package composition, open decisions, constraints | No | Project | Any package generates |

### Expert perspective per artifact

Which role best acquires or validates each. Roles are **governed profiles over one runtime**, not separate agents.

| Perspective | Acquires / validates |
| --- | --- |
| Business analyst | Charter, stakeholders, scope, workflows, requirements |
| Solution architect | Architecture, ADRs, module inventory, dependency graph, data model |
| Integration engineer | Integration contracts, interface specifications, failure behaviour |
| Security reviewer | Security requirements, permissions, compliance constraints |
| Requirements reviewer | Acceptance criteria, verification coverage, contradiction detection |
| Project manager | Implementation plan, milestones, tasks, risks |

## 3. Project package specification

```text
project-context/
├── CONTEXT_INDEX.md              ← governs loading order; read first
├── CURRENT_STATE.md              ← wins every conflict
├── product/
│   ├── charter.md · stakeholders.md · scope-and-non-goals.md · workflows.md
├── requirements/
│   ├── functional.md · integration.md · security.md · operational.md · quality.md
│   └── acceptance-criteria.md
├── architecture/
│   ├── system-context.md · component-design.md · data-model.md
│   ├── integration-contracts.md
│   └── decisions/ADR-*.md
├── modules/
│   ├── index.md                  ← module inventory
│   ├── dependency-graph.md       ← build order
│   └── <module>.md               ← one per module
├── planning/
│   ├── phases.md · milestones.md · risks.md · open-questions.md
├── governance/
│   ├── readiness-report.md · manifest.yaml
└── agents/
    ├── CLAUDE.md | AGENTS.md | .cursor/rules/   ← target-tool shaped
    ├── project-context.yaml
    └── task-template.md
```

## 4. Module package specification

A module package is **bounded**: enough to implement one module without reading the project, and without carrying an uncontrolled snapshot of it.

```text
module-context/<module-key>/
├── CONTEXT.md                    ← purpose, responsibilities, non-responsibilities
├── requirements.md               ← allocated requirements, with IDs
├── interfaces.md                 ← exposed and consumed, with contracts
├── data.md                       ← owned and read entities
├── dependencies.md               ← modules depended on, with stub summaries
├── acceptance-criteria.md
├── testing.md
├── decisions.md                  ← applicable ADRs (referenced, see below)
├── blockers.md                   ← unresolved open decisions — never omitted
├── readiness.md                  ← per dimension
├── manifest.yaml
└── agents/implementation-prompt.md
```

### Inheritance without snapshot drift

The stated requirement — inherit project constraints without copying a snapshot that immediately goes stale — is solved by **reference plus pinned revision, not by copying**:

1. A module package **references** project-level artifacts by identifier and revision (`ADR-0007 @ revision 47`), and includes only the *statement* of a constraint, never a duplicated rationale.
2. Both packages are pinned to **the same `knowledge_revision`**. A module package generated at revision 47 is consistent with the project package at revision 47 by construction.
3. When project knowledge changes, **both go outdated together** (§6). There is no state where a module package silently disagrees with its project.
4. Dependency modules appear as **stub summaries** — purpose, exposed interfaces, owned data — never as full specifications. A copy of a neighbour's spec is precisely the snapshot that drifts.

**Rule: a module package may reference any project fact and may duplicate none.**

## 5. Readiness profiles

The correction is that readiness is not one number and not "one confirmed item per area". Five profiles, each answering a different decision.

| Profile | Question | Gate conditions |
| --- | --- | --- |
| **Project definition** | Is the project defined enough to begin architecture? | Problem and ≥1 objective confirmed · ≥1 stakeholder · in-scope **and** out-of-scope stated · ≥1 workflow · no critical contradiction unresolved |
| **Architecture** | Is architecture defined enough to identify modules? | Project-definition met · data entities identified · every entity has exactly one owner · integration points named · architecture decisions with alternatives recorded |
| **Module implementation** | Can this module be implemented? | Requirements confirmed and allocated · exposed and consumed interfaces specified · data ownership resolved · dependencies exist and are acyclic · **no `blocked_by` open decision** · acceptance criteria testable · failure behaviour defined |
| **Integration** | Can this interface be built against? | Initiator · protocol · authentication · synchronicity · **retry ownership** · field authority · versioning · timeout · failure behaviour · acceptance method — all answered |
| **Release planning** | Can delivery be sequenced? | Dependency graph acyclic · build order derivable · every requirement verified by ≥1 test · no critical open decision on the critical path |

**The generation gate is separate from readiness.** A package may generate below a profile threshold, *provided* it declares its confirmation state and carries its unresolved gaps. Incomplete does not mean useless — but hidden incompleteness is disqualifying. The rule is: **generation may be incomplete; it may never be silent.**

This directly replaces the failure mode found in the Slim evaluation, where an area with no required fields scored 100% and the package was declared "ready for generation".

## 6. Lineage and staleness

### Lineage

Every generated artifact records: the package it belongs to, the `knowledge_revision` rendered, the generator and template versions, the prompt versions, a content hash, and the complete set of source knowledge identifiers.

**Lineage is KAE-Memory-owned.** Studio performs generation and publication; Memory records that an artifact was produced, from what, and where it went. This is the existing `ADR-0003` boundary applied to lineage.

### Staleness

An artifact is **outdated** when any node in its `source_knowledge` has a revision later than the artifact's `knowledge_revision`.

That is computable exactly — no heuristics, no timestamps — because Memory already maintains a monotonic per-project `knowledge_revision`, and `ReadinessSnapshot.is_stale_against(current_revision)` already implements this comparison for snapshots. **Reuse that mechanism rather than inventing a second one.**

Four states, and the distinction between the last two matters:

| State | Meaning | Action |
| --- | --- | --- |
| **Current** | Every source node is at or below the pinned revision | None |
| **Outdated** | A source node changed | Regenerate |
| **Superseded** | A later package version exists for the same scope | Informational |
| **Conflicted** | The published target changed since publication | **Never overwrite** — present the diff |

Staleness must be **granular per artifact**, not per package. Changing one module's requirement should not mark the stakeholder register outdated. This is why `source_knowledge` is recorded per artifact rather than per package.

### What must not be invalidated

Post-implementation work products (completion notes, retrospectives, `PROTOTYPE_NOTES.md`) and repository-local human overrides are **not generated artifacts**. They have no lineage, are never marked outdated, and are never overwritten. Publication must distinguish them by path policy and manifest membership before writing.

## 7. Artifact dependency graph

Generation order, derived from what each artifact needs to exist first.

```text
                       CURRENT_STATE ──────────────┐
                            │                      │
   charter ── stakeholders ─┴─ scope-and-non-goals  │
      │                            │               │
      └──────────► requirements ◄──┘               │
                       │                           │
        ┌──────────────┼───────────────┐           │
        ▼              ▼               ▼           │
    workflows     acceptance-      data-model      │
        │          criteria            │           │
        └──────────────┴───────────────┘           │
                       ▼                           │
              architecture + ADRs                  │
                       ▼                           │
              module inventory                     │
                       ▼                           │
              dependency graph                     │
            ┌──────────┴──────────┐                │
            ▼                     ▼                │
   module specification   integration contracts    │
            ▼                     ▼                │
        test context      interface specs          │
            └──────────┬──────────┘                │
                       ▼                           │
              implementation plan                  │
                       ▼                           │
              development tasks                    │
                       ▼                           │
   CONTEXT_INDEX ◄─────┴─── agent instructions ◄───┘
```

Two edges deserve comment. **`CONTEXT_INDEX` is generated last** because it must enumerate what actually exists. **`CURRENT_STATE` feeds the agent instructions directly**, because the precedence rule ("if documents disagree, current state is correct") has to be stated in the tool's own instruction file to be honoured.

## 8. Distinctions the design depends on

Restating, because every subsequent decision rests on them:

- **Authoritative knowledge** lives only in KAE-Memory.
- **Generated documents** are renderings at a pinned revision; editing one is not how knowledge changes.
- **Templates and prompts** are versioned generator inputs, recorded in every manifest.
- **Tool configuration** is generated, tool-shaped, and regenerable.
- **Repository-local human overrides** are never overwritten and never invalidated.
- **Post-implementation work products** are ingested as evidence, never generated.
