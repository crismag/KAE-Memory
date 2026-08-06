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

## Phase T — Test execution

Opened 2026-08-05 after the suite became the development bottleneck: 25 full
gates in one session at roughly six minutes each, against test bodies that take
31 seconds in total.

- [x] **N47** — Test execution architecture — 2026-08-05.

  *Measured, 2026-08-05, 1,340 tests in 277s:*

  | Phase | Time | Share |
  | --- | ---: | ---: |
  | **setup** | **236s** | **86%** |
  | call | 31s | 11% |
  | teardown | 8s | 3% |

  **The tests are fast. The fixtures are not.** 854 timed setups, mean **277ms**,
  and the cause is one line: `factory` runs `TRUNCATE` across all 20 mapped
  tables before every test. Schema creation is already session-scoped and is not
  the problem.

  By directory: `mcp_adapter` 107s, `api` 55s, `application` 50s, `persistence`
  18s, everything else under 14s. The worst single file is
  `test_adapter_parity.py` at 20.8s of setup — 107 parametrised cases each
  paying a truncate to build an app whose OpenAPI table needs no data at all.

  *Scope:*

  1. **Per-test isolation by transaction rollback, not truncation.** The current
     comment rejects rollback because "the application opens its own sessions
     and commits them". That objection is answerable: binding the sessionmaker
     to one connection inside an outer transaction, with a SAVEPOINT restarted
     on each commit, preserves commit semantics from the application's view and
     discards the work at test end. Expected 277ms → single-digit ms.
  2. **Keep truncation available as an opt-in** for tests that genuinely need
     real cross-connection commits — concurrency, idempotency-under-race,
     anything asserting a unique index fires. Those exist and must keep working;
     the marker names them rather than the default punishing everyone else.
  3. **No database fixture for pure domain tests.** 21 files already take none.
     Several domain-directory tests request `factory` for a service they
     exercise; those are service tests and should say so.
  4. **Markers**: `unit`, `db`, `contract`, `e2e`, `provider`, `migration`,
     `slow`. Five exist; the split that matters is a default run excluding
     `migration` and `provider` — the single slowest entry in the suite is a
     7.3s migration teardown.
  5. **Documented changed-area commands**, so "run the affected subset" is a
     command someone can copy rather than a judgement call each time.
  6. **Consolidation only where behaviour genuinely duplicates**, into curated
     parameterised cases. **No regression test is removed without naming the
     exact surviving test or contract that catches the same defect** — recorded
     in the commit, not just believed.

  *Targets:* focused developer tests under 30s; affected-area under 90s; full
  PostgreSQL gate materially under 277s and run once per completed target.

  *Non-goals:* deleting coverage to make a number; SQLite; skipping the database
  for tests whose subject is persistence.

  *Delivered.* Isolation is by rollback with
  `join_transaction_mode="create_savepoint"`, so application commits release
  savepoints and commit semantics are exactly what the application sees.

      full gate     277s -> 38s   (77s with coverage, from ~347s)
      setup         236s -> 16.4s
      domain+service        5.6s
      adapters+api+e2e     26.7s

  All 1,340 tests still pass; none deleted, skipped, or weakened. One test needed
  the old behaviour — `test_concurrent_retries_create_exactly_one_record`
  asserts a unique index firing across two connections, which rollback cannot
  express — and carries `@pytest.mark.real_commits`, truncating before *and*
  after, because its writes are real and the next test's rollback cannot undo
  what it never saw.

  **Acceptance partially met, honestly.** Setup share is 45%, not the 30% I set,
  because the denominator collapsed: absolute setup fell 14x. The relative
  metric was a poor choice — once the fixture is cheap, the share converges on
  whatever connection handling costs, and driving it lower would mean making
  tests slower.

  **Not done:** duplicate-behaviour analysis across layers. At a 38s suite the
  payoff is small and the risk is losing a regression whose equivalent I would
  only *believe* survived. It belongs in its own target with the
  name-the-surviving-test rule enforced per removal.

## Phase I — Configuration and service messages

Focus: [`focus/CONFIGURATION_AND_MESSAGES.md`](../00_project/focus/CONFIGURATION_AND_MESSAGES.md)

- [x] **N7** — Governed backend configuration — `src/kae_memory/settings/`,
  [`CONFIGURATION_INVENTORY.md`](CONFIGURATION_INVENTORY.md), 2026-08-05.

  The value lives in `defaults.toml`, the contract in `catalog.py`: stable
  dotted key, type, unit, rationale, scope, reload behaviour, override
  variable, range, optional non-overridable ceiling, and the cost of changing
  it. A catalog entry with no committed value is refused, and so is a value out
  of range — **at construction**, because the first call that reads a setting
  is reliably the one furthest from anyone who could fix it.

  Precedence is three layers: coded ceiling, environment, committed default.
  The administrative and project-level layers the focus file reserves are
  **deliberately absent** — both need an authorisation model this repository
  does not have, and the plumbing before the authority is a system overridable
  by whoever reaches it first.

  An out-of-range override is **refused, not clamped**: a caller silently given
  a different number than they asked for will debug everything except the
  number. An exported-but-empty variable is not an override.

  **The audit found a real defect.** `MAX_PAGE_SIZE` in the MCP response policy
  and `MAX_PAGE` in the HTTP router were the same number written twice with the
  same docstring, and nothing would have noticed them diverging. One governed
  value now, and a test asserts the two are the same object rather than merely
  equal.

  `explain()` reports where every effective value came from, and
  `unknown_overrides()` reports `KAE_*` variables that govern nothing — a
  variable nothing reads is worse than no variable, because someone sets it,
  watches nothing change, and concludes the setting is broken.

  **TOML rather than the YAML the placement table names.** `tomllib` is in the
  standard library and read-only, which is the exact shape of a file the
  application never writes; YAML would have added a dependency to gain nothing.

  Migrated: the pagination and response-limit slice, chosen because T4/T5
  already test its contract. Classified and **not** migrated, with reasons in
  the inventory: security ceilings, tokeniser constants, readiness thresholds,
  worker and ingestion knobs, provider selection, and every secret.

