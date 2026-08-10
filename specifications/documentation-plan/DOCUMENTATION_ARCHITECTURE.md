# Documentation architecture

What KAE-Memory's public documentation should contain, who it is for, and where
each thing lives. **This is a plan, not the documentation.** Phase 2B writes the
pages; this decides what they are and what governs them.

Companion artifacts:

- [SOURCE_MAP.md](SOURCE_MAP.md) — what establishes each claim
- [GAP_REGISTER.md](GAP_REGISTER.md) — contradictions, missing authority, blockers
- [DOCUMENTATION_MANIFEST.md](DOCUMENTATION_MANIFEST.md) — every page, path, phase

---

## The component, as it currently is

**KAE-Memory is a headless knowledge service.** It holds what a software project
durably knows, keeps the record of how it came to know it, and serves that to
agents and applications through two adapters. It renders no interface (ADR-0026).

Evidence for that sentence: 49 HTTP paths / 57 operations in the recorded
contract, 31 declared MCP tools, no `package.json` anywhere in the repository,
and a `make dev` that starts a database, migrations, an API and a worker.

**What it deliberately does not do:**

| Not this | Where it lives instead |
|---|---|
| Product interface, conversation surface | KAE-Studio, its own repository (ADR-0026) |
| Interview intelligence | CIE (`cris-cie-slim`) |
| Deciding what a project should do | People. It records and reports; confirmation is a person's act |
| Direct persistence access as a workflow | Forbidden for normal clients (ADR-0027) |
| Private infrastructure automation | KAE-Ecosystem, private |

**What it is not yet.** No maturity claim belongs in the documentation beyond
what the register supports: 1,885 tests, one deployed instance, no versioned
release, no published compatibility guarantee. "Production ready" and "fully
supported" appear nowhere in this repository today and should not start here.

---

## Audiences

Six, in the order the documentation should serve them. **The MCP user comes
first** — that is the interface KAE-Memory was built around, and the one a person
can reach today without KAE-Studio.

### A1 — MCP user *(primary)*

Connects an MCP client, drives a project through conversation with an agent.

- **Entry:** `docs/getting-started/quickstart.md`
- **Journey:** quickstart → connect a client → create a project → submit an
  observation → review what was proposed → answer a clarification → assemble
  context
- **Success:** a second session, in a new client, knows what the first
  established. That is the claim the product turns on, and the documentation
  should prove it rather than assert it.
- **Confusion to pre-empt:** that submitting something makes it true. It becomes
  *proposed*; a person confirms it. Every page touching acquisition must carry
  that distinction.

### A2 — Application integrator

Builds against MCP or HTTP.

- **Entry:** `docs/reference/capability-matrix.md`
- **Journey:** capability matrix → the adapter's reference → response policy →
  lifecycle semantics → errors and idempotency
- **Confusion to pre-empt:** that the two adapters are the same surface. They
  are peers with *declared* differences — 25 capabilities on both, 12 HTTP-only,
  5 MCP-only, 1 internal. Parity means the registry decides, not that everything
  appears twice.

### A3 — Evaluator

Deciding whether this is worth attention.

- **Entry:** `README.md` → `docs/index.md`
- **Journey:** what it is → why persistent project knowledge differs from a
  transcript or a vector store → a worked demonstration
- **Confusion to pre-empt:** "this is RAG". The lifecycle and provenance are the
  difference, and stating that abstractly will not land — the demonstration has
  to show a rejected statement staying rejected.

### A4 — Developer / contributor

- **Entry:** `docs/development/local-setup.md`
- **Journey:** install → run → migrations → test strategy → package layout →
  provider behaviour → architectural rules
- **Confusion to pre-empt:** that tests need AWS. They do not; extraction falls
  back to a fixture.

### A5 — Operator

- **Entry:** `docs/operations/deployment.md`
- **Journey:** topology → configuration → database init → migrations → service
  startup → health → troubleshooting
- **Confusion to pre-empt:** that this repository provisions AWS. It does not,
  and has not since `05fb320`.

### A6 — Ecosystem maintainer

- **Entry:** `docs/architecture/system-context.md`
- **Journey:** component boundaries → what KAE-Studio owns → what stays private
- **Must not appear publicly:** account identifiers, private hostnames, secret
  locations, provisioning automation, Studio release coordination.

---

## Documentation tree

Adapted from the suggested structure. Three deviations, each for a reason:

1. **`guides/` is `workflows/`.** Every guide here is a workflow through the
   knowledge lifecycle; naming them so makes the lifecycle the organising idea
   rather than a topic inside it.
2. **No `troubleshooting/` directory.** One page. A directory invites a
   symptom-per-file collection that goes stale faster than anything else in a
   documentation set.
3. **`specifications/` and ADRs stay where they are**, outside `docs/`. They are
   contracts and decisions, not documentation, and moving them would make
   `docs/` the place normative content lives — which is the mixing Phase 1
   removed.

