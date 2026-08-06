# ADR-0026 — KAE-Memory is a headless knowledge service

- **Status:** accepted
- **Date:** 2026-08-05
- **Supersedes:** [ADR-0009](ADR-0009-discovery-workspace-frontend.md) — *Discovery workspace frontend technology*
- **Relates to:** [ADR-0023](ADR-0023-http-and-mcp-as-peer-adapters.md), [ADR-0024](ADR-0024-http-trust-boundary.md)
- **Closes:** N10

## Decision

KAE-Memory owns no presentation. It serves two adapters — HTTP and MCP — and
ships no UI, no build step for one, and no assumption that one exists.

**KAE-Studio is the owner of product interaction**, including settings
presentation, conversation surfaces, and anything a person looks at.

The embedded `frontend/` directory is removed (N11).

## Why supersede rather than delete quietly

ADR-0009 is an accepted decision. Deleting the code it decided about, without
replacing the decision, would leave the record saying two things: an ADR
specifying an embedded React workspace, and a repository with none. Whoever read
the ADR first would conclude the frontend had been lost rather than moved.

The focus file says this in one line — *if ADR-0009 is superseded, add an ADR
rather than silently rewriting history* — and it is the right rule. An ADR is a
record of what was decided when, not a description of the present.

## What ADR-0009 got right, and where it now applies

Most of it was not about React.

**The application boundary.** "The Python API stays authoritative for
authentication and authorisation, project and session operations, knowledge
lifecycle, readiness calculation, blueprint generation, durable run creation and
observation, retrieval, and provider and secret handling." That is still exactly
right, and it is now a boundary between *repositories* rather than between
layers of one. ADR-0024 hardened it: a trust boundary, not a convention.

**The browser does not own the run.** A long-running operation returns a durable
run identifier; closing a browser must not cancel an `AgentRun`; current state is
always recoverable through an ordinary request. Unchanged, and load-bearing for
any client Studio builds.

**Three kinds of state stay distinct** — conversation, knowledge, execution.
This was ADR-0009's sharpest observation: *a chat-only interface would hide most
of what KAE-Memory does, because the memory, the provenance, and the recovery
are all invisible in a transcript.* It survives as a requirement on Studio, and
the adapters make all three separately readable so a client can honour it.

**The vocabulary warning.** ADR-0009 observed that domain vocabulary had already
drifted three times and that "the frontend is where a divergent copy would
become permanent, because hand-written TypeScript interfaces are never
reconciled once written." That risk did not go away when the frontend did — it
moved across a repository boundary, where it is harder to see. The recorded
OpenAPI document and the contract test that guards it (N9) exist for precisely
this, and Studio generating its client from that document rather than hand-
writing interfaces is the mitigation ADR-0009 asked for.

## What changes

| ADR-0009 said | Now |
| --- | --- |
| The workspace is a React/Vite application in this repository | Studio owns it, in its own repository |
| `frontend/` alongside `src/` | Removed (N11) |
| The client is generated early from the OpenAPI document | The document is still recorded and guarded; whoever generates a client does so from it |
| CI builds, typechecks and tests the frontend | Removed with the directory |
| Initial workspace: project selection, guided discovery, knowledge inspection, accept/edit/reject, readiness, blueprint, run status, provenance | Product requirements, each already reachable over HTTP (N3, N6), destinations recorded in the survey |

The technology choices — React, Vite, React Router, TanStack Query, Vitest — are
no longer this repository's to make. Studio may keep or change them; nothing
here depends on the answer.

## Consequences

**KAE-Memory has no demonstration surface.** This is a real loss and worth
stating plainly: the six panels showed what the system does in a way no API
response does. What replaces it is Studio, which does not exist yet as an
integration. Between now and then, the system is demonstrated through its
adapters — which is honest about what the repository actually contains.

**The contract guard becomes more important, not less.** While the frontend was
here, a breaking API change broke a build in the same repository. Now it breaks
somebody else's, later. `tests/api/test_recorded_contract.py` is the replacement
and it is deliberately stricter: whole-document comparison, in the ordinary test
command.

**No production capability was ever at risk.** The survey (N9) traced every
dependency: no backend test, migration, deployment script, or documented
workflow required the frontend. The repository was already operable headless.

## What this does not decide

Whether Studio should have the same six panels. Whether Studio uses a generated
client or a hand-written one — recommended, not mandated. When Studio integrates
against a live API rather than its mocks; that is Phase K, which this register
does not implement.