- [x] **N8** — Backend service messages — `src/kae_memory/messages.py`,
  2026-08-05.

  Narrow on purpose, and the focus file's ruling-out of mechanical
  centralisation is the reason: four hundred keys nobody reads, plus a message
  you cannot understand without opening a second file, is a worse problem than
  the one it solves. A test bounds the catalog at twenty entries so growth is a
  decision rather than a habit.

  What earned a stable key: the **integrity notes** both adapters say, the
  **cross-adapter refusals**, and the **environment failures**. Each integrity
  note is a caveat about what a response does *not* establish, which is why
  drift there is not cosmetic — an adapter that softened its copy would claim
  more than KAE knows.

  They had already drifted. Three copies of "Reported, not verified" existed
  and two ended differently; the capability refusal had eight near-identical
  copies. Neither divergence was a decision.

  **One split rather than a merge.** The two classification notes looked like
  drift and were not: a read cannot change an operational status and must not
  deny having done so, because a caveat about an action nobody took reads as
  reassurance about the wrong thing.

## Phase J — Frontend separation

Focus: [`focus/FRONTEND_SEPARATION.md`](../00_project/focus/FRONTEND_SEPARATION.md)

- [x] **N9** — Frontend dependency survey —
  [`FRONTEND_SEPARATION_SURVEY.md`](FRONTEND_SEPARATION_SURVEY.md), 2026-08-05.

  Every dependency traced and disproved: **no backend test, migration,
  deployment script, or documented workflow required `frontend/`.** The three
  occurrences of the word in `src/` and `tests/` are prose in docstrings
  explaining why a capability exists.

  **One thing was load-bearing, and it was not the frontend.** CI regenerated
  the OpenAPI document and diffed it against the checked-in copy — a guard
  against a backend contract change nobody carried into the record, living in a
  frontend directory for historical reasons. Deleting the directory would have
  removed the only automated notice that the HTTP surface changed shape, during
  the phase that adds routes to it.

  Moved to `specifications/openapi.json` with
  `tests/api/test_recorded_contract.py` as the guard — **stricter than what it
  replaced**: whole-document comparison, in the command a developer already
  runs, needing no Node toolchain.

  The six panels' *requirements* are mapped to the adapter capabilities that
  already serve them (N3, N6) and to Studio as their destination. The
  implementation is not transferred; the focus file rules out copying the old UI
  wholesale, and Studio has its own service interfaces already.

- [x] **N10** — Supersede ADR-0009 —
  [`ADR-0026`](../../specifications/ADR/ADR-0026-kae-memory-is-headless.md),
  **accepted** 2026-08-05.

  Most of ADR-0009 was never about React, and the ADR says which parts survive:
  the application boundary (now between repositories rather than layers), "the
  browser does not own the run", and the three-kinds-of-state observation —
  *a chat-only interface would hide most of what KAE-Memory does, because the
  memory, the provenance, and the recovery are all invisible in a transcript.*

  It also carries forward ADR-0009's sharpest warning: vocabulary had drifted
  three times, and hand-written TypeScript interfaces are never reconciled once
  written. That risk did not disappear with the frontend — it crossed a
  repository boundary, where it is harder to see. The recorded document and its
  guard are the mitigation.

