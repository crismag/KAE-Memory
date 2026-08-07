# ADR-0009 — Discovery workspace frontend technology

- **Status:** superseded by [ADR-0026](ADR-0026-kae-memory-is-headless.md), 2026-08-05
- **Date:** 2026-07-27
- **Closes:** OQ-011
- **Blocks:** M9 — Workspace and Reporting
- **Scope:** decision only. Implementation is M9 and does not begin here.

## Decision

The discovery workspace is a **client-side React application in TypeScript**,
built with **Vite**, navigated with **React Router** in declarative or data mode,
with **TanStack Query** owning server state.

| Concern | Decision |
| --- | --- |
| Language | TypeScript |
| UI library | React |
| Build tool | Vite |
| Routing | React Router — declarative or data mode, **not** framework mode |
| Server state | TanStack Query |
| Local UI state | React state and context |
| API protocol | Versioned REST/JSON |
| Run updates | Server-Sent Events, with polling fallback |
| Styling | CSS variables over a reusable component layer |
| Testing | Vitest, React Testing Library, Playwright |
| Output | Static assets, client-side rendered |
| Mobile | Responsive web, desktop-optimised. No native app |

No JavaScript server-side runtime is introduced. Server-side rendering, React
Server Components, and JavaScript-owned backend routes are outside first-release
scope.

Redux or another global client-state framework is not adopted unless a
demonstrated requirement cannot be met cleanly through server state, route state,
or local component state. Most state here belongs to the server.

## Application boundary

The React application is a **presentation client**. The Python API stays
authoritative for authentication and authorisation, project and session
operations, knowledge lifecycle, readiness calculation, blueprint generation,
durable run creation and observation, retrieval, and provider and secret
handling.

The frontend must not implement authoritative business rules that can change
persisted project state without API validation.

```text
React frontend      presentation and interaction
      |
Python API          authentication, authorisation, use cases
      |
Worker              durable AI and retrieval workflows
      |
CockroachDB         authoritative operational and semantic state
```

**The browser does not own the run.** A long-running operation returns a durable
run identifier rather than holding the HTTP request open, and closing or
refreshing the browser must not cancel an AgentRun. Cancellation is an explicit
API call. SSE improves the demonstration; correctness must never depend on an
uninterrupted browser connection, so current run state is always recoverable
through an ordinary request.

## The workspace makes three kinds of state distinct

- **Conversation state** — what the user and agent said.
- **Knowledge state** — what KAE extracted and preserved.
- **Execution state** — what the durable worker is doing.

This separation is the product demonstration. A chat-only interface would hide
most of what KAE-Memory does: the memory, the provenance, and the recovery are
all invisible in a transcript.

Initial workspace: project selection and overview, guided discovery
conversations, structured knowledge inspection, accept/edit/reject of extracted
knowledge, readiness presentation, blueprint generation and review, durable run
status and recovery visibility, and source and provenance inspection.

## Four corrections against the repository as it stands

### 1. `frontend/` alongside `src/`, not a move to `backend/`

The proposal placed the package at `backend/src/kae_memory/`. It currently lives
at `src/kae_memory/`, and four things are pinned to that:
`pyproject.toml` packages, ruff `src`, mypy `files`, and `alembic.ini`'s
`prepend_sys_path`.

Relocating is possible but it is **its own bounded task with its own pull
request**, not something to carry inside a frontend decision. The separation the
proposal wants is achieved either way; only the churn differs.

```text
KAE-Memory/
├── src/kae_memory/     unchanged
├── frontend/
│   ├── src/{app,routes,features,components,api,types}/
│   └── tests/
└── tests/              unchanged
```

Feature-oriented modules under `features/` — projects, discovery, knowledge,
readiness, blueprints, runs — rather than one global `components/` directory.

### 2. Run status is the domain enum, and the client is generated early

The proposal's `AgentRun` interface used
`"queued" | "running" | "retry_wait" | "completed" | "failed" | "cancelled"`.
The domain defines `pending`, `running`, `interrupted`, `succeeded`, `failed`,
`cancelled`, `abandoned`, and **ADR-0007 already settled the mapping**: `queued`
is `pending`; `retry_wait` is `failed` with a future `next_attempt_at`;
`completed` is `succeeded`. Two field names also have no counterpart —
`attemptCount` is `attempt_number`, and `currentStep`/`checkpointVersion` are
`continuation_state`.

