# Next-Phase Target Checklist

Status: **active register**, opened 2026-08-05.
Orientation: [`NEXT_PHASE_FULL_CONTEXT.md`](../00_project/NEXT_PHASE_FULL_CONTEXT.md).
Predecessor: [`MCP_TARGET_CHECKLIST.md`](MCP_TARGET_CHECKLIST.md) — **closed**,
T1–T25 complete.

Targets are numbered **N1…** in one namespace, so a target number never means
two things. Phase letters continue from the closed register, which ended at
Phase G.

## How to use this file

One target, one pull request, one bounded action context. A target is checked
only when its acceptance evidence exists in code, tests, or a recorded run —
not when the work is believed finished. Where a target is deliberately not
built, it stays unchecked with the reason recorded, the same way T25.3 and
T25.4 are: an unchecked box that means "decided against" is more useful than a
missing row.

**This register does not own the focus files.** Each target names the focus file
that defines its action boundary; the focus file is the instruction, this is the
tracking.

---

## Phase H — Backend interface readiness

Focus: [`focus/BACKEND_INTERFACE_READINESS.md`](../00_project/focus/BACKEND_INTERFACE_READINESS.md)

The MCP surface exposes substantially more of the application layer than HTTP
does, and Studio is an HTTP client. Everything else in this phase follows from
settling that.

- [x] **N1** — Capability inventory —
  [`ADAPTER_CAPABILITY_MATRIX.md`](../06_architecture/ADAPTER_CAPABILITY_MATRIX.md),
  2026-08-05. Nine services, 15 MCP tools, 28 HTTP routes, 24 registered
  capabilities. **Twelve are Studio-required and absent from HTTP.** The
  asymmetry runs both ways — HTTP can start and stream an agent run and record
  blockers and contradictions, MCP cannot — which is what makes it drift rather
  than backlog. Supersedes KAE-Studio's `CAPABILITY_MATRIX.md`, pinned to
  `de37cc4` before Phases C, D, E, T24, and T25.
- [x] **N2** — Adapter ADR —
  [`ADR-0023`](../../specifications/ADR/ADR-0023-http-and-mcp-as-peer-adapters.md),
  **accepted** 2026-08-05. HTTP is Studio's transport, MCP
  is the agent's, both adapt the same application services, and four exceptions
  are declared rather than left to be discovered. Records what it does *not*
  decide: the conversation scope question, briefing vs blueprint, and the three
  absent domain concepts a router must not invent.
- [x] **N3** — HTTP exposure of Studio-required services — 2026-08-05. Ten
  routes across two routers: search, document ingestion, clarification list and
  answer, context assembly, knowledge reject and correct, operational state,
  classifications, and settle. 28 routes to 38.

  Contract decisions worth their reasons: ingestion is **202**, because nothing
  has been read yet and a 201 would claim a readable resource exists; listing
  clarifications is **POST**, because it materialises the questions it returns
  and a GET that mutates is one a prefetch or retry performs again; assembly is
  **GET**, because it is deterministic and creates nothing — and `package_id`
  is explicitly not deliverable identity, which is a concept this repository
  does not have and a router must not invent.

  **The parity test found a real defect before merge.** MCP resolves to lexical
  search when the embedder cannot rank by meaning; the new route reached
  straight for the vector path and returned nothing where MCP returned results.
  Whether to answer by meaning or by words is a property of the configured
  embedder, not of the transport that asked, so it moved into
  `RetrievalService.best_effort` rather than being copied into a second
  adapter. `StaleVersionError` also gained a 409 mapping — it had been falling
  through to a 500.

  Still absent from HTTP by decision: project-scoped conversation reads (N13),
  the briefing (matrix row 10 — a contract question, not a missing endpoint),
  and anything requiring durable deliverables, modules, or publication.
- [x] **N4** — Classification lifecycle closure — 2026-08-05. Three tools:
  `kae_get_operational_state` (filter by state, kind, subject; paged),
  `kae_get_classifications` (filter by tier; paged), and
  `kae_settle_operational_record`. Transition rules live in the domain as
  `ensure_operational_transition`, modelled on the knowledge lifecycle: a
  proposal may be accepted, refused, or lapse, and terminal states are terminal
  — a recurrence is a new record, not a reopening that erases the fact that
  this one closed.

  **Settling is not verifying.** Accepting a reported completion records that a
  person took responsibility for the claim; the record keeps `authority:
  agent_reported` and `verification: reported`, and `actor` is required for the
  same reason `reviewer` is on confirmation.

  Supersession now has a caller, and wiring it exposed a defect T24's tests
  could not have caught: `superseded_by` was a UUID column, but supersession is
  by classifier **version** — one old classification is not replaced by one new
  row, a whole result set is retired. Migration `0012` retypes it to
  `superseded_by_version`. No data was lost, because nothing had ever written
  the column, which is the same fact from two directions: a column nothing
  writes is a column whose type nothing checks.