- [x] **N11** — Remove the embedded frontend — 2026-08-05. 24 tracked files,
  two Make targets, the `generate-client` half of `openapi`, and the CI
  `frontend` job. The local development script runs the database, API and
  worker and says out loud that the absence of a UI is the product.

  Descriptions corrected in `README.md` and `LOCAL_DEVELOPMENT.md`:
  KAE-Memory is a headless knowledge service.

  **The loss is real and stated rather than glossed:** the six panels
  demonstrated what the system does in a way no API response does, and Studio
  does not exist yet as an integration. What replaces the demonstration is the
  adapters, which is honest about what this repository contains.

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
- [ ] **N33** — **Studio setup and target-management contracts.** Extends N12.
  Studio's `PublishTarget` is keyed by *kind* alone — `'github' | 'local' |
  's3'` — with no target identity and no per-project registration, which the
  registered-target model (N27) makes incompatible. Also needs: the setup
  conversation, proposed-setup confirmation, unresolved setup questions,
  default destination selection, and per-publication override.
  *Non-goals:* Studio collecting or displaying any raw credential.
- [ ] **N39** — **Studio generate-with-assumptions workflow.** Actions:
  continue interview, add sources, review important questions, let KAE
  recommend, generate with assumptions, accept current knowledge, prepare
  package, publish, return to setup later. **Generation is never disabled by a
  score or a completion percentage.**
- [x] **N40** — Generation-policy contract — `domain/generation_policy.py`,
  2026-08-05. **One field**, scoped to what N42 needed:
  `generation_policy.discovery_extraction`, `on_submission` by default and
  `disabled` as the per-call opt-out.

  Room preserved without vocabulary invented. A dataclass takes a field without
  changing a signature and an enum takes a value without changing a type, and a
  test asserts the policy holds exactly one field today — so broadening it is a
  decision rather than a drift. The wider vocabulary the product context
  sketches arrives with the callers that need it.

  **An unrecognised key is refused, not ignored.** Accepting one would let a
  caller believe they configured behaviour they had not, and that failure
  surfaces later as the system ignoring an instruction rather than immediately
  as a rejected request.

- [ ] **N15** — First vertical slice on real HTTP: project selection through
  first proposal review, with unavailable, queued, partial, proposed, and
  complete visibly distinct.

## Phase O — Progressive acquisition and user-controlled sufficiency

Product context: *KAE Progressive Knowledge Acquisition, User-Controlled
Sufficiency, and Non-Blocking Generation*, 2026-08-05.

> Incomplete, uncertain, or minimal project knowledge is a normal project
> condition — not a failure, and not by itself a reason to stop generation.

**Placed before Phase M deliberately.** Setup, configuration, and publication
all inherit this rule: requiredness is evaluated against a requested capability,
never globally. Designing them first would bake in the gate this phase exists to
prevent.

- [x] **N0-proof** — **Thin vertical proof** —
  `tests/integration/test_thin_vertical_proof.py`, 2026-08-05. 21 tests, one
  journey: sparse project → current knowledge → assemble → record → verify
  reproduction and publication eligibility. **No publication**, deliberately.

  Every subsystem it crosses was already tested and none of them had ever met.
  1,235 tests proved each piece and nothing proved the seams — and what a suite
  like that hides is not a broken part but six correct parts that disagree
  about what they hand each other. It passed first run, which is evidence
  rather than luck only because it asserts the principle rather than the
  plumbing.

  Six claims, each a stage: sparse knowledge is valid input; proposed knowledge
  participates when the policy allows; missing information becomes a recorded
  assumption rather than a failure; the user may accept the current knowledge
  boundary; recording needs no publication target; and only reproduction,
  integrity, and publication are blocked — each for its own reason, without
  spreading.

  **Extended, never replaced.** N20.2 and N36 add stages to this journey. A
  second integration fixture would let the two drift and double the cost of
  every later change to the pipeline.

### Manual test, 2026-08-05 — **FAILED**, capability gap confirmed

A project was created from one sentence: *"I want an inbox where I can dump
thoughts and have them turned into useful things."* Every subsystem behaved
correctly and the result was useless.

    idea -> evidence recorded -> unclassified -> no candidate knowledge
         -> assembly sees nothing -> empty package

Readiness blocked nothing, which is the N34 principle working. The pipeline is
sound. **What is missing is the interpretation that turns natural product
language into something the pipeline can carry**, and no amount of retrying
assembly produces it.

**Revised diagnosis, 2026-08-05.** The first reading — "the classifier cannot
interpret product language" — was wrong, and inspecting the code before
implementing is what caught it.

**Model-backed extraction already exists, is wired, and is reachable.**
`BedrockExtractionAdapter` runs a Claude model behind `ExtractionPort`
(ADR-0006), and the `requirements.v1` prompt already says: *"If the text implies
something without stating it, record it as an assumption; if it raises a
question it does not answer, record that as an unknown."* `KnowledgeKind`
already carries `ASSUMPTION` and `UNKNOWN`, and every candidate must quote its
source span verbatim.

So KAE can already interpret language into candidates, assumptions, and
unknowns. **It cannot be reached from a conversational observation.** Extraction
is enqueued from exactly two places — `ingestion_service` for documents and
`clarification_service` for answers. `kae_submit_observation` enqueues nothing.

The failure is therefore **one missing edge in the graph**, plus a prompt tuned
for requirement-bearing text rather than sparse product intent. Neither is a
missing understanding capability.

**The assistant demonstrated the target behaviour in the same session**, which
makes this test a specification rather than only a defect report. What it did,
and what N42, N44, N45, N46 must reproduce:

- preserved the user's original statement verbatim;
- interpreted natural product language semantically;
- separated what was known from what was inferred;
- created **reversible** assumptions, each with its consequence if wrong;
- identified the material unknowns;
- distinguished important questions from deferrable ones;
- produced useful preliminary context despite 0% readiness;
- never presented an assumption as a confirmed fact.

- [x] **N42** — Observation to extraction path — 2026-08-05. The missing edge.
  `kae_submit_observation` now enqueues a discovery extraction run, so a
  conversational statement can become a candidate through the same review model
  a document does.

  Contract as specified: the observation stays **verbatim**; the response says
  **queued**, **skipped**, or refused, distinguishably, with the run identifier
  and status — a policy choice must not look like a broken server; extraction is
  **idempotent by the caller's key**, so a retry reuses the run rather than
  paying for a second model call; and everything produced stays **proposed**,
  with readiness unmoved.

  Runs `requirements.v1` until **N46** adds a discovery role. That prompt is
  disciplined about not inventing and will read a sparse product sentence
  thinly — correct behaviour for it, and the reason the edge alone does not
  close the manual test.

  **Decided and recorded:** on submission, one run per observation, opt-out per
  call via `generation_policy.discovery_extraction: disabled`. One model call
  per observation, the shape ingestion already pays per chunk.

- [x] **N46** — Discovery extraction role — `discovery.v1`, 2026-08-05.
  `AgentRole` gains a fourth member, approved with this target.

  The other three read text that already contains what they extract:
  requirements from a stakeholder's own words, architecture from confirmed
  requirements, review from written knowledge. None turns *an idea* into what a
  project now knows it is discussing, and `requirements.v1` reads an early
  description almost to nothing — correctly, since it is disciplined about not
  inferring requirements nobody expressed.

  **One execution path, two instructions.** `DiscoveryAgent` subclasses
  `RequirementsAgent` and the worker branches on a set, so extraction,
  provenance, and the review model are literally the same code. Duplicating the
  method to change one argument would give the two ways to drift apart, with
  one of them quietly wrong.

  The prompt keeps every epistemic rule its sibling keeps — verbatim
  `source_quote`, inference recorded as an assumption with its cost, an
  unanswered question recorded as an unknown — and adds the one thing that
  differs: **incompleteness is normal and is not a reason to return nothing**,
  and a goal is a goal when phrased as a wish. It explicitly forbids answering
  its own unknowns and dressing an assumption as something the speaker said.

  **No rule for any phrasing.** A test asserts the prompt never names "I want",
  because a pattern would pass the acceptance scenario while failing the
  requirement it stands for.

  No test asserts a particular candidate. Output depends on the extractor and
  the model, and asserting "produces an actor" would assert the model's taste —
  failing on a better answer and passing on a worse one that happened to match.

- [x] **N43** — Model-backed semantic classifier —
  `agents/semantic_classifier.py`, 2026-08-05. Resolves
  `OBSERVATION_CLASSIFICATION.md` §15 question 3.

  Behind the existing `ObservationClassifier` protocol, reporting
  `semantic_classification: true` where the deterministic adapter reports
  false. Selected by `KAE_OBSERVATION_CLASSIFIER`, deterministic by default so
  a cloned repository still walks the whole workflow with no account and no
  bill.

  **Deliberately narrow, and it stayed narrow.** This decides a retention tier,
  not what a project knows. Extraction produces candidate knowledge over the
  same text and is a separate path; the first reading of the sparse-project
  failure confused the two, and nothing here encourages that again.

  Three properties do the work. **Offsets are never model-derived** — the
  sentence split happens locally, the model sees numbered sentences, and a test
  asserts the split matches the deterministic adapter's, because a span that
  does not line up sends a reviewer to the wrong text. **An unrecognised class
  becomes `unclassified`, not the nearest match**, which would file it
  confidently in the wrong tier. **It degrades rather than blocks**, and the
  degradation is visible: `last_degraded` distinguishes "the model read this
  and could not tell" from "no model ran", which is the difference between an
  honest `unclassified` and a silent lie about being semantic.

  A missing region at startup is **refused**, not degraded — that is a
  deployment which never had the capability, distinct from a call that lost it.

  `describe()` now reports classification apart from embedding. A deployment
  can rank by meaning and classify by rule; one capability must not answer for
  the other.

  *Value delivered:* better tiering, and operational records from observations
  that mention status. As the target said, neither is what the manual test
  failed on.

- [x] **N44** — Preliminary context generation —
  `application/preliminary_context_service.py`, 2026-08-05.

  The composition the manual test was missing. Every subsystem held a piece —
  candidates in one place, assumptions in another, questions in a third — and
  assembly showed only confirmed knowledge, of which a one-sentence project has
  none. Nothing put them together, so KAE had everything it needed to be useful
  and was not.

  Four collections that **never merge**: what was stated verbatim, what a
  person confirmed, what was proposed or assumed, what nobody has decided. Not
  one annotated list, because a reader under time pressure reads structure
  before labels, and a document whose reader cannot tell a confirmed
  requirement from a plausible guess is the same document with the warning
  removed.

  `stated_verbatim` carries the actor. An observation an agent relayed and a
  sentence a person typed are not the same evidence, and flattening them would
  overstate the second — which matters most here, where the relayed sentence is
  often the only thing the project has.

  **It reads and never writes**, which is what makes "never refuses" safe
  rather than reckless: it cannot confirm, accept, or promote, so there is no
  state where producing it is a risk. Low readiness produces a thinner context;
  an unknown project is still a 404. Unknowns are split material versus
  deferrable so ten helpful questions never make a project look blocked, and
  material means "spend attention here first", never "stop".

  It carries the assembly's statement pins, so a deliverable recorded from
  preliminary context is reproducible in fact rather than in appearance
  (N20.1).

  Adapters both ways: `kae_get_preliminary_context` and
  `GET /v1/projects/{id}/preliminary-context`, with `context.preliminary` in
  the capability registry. The twenty-seventh tool, and a genuinely different
  question from `kae_assemble_context` — that one answers "what has this
  project settled", which for a sparse project is "nothing"; this one answers
  "what can you usefully say anyway". Merging them would mean an assembly that
  quietly included guesses.

- [x] **N45** — Assumption adapters — 2026-08-05. Three tools and three routes:
  record, list, accept. The N35 model reached an adapter without being weakened
  on the way.

  Recorded **proposed**, whoever asks — a caller able to record one already
  accepted would be recording a decision nobody made. Accepting names a person
  and is **not** confirming: it says someone is willing to build on a guess,
  which is a weaker and more honest claim than believing it true.

  Tests assert the FR-005 promotion is still impossible **across the adapter
  seam**, not only inside the service that structurally cannot perform it.

  This is what the manual test hit twice. *"I don't know yet. Recommend
  something reasonable for a prototype, but don't make it a permanent project
  decision"* had nowhere to go: answering the clarification would have closed
  it, and the record designed for exactly that case was unreachable. Half of
  that is now fixed; the other half is **N36**, which must let a disposition
  answer a question without closing it.

### The decisive acceptance scenario

**Met, as an automated proof** — `tests/mcp_adapter/test_sparse_project_journey.py`,
2026-08-05. One sentence, one question nobody could answer, one reversible
recommendation, a preliminary context, and a deliverable that pins both the
bytes and the uncertainty. 22 assertions, all against KAE's own state.

The model-backed step is proved by **provenance rather than by output**: the
discovery run exists, names the stored message it will read, and is selected by
role rather than by position. What that run eventually produces is a candidate,
and asserting anything about its wording would be asserting a model's taste.
Running the same journey against a live provider stays useful as a model-path
check and is not the correctness criterion.

The eight epistemic conditions below are each an assertion in that file, and
three of them are the ones worth naming: nothing is confirmed anywhere along
the path, the recorded assumption never becomes a knowledge statement, and
readiness never moves. Those are the failures a system like this actually has —
not producing nothing, but producing something and quietly overstating it.


One ordinary sentence, submitted as an observation:

> *"I want an inbox where I can dump thoughts and have them turned into useful
> things."*

After worker processing, proved **entirely through KAE state** — read from the
database and the adapters, never from the surrounding session:

1. the original observation exists **verbatim**;
2. model-backed discovery extraction **ran**, identified by its run record;
3. **useful** candidate knowledge was produced;
4. every extracted item **traces to the observation** by provenance;
5. inferred material is explicitly **proposed or assumed**, never confirmed;
6. relevant unknowns and questions are **represented without their answers
   being invented**;
7. readiness **does not rise through confirmation** that nobody performed;
8. preliminary assembly **can use** the resulting unconfirmed knowledge;
9. the resulting context **distinguishes known, assumed, and unknown**.

**What the test must not require.** No particular actor, assumption, question,
or count. A test asserting "produces exactly two questions" would be asserting
the model's taste rather than the product's behaviour, and would fail on a
better answer. The requirement is **semantic usefulness plus epistemic
integrity**.

**What makes it proof rather than theatre.** Provenance and run identity. A
candidate that traces to a stored message through a recorded extraction run
cannot have come from the conversation around KAE — the assertion is against
KAE's own state, and the run record says which adapter produced it.

Running the same scenario against `DeterministicExtractionAdapter` stays useful
as a model-path check, and is **not** the correctness criterion: "different or
weaker output" is a comparison whose result depends on both sides, and the
database provenance already answers the question on its own.

### What the inspection found

Three of the fifteen inspection points turned out already satisfied. Those need
regression evidence, not redesign.

**Already correct — preserve and prove:**

- **Readiness does not block generation.** No code path raises on
  `implementation_eligible` or `draft_eligible`; they are advisory and feed
  labels and prose. Nothing uses a score as an authorization decision.
- **Assembly already admits unconfirmed knowledge** through `include_proposed`,
  and labels it rather than hiding it.
- **Capability gaps are already narrow.** `CapabilityUnavailableError` names its
  subject, what is missing, and what to use instead — the shape this context
  asks for.

**Real gaps:**

- **Assumptions have no durable identity.** `StatementLabel.ASSUMPTION` is a
  label applied to an assembled statement, not an entity with provenance,
  confidence, reversibility, or acceptance. Nothing can pin one, disclose one,
  or revisit one.
- **Proposed knowledge is labelled `assumption` during assembly.** Two distinct
  concepts share one word: unconfirmed *knowledge* and a KAE-made
  *interpretation*.
- **Questions have no disposition.** No deferred, no "I don't know", no
  delegation, no revisit trigger. A question is open or answered.
- **The deliverable model cannot record maturity or accepted sufficiency.**
  N20/N20.1 pin what was rendered; nothing records what it was *for*, or that a
  person accepted the knowledge boundary.
- **N20.1 cannot pin assumptions**, because they do not exist as entities.
- **Wording.** `blueprint_service` emits "This blueprint is not authorised for
  implementation" — permission language for an advisory statement.

- [x] **N34** — Progressive acquisition vocabulary and capability readiness —
  `domain/acquisition.py`, `application/capability_readiness_service.py`,
  2026-08-05.

  Readiness is now reported **per capability**. Nine states, split into those
  an operation may proceed from and those it cannot — and **not one of the
  blocking states is about knowledge quality.** They are choice, authorisation,
  integrity, provider, and support: facts about an operation, never judgements
  about how well understood a project is.

  A blocked capability **must** name why and the next useful action, enforced
  in the constructor. "Unavailable" alone leaves a caller unable to act, and a
  dead end is not a state. `available_with_assumptions` must name the
  assumptions, because a caller cannot accept what they were not shown.

  `quality_never_blocks` is checked on every report rather than trusted. The
  inspection found nothing currently gates generation on the percentage — that
  is correct and was undefended, and a future check refusing to assemble below
  a threshold would look reasonable in review and pass every existing test.

  An unknown capability is **permitted**, not refused: a gap in the report must
  not become a gate.

  Wording fixed: "This blueprint is not authorised for implementation" became
  "This blueprint is provisional", and "Draft blueprint — incomplete" became
  "Provisional blueprint". The first was permission language for an advisory
  statement; the second read as a verdict on the project rather than a
  description of the document.

- [x] **N35** — Assumption lifecycle and provenance — `domain/assumptions.py`,
  `application/assumption_service.py`, migration `0016`, 2026-08-05.

  `StatementLabel.ASSUMPTION` was a label on an assembled statement. A label
  cannot be pinned, disclosed, accepted, revisited, or reversed — it lives as
  long as the payload that carried it, so a package generated from thin
  knowledge disclosed its assumptions once and then forgot them.

  **The forbidden promotion is prevented structurally, not procedurally.**
  `AssumptionService` imports no `MemoryService`, holds no reference to
  knowledge, and exposes no confirm — asserted against the module namespace.
  Someone asked to "just promote accepted assumptions" would have to add a
  dependency first, which is a visible change rather than a quiet one.
  `accepted` is the furthest an assumption goes, and there is deliberately no
  state meaning "became knowledge".

  An assumption **must say why it was made**: without a reason a reader cannot
  judge it, and an unjudgeable assumption is a guess with a record attached. An
  accepted one **must name who accepted it**, for the same reason `reviewer` is
  required on confirmation.

  A **material** assumption — architectural, unsafe, or irreversible — cannot be
  marked never-revisit. That is how a prototype default becomes a production
  commitment nobody remembers making.

  Retired and rejected are kept apart: retired means the gap was answered,
  rejected means the guess was wrong, and a reader needs to tell those apart.

- [x] **N36** — Question priority and disposition — `domain/dispositions.py`,
  2026-08-05.

  A response and a settlement are different events, and the clarification
  lifecycle had only the second. The manual test that produced this target hit
  it exactly: "I don't know yet. Recommend something reasonable for a prototype,
  but don't make it a permanent project decision" had no representation.
  Recording it as an answer writes a decision nobody made; recording nothing
  loses both the recommendation and the fact that anyone was asked.

  `settles()` names the three dispositions that close a question — answered, no
  longer relevant, superseded — and it is **stated rather than derived**, so
  adding a disposition is a decision about whether it closes anything.

  Both halves of the acceptance criterion are wired, and they pull opposite
  ways. A non-settling response leaves the question **unresolved** — it never
  leaves `awaiting_a_person` and is counted in the tool's `deferred`. It is also
  **not asked again**: `open_questions` holds it back unless `include_deferred`
  asks for it, because a person who says "I don't know yet" and is asked the
  same thing next call learns to stop reading the list. Held back, not dropped.

  The default idempotency key had to change with it. Keying every response on
  the question alone made the later decision collide with the earlier deferral,
  which would have made deferring a trap; non-settling responses now key on what
  was said. A second *different* decision for one question still conflicts.

  `blocks()` carries the priority half: helpful, important and deferred never
  block, and only capability, authorization and integrity do — asserted as
  exactly three so that widening the set is a decision rather than a drift. This
  is the readiness gate N34 rejected, and this file is where it would have crept
  back in.

  Adapters: `disposition` and `assumption_id` on `kae_answer_clarification` and
  on `POST .../clarifications/{id}/answer`, with `question_settled` in both
  responses so no caller infers it. Delegating without an assumption id is
  refused — a recommendation nobody recorded is one nobody can revisit, which is
  the thing the person asked not to happen.

- [x] **N37** — Mode-aware assembly — `domain/generation.py`, 2026-08-05.

  Five modes (explore, shape, plan, build, validate) declaring what the output
  is *for*. A mode **widens** what is included and qualifies the result; it
  never refuses and never narrows, because narrowing is the shape a gate would
  need. `mode_never_blocks` raises on a mode configured to include nothing, and
  a test asserts **build admits unconfirmed statements** — "build requires
  confirmed requirements" reads as prudence and is the N34 gate in new words.

  Validation is the one mode that includes less, and it narrows *toward*
  disagreement rather than away from doubt: contradictions and assumptions are
  exactly what a reviewer must see.

  **Mode is opt-in.** An unnamed mode changes nothing, so no default moves
  under callers who never asked for one — the same rule that says an override
  must not silently become a default. The pre-N37 contract is asserted intact.

  **The conflation is undone.** `StatementLabel` says where authority comes
  from and is computed from provenance; assembly was using `assumption` to mean
  "nobody has confirmed this", which made a statement KAE inferred and a
  statement awaiting review the same word. Proposed statements now carry
  `label: derived` and `inclusion_class: proposed`, and the two fields answer
  different questions.

  Qualification replaces refusal: a build package with nothing confirmed says
  it is suitable for prototype implementation and is not evidence of production
  readiness, rather than being withheld.

- [x] **N38** — Deliverable maturity and accepted sufficiency —
  `domain/maturity.py`, migration `0017`, 2026-08-05.

  **Maturity is not a ladder.** No rank, no numeric level, no comparison, and
  nothing that decides whether one maturity is "enough" — asserted by tests
  that scan the module for `ORDER`, `RANK`, `LEVEL`, `sufficient`, `at_least`,
  and `meets`. Each of those would be a gate with a friendly name, and this was
  the most gate-shaped idea in the phase.

  Every value says what it *means* in a sentence, because a label nobody can
  act on gets treated as a rank. `production_review_candidate` says the
  reviewer decides and that the label does not claim the review passed.

  A mode **suggests** a maturity and requires none: a caller labelling a build
  package exploratory has described their own output accurately.

  **Accepted sufficiency is a record, not a permission.** It names the purpose,
  the person, the time, and what was disclosed — and carries
  `applies_to: this generation only` in the payload rather than leaving a
  reader to assume it. There is deliberately no field marking a question
  answered: an acceptance that could resolve questions would let "I'll proceed
  anyway" quietly become "these are settled".

  A deliverable resting on unconfirmed statements **must** carry the
  qualification saying so; silence there is the package claiming more than its
  evidence. Not backfilled onto older records — describing a package nobody
  described would be a claim rather than a record.

- [x] **N20.2** — Pin provisional context in reproduction — migration `0019`,
  2026-08-05.

  N20.1 made a package reproduce the same **bytes**. This makes it reproduce
  the same **claim**. A package generated with open questions and an unaccepted
  assumption rested on guesswork; the identical bytes, read after those were
  settled, read as a settled document, and nothing recorded the difference.

  Pinned: the generation mode, the confirmation split, each active assumption
  **at the state it was in**, each unresolved question **with its disposition**,
  and the unresolved gap areas. Assumptions have no version numbers — they have
  a lifecycle, and which state a package rested on is the thing that changes
  what it meant. A question nobody had been asked and a question someone could
  not answer are both unresolved and are not the same uncertainty (N36).

  The constructor lives in `DeliverableService`, not in each adapter. N38
  shipped a model no caller built and every deliverable carried `qualification:
  null`; a field each router had to remember would fail the same way and fail
  silently.

  Nullable and **not backfilled**. Reconstructing a historical record from
  today's assumption states would file what a package would mean now under what
  it meant then — the exact failure the target names.

  **Reported apart from `publication_eligible`.** A pre-N20.2 record can still
  be re-rendered byte for byte, and withdrawing that would be a capability lost
  to a bookkeeping change; `reproduces_uncertainty` answers the separate
  question of whether it can say how much of itself was guesswork.

## Phase M — Preliminary setup and project configuration

> Lettered M and placed before L deliberately. Phase L's rendering and
> publication targets depend on it: a publication target registry has to exist
> before a provider can resolve one, and the alternative — letting the first
> provider define the domain — is what the product context rules out.

Product context: *KAE Preliminary Project Setup, Configuration Acquisition, and
Publication*, 2026-08-05.

The principle these targets serve: **configuration is acquired when possible,
requested only when necessary, remembered once established, and reused silently
during ordinary work.** A normal interaction is "generate the development
package" — not a destination questionnaire.

Phase I (N7, N8) governs **system and deployment** configuration. Nothing in the
register covered **project** configuration or **per-operation overrides**, which
is the gap this phase fills.

- [ ] **N24** — **Preliminary setup domain and vocabulary.**
  *Purpose:* name the stage and its states before anything implements it.
  *Scope:* setup states — not started, discovering, needs input, sufficient to
  begin acquisition, ready for generation, ready for publication, degraded;
  the inference policy as a typed rule rather than prose (adopt and disclose /
  propose / ask / defer / block); provenance and confidence on every inferred
  value.
  *Non-goals:* asking anything; any provider; any UI.
  *Acceptance:* setup readiness is reported **separately from knowledge
  readiness**, and names the exact unavailable capability and the next useful
  action. An unknown publication target does not block repository analysis; a
  missing primary source does block repository acquisition.
  *Tests:* each state reachable; blocking and non-blocking questions separated;
  no inferred credential or authorisation, ever.

- [ ] **N25** — **Setup-question lifecycle.**
  *Decision required first:* whether these reuse the clarification model with a
  purpose field, or need their own. **Evidence says they need their own.**
  `Clarification` is derived from a `Finding` and has no identity until
  materialised; it carries `finding_kind`, `severity`, and `knowledge_ids`, and
  is answerable only through the finding that produced it. A setup question has
  no finding, targets a configuration field rather than a statement, and must
  record whether its answer becomes the project default. Forcing it in would
  distort both lifecycles, which the product context explicitly forbids.
  *Scope must preserve:* purpose, blocking status, suggested answer, evidence
  for the suggestion, confirmed answer, project association, configuration
  field affected, answer provenance, whether it becomes the default, whether it
  may be revisited.
  *Tests:* a setup question never appears in the clarification queue and vice
  versa; answering one updates configuration and not knowledge.

- [ ] **N26** — **Typed project configuration projection.**
  *Constraint from Phase O:* every field must support unknown, inferred,
  suggested, confirmed, provisional, deferred, inherited, overridden, and
  unavailable-because-disabled. **A project must be creatable with almost none
  of it populated** — `primary_repository` is unknown for an idea, and
  `default_publication_target` stays unknown until the first publication.
  *Purpose:* publication must not search natural-language knowledge at runtime
  to decide where to write files.
  *Scope:* a validated typed record distinct from knowledge statements;
  derivation from confirmed knowledge where appropriate; explicit separation of
  descriptive knowledge, governed preference, deployment configuration, secrets,
  and per-operation override.
  *Non-goals:* storing credentials in any of these; a settings UI.
  *Acceptance:* "the project uses `crismag/KAE-Studio`" may exist as knowledge,
  and publication reads a validated target record instead.
  *Tests:* a knowledge statement naming a repository never routes a
  publication; secrets are refused at the boundary.

- [ ] **N27** — **Publication target registry and default resolution.**
  *Scope:* zero or more targets per project; at most one default per purpose or
  deliverable class; availability and authorisation state; provider-neutral
  identity with safe provider-specific configuration and **no raw credentials**;
  `target_id` optional on a request, resolving to the project default.
  *Acceptance:* a request carrying a bucket, repository coordinate, or absolute
  path is refused; an override never silently becomes the default.
  *Tests:* default resolution; override isolation; unauthorised target refused;
  disabled provider refused.
  *Registry:* product + agent read, product-only default management.

- [ ] **N28** — **Provider authorisation and connection boundary.**
  Separate from publication execution, deliberately.
  *Scope:* connection records, authorisation state, and the trust boundary that
  keeps GitHub, S3, and filesystem credentials in the runtime layer.
  *Non-goals:* publishing anything; exposing a credential to Studio or to an
  agent under any response shape.
  *Acceptance:* an unauthorised target is visible as unavailable with a reason,
  and cannot be published to.

## Phase L — Rendering, publication, and proof

Renamed from "Engine and proof gaps". The module targets that gave it that name
(N16–N19) are complete; what remains is the delivery half, decomposed so that no
single target carries provider execution, authorisation, history, and setup at
once.

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
- [x] **N20** — Durable deliverable identity — `domain/deliverables.py`,
  `application/deliverable_service.py`, migration `0014`, 2026-08-05. Scope as
  directed: KAE-Memory owns persistent immutable identity, project ownership,
  manifest and hashes, lifecycle, and provenance. **No package bytes in the
  database, and no publication or storage side effect** — those are N21.

  **Identity is content, not call.** Recording the same output twice returns
  the same deliverable, enforced by a unique index rather than a lookup,
  because a lookup before an insert races and two concurrent recordings would
  mint two ids and report a change the project did not make. The knowledge
  revision is part of that identity: the same content at a later revision is a
  different claim, because it says the project moved and the output did not.

  **Staleness is derived, never stored.** A stored flag is true until something
  remembers to update it, and the write most likely to forget is the one that
  made it false.

  `rendered` and `published` are present on every response and always false.
  Their absence would let a caller assume either happened. A test asserts no
  column named `content`, `bytes`, `payload`, or `blob` exists on the table —
  against the mapping, not the payload, because the constraint was about the
  database.

  Withdrawn is distinct from superseded: "there is a newer one" and "do not use
  this" are different facts, and collapsing them would leave a reader unable to
  tell which they were being told. **Studio's `listDeliverables` is unblocked.**
- [ ] **N21** — **Renderer and hash verification.** Provider-neutral, no
  destination. Split out of the former "rendering and publication" so that the
  contract exists before any provider defines the domain.

  *Purpose:* turn a recorded deliverable into bytes, and prove those bytes match
  the N20 manifest and per-artifact hashes.
  *Scope:* deterministic renderer; verification against `content_hash` per
  artifact and for the package; explicit failure when reproduction cannot be
  proven.
  *Non-goals:* writing anywhere, any provider, any credential, any target.
  *Depends on:* **N20.1** (below) — without version pinning, reproduction is
  unprovable for any deliverable whose knowledge has moved.
  *Acceptance:* rendering the same deliverable twice is byte-identical;
  verification fails loudly rather than publishing mismatched content; nothing
  is written to disk, object storage, or a repository.
  *Tests:* determinism; hash match; deliberate mismatch refused; a deliverable
  whose source knowledge changed refuses rather than silently re-rendering.
  *Registry:* one capability, agent + product, no provider terms.

- [x] **N20.1** — Pin every input a deliverable was rendered from —
  `domain/deliverables.py`, migration `0015`, 2026-08-05.

  **Statements are pinned as `(knowledge_id, version)`.** Knowledge versions are
  immutable and append-only, which is what makes a pin a promise rather than a
  hope: the version it names still exists, unchanged, however far the statement
  has moved. A test corrects a statement and asserts the earlier deliverable's
  pins and hash are unmoved.

  **Statements were not the only input.** `render_inputs` captures purpose,
  scope, `include_proposed`, the ordering contract, generator version, package
  schema, knowledge revision, module key, and — for module scope — a structural
  fingerprint of the graph that decided what the scope contained. A partial set
  is treated as absent: reproduction needs every input, and a subset would let
  a deliverable claim eligibility it cannot honour.

  **Artifact hashes remain the final proof.** Eligibility says the inputs exist
  to attempt reproduction; only the hash says the attempt succeeded, and the
  two are reported separately so neither is mistaken for the other.

  **Nothing was backfilled.** Legacy rows stay readable and are explicitly
  `publication_eligible: false` with a reason that says what is missing and why
  it matters. A fabricated pin would make an unprovable claim look proven, which
  is worse than an absent one. `publication_eligible` carries a `server_default`
  as well as a mapping default, so a metadata-built schema and a migrated one
  agree that an unspecified row is ineligible.

- [ ] **N29** — **Publication attempt history.** Append-oriented records
  separate from the immutable deliverable.

  *Scope:* requested target, provider, status, attempt history, verification
  result, package hash and size, external reference, error category, actor
  provenance, timestamps. States: requested, rendering, verification_failed,
  publishing, published, failed, cancelled.
  *Non-goals:* provider execution; storing expiring download URLs.
  *Acceptance:* a failed attempt never marks the deliverable invalid; retry is
  possible; the deliverable's own state is untouched by publication outcomes.
  *Tests:* failure isolation; retry idempotence; no URL persisted.

- [ ] **N30** — **Local filesystem provider.** The simplest contract proof, and
  explicitly not the permanent architecture.

  *Scope:* publication root from trusted runtime configuration; target stores a
  safe relative location beneath it; absolute and traversal paths refused;
  staged or atomic writes; defined collision behaviour; rendered files verified
  against N20 hashes before the write is accepted.
  *Non-goals:* browser download — a hosted user choosing "download" is not
  server-local publication and needs its own delivery mechanism.
  *Acceptance:* nothing is written outside the configured root under any input;
  the capability can be disabled in hosted deployments.
  *Tests:* traversal, absolute path, symlink escape, collision, disabled mode.

- [ ] **N31** — **S3-compatible provider.** Private objects, server-configured
  bucket and allowed prefix, immutable or versioned keys, encryption, runtime
  credentials. Short-lived download URLs generated on demand and **never
  persisted**. Repeated publication of one deliverable is idempotent.
  *Non-goals:* public ACLs; caller-supplied buckets or endpoints.

- [ ] **N32** — **GitHub publication provider.** Default mode creates or updates
  a dedicated branch and draft pull request. Commit to a configured branch is
  opt-in; **direct commit to the default branch needs explicit project *and*
  system authorisation**. Records repository, commit SHA, branch, path, and pull
  request. Existing user edits are never silently overwritten; conflict and
  changed-base behaviour is explicit.
  *Depends on:* **N28** — authorisation is a separate boundary from execution.

- [ ] **N22** — Remote MCP tenancy and authentication. Distinct from N5, which
  is the HTTP boundary.
- [ ] **N23** — **End-to-end acquisition-to-publication proof**, in deployment.
  Widened from "live deployment proof": the product criterion is a complete
  journey — create project, connect sources, confirm preliminary setup, acquire
  knowledge, organise modules, assemble, record, render, verify, publish
  through the remembered default, and open the result in Studio.
- [ ] **N41** — **Sparse-project generation proof.** The eight acceptance
  scenarios from the progressive-acquisition context, end to end: a
  one-sentence idea, a partial questionnaire, an existing repository with weak
  documentation, contradictory sources, no publication target, "generate now"
  with important questions open, reproducing a historical provisional
  deliverable, and a real hard block that stays narrow.

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
