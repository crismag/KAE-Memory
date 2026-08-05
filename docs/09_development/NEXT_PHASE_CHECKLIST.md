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
  **proposed** 2026-08-05, awaiting acceptance. HTTP is Studio's transport, MCP
  is the agent's, both adapt the same application services, and four exceptions
  are declared rather than left to be discovered. Records what it does *not*
  decide: the conversation scope question, briefing vs blueprint, and the three
  absent domain concepts a router must not invent.
- [ ] **N3** — HTTP exposure of Studio-required services, one contract at a time.
  Bounded responses, pagination where data grows, explicit revision identity,
  honest queued and partial states. No lifecycle, validation, readiness, or
  idempotency logic duplicated in a router.
- [ ] **N4** — Classification lifecycle closure: filterable, pageable reads for
  classified observations and operational state; the accept, reject, resolve,
  and supersede transitions the domain already models; and a caller for
  `ClassificationRepository.supersede_older_versions`, which exists today with
  no path to it.
- [ ] **N5** — HTTP trust boundary: authentication, project authorisation kept
  separate from it, explicit CORS allowlists, request-size and rate and timeout
  bounds, safe external errors with correlation ids. Local development may have
  a documented development mode; **remote deployment fails closed.**
- [ ] **N6** — Adapter parity tests: a declared capability registry that fails
  when something required on both adapters is exposed by only one. Behaviour
  parity, not envelope parity — transport serialisation may differ.

**Phase acceptance.** A Studio-required capability is reachable over HTTP with
the same domain behaviour as its MCP equivalent, or is recorded as an
intentional exception. No unauthenticated remote access. Divergence fails a
test rather than surfacing months later.

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

- [ ] **N16** — **Relationship vocabulary.** Four competing lists exist and only
  `depends_on` appears in three. Names are near-impossible to change once graph
  data exists, so this is settled *before* any relationship is written. **Gates
  N17–N19.**
- [ ] **N17** — Module relationship model: how a module owns, depends on, and
  exposes.
- [ ] **N18** — Module graph traversal: dependents, dependencies, build order.
- [ ] **N19** — Module-scoped context assembly, replacing the capability gap
  `kae_get_module_context` currently reports honestly.
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
