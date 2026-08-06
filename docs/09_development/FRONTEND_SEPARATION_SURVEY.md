# Frontend separation survey and deletion manifest (N9)

Status: **surveyed** 2026-08-05.
Focus: [`FRONTEND_SEPARATION.md`](../00_project/focus/FRONTEND_SEPARATION.md).

The focus file requires the dependency and value survey before any deletion.
This is it, and the conclusion is that **one thing in `frontend/` is
load-bearing and it is not the frontend**.

## What is there

24 tracked files. The 160 MB on disk is untracked `node_modules`.

A Vite/React application with six panels — Blueprint, Discovery, Knowledge,
Readiness, Review, Runs — a generated API client, and a checked-in OpenAPI
document.

## Traced dependencies

| Dependency | Verdict |
| --- | --- |
| Backend tests | **None.** No Python test imports, executes, builds, or serves anything under `frontend/`. The only occurrences of the word in `src/` and `tests/` are three prose references in docstrings explaining *why* a capability exists. |
| API contract tests | **None** in the Python suite. The contract guard lives in CI (below). |
| Migrations, deployment scripts, runbooks | **None.** |
| Demo V1 procedure | **None.** The documented local workflow is API + worker + MCP. |
| Make targets | `frontend`, `frontend-install`, and the second half of `openapi`. |
| CI | One `frontend` job: install, generate client, diff, typecheck, test, build. |
| `scripts/development/dump-openapi.py` | Writes `frontend/openapi.json` by default. **Load-bearing — see below.** |

## The one load-bearing thing

CI regenerates the OpenAPI document from the application factory and diffs it
against the checked-in copy. That check has nothing to do with React: it catches
**a backend contract change that nobody carried into the recorded schema**. It
is a backend guard that happens to live in a frontend directory.

Deleting `frontend/` without replacing it would remove the only automated notice
that the HTTP surface changed shape — during the phase that adds routes to it.

**Replacement:** the document moves to `specifications/openapi.json`, and the
check becomes a Python test that regenerates it and compares. That is stronger
than the CI-only version, because it fails in the same command a developer
already runs rather than fifteen minutes later, and it needs no Node toolchain.

The `generate-client` half of the `openapi` Make target goes with the frontend.
Studio generates its own client from the published document when it wants one.

## Requirements worth keeping, and where they go

The panels are not implementation worth transferring — the focus file rules out
copying the old UI wholesale, and Studio has its own service interfaces and
component vocabulary already. What survives is the **product requirement each
panel represented**, which is already served by an adapter capability:

| Panel | Requirement | Backend capability | Destination |
| --- | --- | --- | --- |
| Readiness | show how well understood a project is, and what is missing | `readiness.read` | Studio |
| Blueprint | show the assembled project definition with labels and traces | `blueprint.read`, `context.assemble` | Studio |
| Discovery | put a question to a person and record the answer | `clarification.list`, `clarification.answer` | Studio |
| Knowledge | review candidates; confirm, reject, or correct | `knowledge.confirm`, `knowledge.reject`, `knowledge.correct` | Studio |
| Review | show findings, blockers, contradictions | `review.findings`, `blocker.record` | Studio |
| Runs | show what an agent run did and what it produced | `run.start`, `run.observe` | Studio |

Every one is reachable over HTTP today (N3, N6). Nothing is being deleted that a
replacement would have to rebuild the backend for.

## What KAE-Studio already owns

Surveyed at `e530753`. Studio has its own `src/services/interfaces.ts`
(`ProjectMemoryClient`, `InterviewProvider`, `ProjectProjectionService`,
`ArtifactService`, `ArtifactPublisher`), a mock service layer, and its own
component and status vocabulary. It does **not** yet call the KAE-Memory API —
its services are mocks behind interfaces.

That matters for this survey in one way: the checked-in `openapi.json` has no
consumer today. It is a record, not an integration, which is why relocating it
costs nothing and losing it would cost the guard.

## Backend diagnostics that must survive a UI-less repository

- `GET /health` — liveness and configuration, no database call.
- `kae_get_readiness`, `kae_get_project_briefing` — what a project knows,
  without a browser.
- `Settings.explain_all()` (N7) — every effective setting and its source.
- `provider.describe()` — which embedder and classifier are configured, and
  whether either reads meaning.

None of these was ever served by the frontend. The repository is already
operable headless; the frontend was a demonstration, not an operator surface.

## Deletion manifest

Ordered, and each step is separately revertible.

1. **Move the contract guard out first** — relocate `openapi.json` to
   `specifications/`, point `dump-openapi.py` at it, add the Python test. *This
   must land before deletion, not with it.*
2. **Supersede ADR-0009** (N10). It is an accepted decision for an embedded UI;
   a commit that contradicts an accepted ADR leaves the record saying two
   things.
3. **Delete** `frontend/`, the two Make targets, the `generate-client` half of
   `openapi`, and the CI `frontend` job (N11).
4. **Correct the descriptions** that call KAE-Memory anything other than a
   headless knowledge service.

## What this survey does not claim

It does not claim the panels were bad, or that Studio will want the same six.
It claims only that no backend capability depends on presentation code, and that
one CI guard needs a new home before the directory goes.