```text
README.md                          concise entry point, not the manual
docs/
├── index.md                       landing and map
├── getting-started/
│   ├── quickstart.md
│   ├── connect-mcp-client.md
│   └── first-project.md
├── concepts/
│   ├── knowledge-lifecycle.md
│   ├── provenance-and-evidence.md
│   ├── clarifications-and-unknowns.md
│   ├── readiness.md
│   ├── context-assembly.md
│   └── modules-and-dependencies.md
├── workflows/
│   ├── submit-observations.md
│   ├── review-knowledge.md
│   ├── answer-clarifications.md
│   ├── retrieve-and-search.md
│   ├── assemble-context.md
│   └── deliverables.md
├── reference/
│   ├── mcp-tools.md
│   ├── http-api.md
│   ├── capability-matrix.md
│   ├── response-policy.md
│   ├── access-and-mutation-policy.md
│   ├── configuration.md
│   └── errors.md
├── architecture/
│   ├── system-context.md
│   ├── components.md
│   ├── persistence-and-providers.md
│   ├── retrieval-and-assembly.md
│   └── security-boundaries.md
├── operations/
│   ├── deployment.md
│   ├── health-and-monitoring.md
│   ├── migrations-and-upgrades.md
│   └── troubleshooting.md
├── development/
│   ├── local-setup.md
│   ├── testing.md
│   └── repository-layout.md
├── examples/
│   ├── cross-session-continuity.md
│   └── sparse-project-walkthrough.md
├── glossary.md
└── assets/
    └── diagrams/
```

**34 pages.** Counts and phases are in the manifest.

---

## Canonical ownership

One home per idea. The rule that matters: **a normative statement appears once,
and everything else links to it.** Documentation that restates a rule diverges
from it, and the copy is always the one someone reads.

| Content | Canonical home | Never duplicated into |
|---|---|---|
| Why a decision was made | `specifications/ADR/` | anything under `docs/` |
| Current technical contract | `specifications/` | `docs/reference/` |
| What an interface exposes | `docs/reference/` | guides, concepts |
| The access/mutation rule | ADR-0027 — `docs/reference/access-and-mutation-policy.md` *summarises and links* | anywhere else |
| Capability differences | `src/kae_memory/capabilities.py` → generated into `docs/reference/capability-matrix.md` | hand-written lists |
| Response tiers | `src/kae_memory/mcp/response_policy.py` → `docs/reference/response-policy.md` | tool reference |
| Configuration keys | `docs/reference/configuration.md` | deployment, local-setup |
| Terminology | `docs/glossary.md` | inline redefinitions |
| Verification status | `specifications/VERIFICATION_GATES.md` | product claims |
| Private operations | KAE-Ecosystem | anything public |

**`README.md` is an entry point, not the manual.** It currently carries a
milestone table, a code inventory and a file-layout table — development-facing
content that survived the migration because it was not in `docs/`. Phase 2B
should reduce it to: what this is, what it is not, quickstart, and links.

### A specification serving too many roles

`specifications/AGENT_COLLABORATION.md` is part contract, part explanation, part
guidance for writing agents. Its normative content belongs in the specification;
its explanatory half is `docs/concepts/`. **Not rewritten in Phase 2A** — mapped:
Phase 2B extracts the explanation and leaves the contract, and the specification
keeps authority.

---

## Public / private boundary

| Public KAE-Memory documentation may describe | Stays in KAE-Ecosystem |
|---|---|
| Supported topology, prerequisites | AWS account identifiers, region topology |
| Provider-neutral configuration | Private hostnames, environment inventories |
| Database initialisation, migrations | Provisioning automation |
| Service startup, health checks | Secret and credential locations |
| MCP and HTTP exposure, security boundaries | Ecosystem release coordination |
| Operator workflows, troubleshooting | KAE-Studio deployment |

**No public page links into KAE-Ecosystem or names a path inside it.** Historical
material is cited by name where it matters, without a location.

---

## Phase sequencing

**2B — MCP-first core.** The pages a person needs to use this at all, in
dependency order: glossary and lifecycle concept first (everything else uses
that vocabulary), then reference (generated where possible), then workflows,
then getting-started — written last because a quickstart is only honest once the
workflows it compresses are verified.

**2C — Executable validation.** Run every documented command, exercise every
tool named, verify schemas and outputs against live responses, confirm
cross-session continuity, check health endpoints. Correct from results.
**Pages carrying E4 claims cannot be published before this.**

**2D — Visual evidence.** Diagrams from validated flows, real client captures,
navigation and consistency review. Studio visuals only if Studio is ready, and
never as a blocker.

The sequence departs from the suggested one in a single way: **quickstart moves
from first to last within 2B.** Writing it first means writing it from
expectation, and a quickstart that fails at step three costs more trust than
having no quickstart.