- [x] **N5** — HTTP trust boundary —
  [`ADR-0024`](../../specifications/ADR/ADR-0024-http-trust-boundary.md),
  2026-08-05. Bearer tokens via `KAE_API_TOKENS`, constant-time comparison,
  project authorisation applied **by path** so a route added later is covered
  the day it is added. An unauthorised project returns 404, not 403 — telling a
  caller a project exists is itself a disclosure.

  **A process that would listen off-loopback without a token refuses to
  start.** Not a warning: a warning about an unauthenticated public API is a
  line in a log a deployment scrolls past, and the failure it predicts arrives
  later as a request nobody was watching for. Supersedes ADR-0014's accepted
  "no authentication" risk, whose mitigation was a network boundary a browser
  client is designed to cross.

  Also: 2 MB body ceiling refused before the body is read, and `X-Request-ID`
  on every response including refusals.

  **Not built, and stated rather than implied:** rate limiting (a token bucket
  in one process is not a rate limit when two run, and it would imply abuse is
  bounded when it is not — that belongs to whatever terminates TLS), timeouts
  (the ASGI server's), and token rotation or expiry. Path-based authorisation
  also cannot cover `/v1/knowledge/{id}`, `/v1/sessions/{id}`, or
  `/v1/runs/{id}`, which name a resource whose project is only knowable after a
  lookup; a scoped token still reaches those.
- [x] **N6** — Adapter capability registry — `src/kae_memory/capabilities.py`,
  2026-08-05. 28 capabilities, each with an exposure and — where asymmetric — a
  reason the dataclass refuses to be constructed without. 98 tests walk it
  against the real `TOOL_DEFINITIONS` and the real OpenAPI route table.

  **The reverse check is the one that prevents recurrence:** a tool or route
  that is *not* registered fails the suite. The twelve-capability gap N1
  measured did not happen because anyone decided HTTP should lack search; it
  happened because nothing noticed, for five phases, that each new target
  landed on one adapter. A register nobody has to remember to update is a
  register that describes the past.

**Phase acceptance: met.** Every Studio-required capability is reachable over
HTTP, or is a recorded exception with a reason. Remote deployment cannot start
unauthenticated. Divergence now fails a test rather than surfacing months later
in a document.

**Phase H is complete.**

## Phase I — Configuration and service messages

Focus: [`focus/CONFIGURATION_AND_MESSAGES.md`](../00_project/focus/CONFIGURATION_AND_MESSAGES.md)

- [ ] **N7** — Audit settings, loaders, validation, and effective-value
  resolution; establish governed backend configuration.
- [ ] **N8** — Backend service messages under the same governance. Not a
  mechanical centralisation of every numeric literal, which the orientation file
  explicitly rules out.

## Phase J — Frontend separation

Focus: [`focus/FRONTEND_SEPARATION.md`](../00_project/focus/FRONTEND_SEPARATION.md)

- [ ] **N9** — Survey what `frontend/` is load-bearing for — backend tests,
  deployment assets, demonstration paths — and preserve the requirements worth
  keeping. 24 tracked files; the 160M on disk is untracked `node_modules`.
- [ ] **N10** — Supersede ADR-0009 before deletion. It is an accepted decision
  for the embedded UI, and the Studio ownership boundary needs a decision that
  replaces it rather than a commit that contradicts it.
- [ ] **N11** — Remove the embedded frontend once N9 has disproved the
  dependencies.

## Phase K — Studio integration

Focus: [`focus/STUDIO_INTEGRATION.md`](../00_project/focus/STUDIO_INTEGRATION.md)
· Studio side: `docs/planning/PRODUCT_CONTRACT_ALIGNMENT.md`

**Blocked on Phase H.** Integrating against an interface that cannot reach
retrieval, ingestion, clarification, assembly, or classification would design
the product around the gap.

- [ ] **N12** — Reconcile Studio's consumer contract against N1. Three of the
  prototype's port methods assume durable concepts Memory does not have:
  `confirmFinding` (findings are computed, not stored), `listDeliverables`
  (assembly describes, it does not persist a deliverable), and `deferDecision`
  (no durable meaning anywhere).
- [ ] **N13** — Project-scoped conversation read. Studio needs
  `listMessages(projectId)`; Memory reads messages by session only.
- [ ] **N14** — `submitMessage` path: Studio's port is project-scoped, the route
  is `POST /v1/sessions/{session_id}/messages`. Either the client resolves a
  session or Memory offers a project-scoped write. Small, and it lands in the
  first slice.
- [ ] **N15** — First vertical slice on real HTTP: project selection through
  first proposal review, with unavailable, queued, partial, proposed, and
  complete visibly distinct.

## Phase L — Engine and proof gaps

Focus: [`focus/ENGINE_AND_PROOF_GAPS.md`](../00_project/focus/ENGINE_AND_PROOF_GAPS.md)

- [x] **N16** — Relationship vocabulary —
  [`ADR-0025`](../../specifications/ADR/ADR-0025-relationship-vocabulary.md),
  `domain/relationships.py`, 2026-08-05. **Two registers, not one.** The four
  lists were never four versions of one thing: three describe system structure
  and one describes how statements relate, which is exactly why `depends_on`
  appeared in three of four. One statement does not depend on another.

  Epistemic — `supports`, `contradicts`, `supersedes`. Structural —
  `depends_on`, `owns`, `exposes`, `consumes`, `satisfies`, `verified_by`,
  matching Studio's `MODULE_SPECIFICATION.md` §4 exactly, because a vocabulary
  the consumer must translate gets translated twice and differently.

  **The epistemic register shrank from seven to three.** `derives_from`,
  `implements`, `validates`, and `blocks` had no writer and no stored row —
  verified: zero rows in `knowledge_relationships`. Two were structural all
  along and moved; two were retired with their reason. A term nobody writes has
  no defined meaning, and the first caller would have invented it.

  Retired names now raise with what replaced them, because three of the four
  source documents use at least one.
- [x] **N17** — Module relationship model — `domain/modules.py`,
  `application/module_service.py`, migration `0013`, 2026-08-05. The write path
  the platform never had: `record_contradiction` was the only thing creating an
  edge, which is why the graph, the build order, and module context were all
  blocked behind one absence rather than five.

  **Cycles are refused at write time**, not detected at read time — a graph
  checked only when traversed stores state it cannot answer from, and the
  caller who discovers that is the one who least caused it. Ownership is
  exclusive. A self-edge is refused as a typo rather than reported as a cycle,
  so it does not bury the real ones. The database carries what DDL can express;
  cycles and exclusivity are refused in the service, because no constraint sees
  the whole graph.
- [x] **N18** — Module graph traversal — 2026-08-05. Dependencies and
  dependents together, because they answer opposite questions a reader needs at
  once: what must exist before I build this, and what breaks if I change it.
  Build order is Kahn's algorithm over `depends_on`, ties broken by identifier
  so the answer is stable — an order that varies cannot be compared to the
  previous one, which is most of what a build order is for. A cycle raises
  rather than returning a partial order, because a truncated order looks like
  an answer.
- [x] **N19** — Module-scoped context — 2026-08-05. `kae_get_module_context`
  answers instead of reporting a gap. Statements come from `satisfies` and
  `verified_by` **edges**, not from matching the module's name against text:
  "these statements mention approval" and "this module satisfies these
  requirements" are different claims, and the old behaviour could only make the
  first.

  Dependencies arrive as **stubs**. An implementer needs what a dependency
  offers, not how it is built; expanding them would reproduce the project one
  edge at a time, which is what a module scope exists to prevent.

  A project with no modules still gets the gap payload and its labelled
  substitute — module scope is genuinely unavailable *for that project* — but
  the way out now exists, so the next steps name it instead of saying this
  needs a product change.
- [ ] **N20** — Durable deliverable identity. Assembly `package_id` is a fresh
  UUID per call; a listable deliverable is a different concept and needs a
  persistence and ownership decision, not a router that invents one.
- [ ] **N21** — Artifact rendering and publication records. Nothing exists.
  Constraint from the orientation file: no package bytes or publication side
  effects in Memory without a new persistence and ownership decision.
- [ ] **N22** — Remote MCP tenancy and authentication. Distinct from N5, which
  is the HTTP boundary.
- [ ] **N23** — Live deployment proof.

## Dependencies outside this repository

- **A trusted Studio backend does not exist.** Studio is a Vite SPA with no
  server. Both focus files route publication credentials to "a trusted Studio
  backend or approved local agent", and only the second branch exists today.
  This is a deployment-topology decision, not a work package inside contract
  alignment, and N21 should not assume it.
- Publisher implementations, settings UI, and interview orchestration are
  Studio-owned and are not tracked here.

## Recording rules

Carried from the closed register, because they are what made it usable:

- A target names its evidence — a file, a test, a measured run — not an opinion.
- A deliberate non-implementation stays unchecked with its reason, so a decision
  is never mistaken for a backlog item.
- Where a target is completed with a departure from its design, the departure is
  recorded on the target rather than left for a reader to discover in code.
