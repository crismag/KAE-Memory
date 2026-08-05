# Focus Action — Remove UI Ownership from KAE-Memory

## Outcome

Make KAE-Memory an explicitly headless service and make KAE-Studio the owner of
all product interaction, without deleting a working dependency blindly.

## Required survey

1. Inventory `frontend/`, Node dependencies, generated client/OpenAPI coupling,
   Make targets, CI jobs, deployment scripts, runbooks, screenshots, and docs.
2. Trace whether any backend test, API contract test, local-development gate,
   deployment proof, or Demo V1 procedure requires the frontend.
3. Separate reusable product requirements from reusable implementation.
4. Record what KAE-Studio already owns before proposing any transfer.
5. Identify backend diagnostics that must remain available without a product UI.

## Execution boundary

- Preserve concepts and requirements that remain valid; do not copy the old UI
  into Studio wholesale.
- Remove frontend code, build steps, and deployment assumptions only after each
  dependency is disproved or replaced.
- Keep API and MCP surfaces product-neutral.
- Do not build the replacement UI in this repository.
- If ADR-0009 is superseded, add an ADR rather than silently rewriting history.

## Acceptance criteria

- No production Memory capability depends on presentation code.
- Useful product requirements are linked to their Studio destination.
- Obsolete frontend code, dependencies, CI/build steps, and deployment wording
  are removed in one intentionally scoped change or a documented sequence.
- Backend and MCP tests remain green.
- Local-development instructions still provide a complete headless workflow.
- Repository descriptions identify KAE-Memory as a headless knowledge service.
- KAE-Studio is the declared owner of user interaction and settings presentation.

## First implementation instruction

Deliver the dependency/value survey and proposed deletion manifest first. The
survey may recommend staged removal. Do not delete `frontend/` in the survey PR.

