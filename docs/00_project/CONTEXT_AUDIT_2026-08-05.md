# Context Audit — 2026-08-05

**Repository baseline:** `49c713e`  
**Purpose:** distinguish current context from historical documents before the
next implementation phase.

## Corrected by this realignment

| File | Stale claim | Correction |
| --- | --- | --- |
| `README.md` | M6/M9 work and several application layers were still described as current or not built | Backend foundation is complete; KAE-Studio owns product UI; focused next-phase work is linked |
| `CURRENT_PROJECT_STATE.md` | T4/T5 and T24/T25 were described as remaining | T1–T24 and T25.2 are complete; T25.3 is conditional and T25.4 undesigned |
| `CURRENT_PROJECT_STATE.md` | Immediate task both said the UI landed and remained to be built | Replaced by four independent focus actions |
| `CONTEXT_INDEX.md` | Historical three-system hackathon topology looked current | Marked as history predating ADR-0022 and the Studio boundary |

## Current sources of truth

1. `docs/00_project/CURRENT_PROJECT_STATE.md` — current repository state.
2. `docs/00_project/NEXT_PHASE_FULL_CONTEXT.md` — current phase orientation.
3. One file under `docs/00_project/focus/` — bounded action context.
4. `docs/09_development/MCP_TARGET_CHECKLIST.md` — MCP target evidence.
5. Accepted ADRs, especially ADR-0018, ADR-0020, ADR-0021, and ADR-0022.
6. Implemented code and tests when a capability claim is disputed.

## Historical or partially stale context

These files remain valuable, but must not be used alone as a current task:

- `project-model.yaml` still carries the pre-T-register milestone model and
  numerous M9-era status entries. A complete regeneration is a separate model
  migration, not a safe incidental edit to this documentation change.
- `docs/09_development/DEVELOPMENT_PLAN.md` and
  `CODEX_CLAUDE_EXECUTION_ROADMAP.md` describe the completed milestone build-out.
- `docs/06_architecture/THREE_SYSTEM_ARCHITECTURE_CONTEXT.md` is the original
  CockroachDB/AWS hackathon topology and predates selectable providers.
- `specifications/ADR/ADR-0009-discovery-workspace-frontend.md` is an accepted
  historical decision for the embedded UI. The new KAE-Studio ownership boundary
  requires a superseding ADR before frontend deletion.
- `docs/05_product/MVP_UI_WORKSPACE.md` describes interaction requirements, but
  implementation ownership now belongs to KAE-Studio.
- `CHANGELOG.md` has an early "Not added" section followed by later additions;
  it is chronological history, not a current capability inventory.

## Follow-up documentation debt

Create separate, bounded changes for:

1. superseding ADR-0009 and updating deployment/UI ownership documents after the
   frontend dependency survey;
2. regenerating `project-model.yaml` from the T-register and current product
   boundaries;
3. archiving or adding status banners to milestone-era roadmaps; and
4. updating the changelog with post-M9, MCP, provider, and classification work.

Until those changes land, the loading order above prevents older planning text
from overriding current evidence.