This vocabulary has now drifted three times: relationship types in M5, knowledge
kinds in M6, run status here. **The frontend is where a divergent copy would
become permanent**, because hand-written TypeScript interfaces are never
reconciled once written.

Therefore the generated-client flow is **not deferred**:

```text
Python API schemas -> OpenAPI document -> generated TypeScript types -> query hooks
```

Generation is set up as soon as the first endpoints exist, not "after they
stabilise". Hand-written duplicates of API models are permitted only as a
temporary scaffold within a single pull request, never merged as the steady
state.

### 3. The API contract is designed before the UI, inside M9

`src/kae_memory/` contains `domain`, `persistence`, `application`, and `agents` —
there is **no interface layer**. `POST /projects/{id}/runs` and
`GET /runs/{id}/events` presuppose a REST and SSE surface that does not exist.

M9 therefore sequences as: **API contract → generated client → UI**. Without that
ordering the first frontend task would invent endpoint shapes by implication, and
the OpenAPI document would end up describing whatever the UI happened to need
rather than what the application layer actually offers.

### 4. Frontend checks gate `main`

CI runs `uv sync`, ruff, mypy, and pytest. Nothing installs Node, and
`make check` is Python-only.

When frontend code lands, **CI gains a Node job and `make check` covers both**.
A frontend that can break while CI stays green is the exact failure mode RA-01
existed to fix, and it would be worse here because UI regressions are invisible
until someone opens the page.

## Rejected alternatives

**Next.js and other React server frameworks.** A second server-side application
runtime alongside the Python API, creating permanent ambiguity about whether
business logic belongs in Python or JavaScript. KAE-Memory needs none of what
justifies it: no SEO, no public content pages, no server components, no
frontend-owned API routes, no frontend-managed sessions, no edge rendering.

**Streamlit and Gradio.** They optimise for rapid model demonstrations, not a
structured stateful workspace. KAE-Memory needs editable discovery areas,
persistent navigation, project and session switching, evidence inspection,
readiness presentation, asynchronous run progress, blueprint review, and recovery
visibility. Streamlit would make the *first* demo faster and then have to be
replaced — a disposable UI rather than a product foundation.

**Native mobile.** Out of first-release scope.

## Security

The browser must never contain CockroachDB credentials, AWS credentials,
server-owned model credentials, or persistent plaintext BYOK secrets. Every
privileged operation and all provider access happen through the Python API and
worker boundary. BYOK keys, if introduced, go through an API-controlled workflow
— never browser local storage.

Authentication is abstracted behind a session interface so the identity provider
can be chosen later. **OQ-011 does not select one**; the demonstration may use a
controlled demo identity.

## Deployment

Vite produces static assets, so hosting can be S3 and CloudFront, a lightweight
web container, or the application's own static path. **OQ-011 does not decide
this** — OQ-016 does.

## Consequences

**Positive.** A product-grade interface foundation rather than a disposable demo
UI. The Python API stays the single backend boundary. Static deployment is
independent of the worker runtime. TypeScript plus a generated client keeps the
frontend aligned with the API contract instead of drifting from it. Run
visibility survives refresh and disconnection.

**Negative.** The project takes on selecting and maintaining individual UI
components without a full-stack framework's defaults. A second toolchain, second
test stack, and second CI job arrive. `make check` gets slower.

**Accepted risk.** The API contract does not exist yet, so the frontend is being
chosen before the thing it consumes is designed. Correction 3 sequences M9 to
close that gap rather than leaving it implicit.

## Related

- [`ADR-0007-worker-runtime-and-leases.md`](ADR-0007-worker-runtime-and-leases.md) — the run status vocabulary the client must not diverge from
- [`../API_CONTRACTS.md`](../API_CONTRACTS.md)
- `MVP_UI_WORKSPACE.md`
- `PRODUCT_EXPERIENCE_NORTH_STAR.md`
