# Focus Action — Remaining Engine and Proof Gaps

## Purpose

Keep genuine gaps visible without turning them into one undifferentiated backend
phase. Each row requires its own approved task or ADR.

| Gap | Current truth | Next decision or proof |
| --- | --- | --- |
| Module context | No first-class module kind, general relationship write path, traversal, or module readiness | Settle relationship vocabulary and module ownership/traversal before implementing `kae_get_module_context` |
| Package bytes | Assembly returns a deterministic manifest/description only | Delivery component must own rendering, destination credentials, publication, and lineage recording |
| Project focus | `project_key` and `project_id` resolve statelessly; no server-side active project | Build session focus only if Studio injection and key resolution prove insufficient |
| Cross-project comparison | No authorised comparison tool | Design an explicit tool; never widen an existing project-scoped read |
| Remote MCP | STDIO is local and has no remote tenancy/authentication model | Tenancy and per-operation authorisation become blocking before remote transport |
| Deployment proof | Assets and runbooks exist; no current real-instance evidence | Run the staged deployment and record health, recovery, secrets, and rollback evidence |
| Live model quality | Titan retrieval was measured; extraction quality remains incompletely characterised | Maintain a versioned evaluation corpus and measure confirmation burden/quality |
| Provider parity | PostgreSQL is practical development; CockroachDB remains supported | Run provider-specific gates when provider code changes, not as unrelated product work |

## Guardrails

- Do not report a documented design or deployment asset as operational proof.
- Do not infer module relationships from free text and persist them without an
  accepted vocabulary and provenance contract.
- Do not let project focus weaken explicit scoping or become authorisation.
- Do not place publication credentials or file-transfer logic in Studio's
  browser or KAE-Memory's assembly transaction.
- Do not re-open completed T1–T24 targets without a reproduced defect.

## Recommended order

Product integration and configuration controls precede module-graph expansion.
Deployment proof can proceed independently when infrastructure is available.
Remote MCP waits for tenancy/authentication requirements. Artifact delivery
begins only after the destination and lineage contracts are approved.

