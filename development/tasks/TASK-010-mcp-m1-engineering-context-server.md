# TASK-010 — MCP-M1 Local KAE Engineering Context Server

**Status:** proposed, 2026-08-01
**Milestone:** MCP-M1

## Objective

Prove the central KAE architectural claim before expanding any user interface:

> Can Claude, Cursor, or Codex retrieve useful, scoped engineering context from KAE-Memory and contribute new knowledge, without directly accessing its database?

If this works, KAE-Studio becomes another client of a proven platform rather than the only place KAE can demonstrate value.

## Relationship to ADR-0004

This milestone does **not** contradict [`ADR-0004 — CockroachDB MCP is inspection-only`](../../specifications/ADR/ADR-0004-mcp-inspection-only.md). It is a different server serving the opposite purpose, and it should be read as completing that decision.

ADR-0004 accepted a known weakness:

> Enforcement is by policy and review, not by a technical control. […] nothing in the tooling prevents an agent from being handed a connection string.

MCP-M1 removes the incentive that made that risk real. An agent that can call `kae_get_module_context` and `kae_submit_observation` has no reason to want SQL access. **The CockroachDB MCP server remains inspection-only; the KAE MCP server is the sanctioned agent data path, and every operation on it goes through application services that enforce the domain invariants.**

Naming caution: KAE-Studio's `docs/decisions/ADR-0004-mcp-access-layer.md` is a different document in a different repository. The two are consistent; the shared number is coincidental.

## Scope

A locally installed MCP server over the existing KAE-Memory application layer. The coding agent already owns filesystem, terminal, Git, and editing capability. This server supplies project intelligence and controlled Memory operations — nothing else.

### Transport: local STDIO first

```text
Coding agent -> starts local `kae-memory-mcp` process -> STDIO -> KAE-Memory application services
```

Chosen because it defers remote deployment, HTTPS, OAuth, public endpoints, gateway configuration, multi-user authorization, and network debugging. Remote Streamable HTTP follows once the local workflow proves useful.

### Location

Inside this repository, as an adapter beside the REST API. **Do not create a third repository.**

```text
src/kae_memory/mcp/
├── server.py
├── resources.py
├── tools.py
├── prompts.py
├── schemas.py
└── errors.py
tests/mcp/
```

Executable: `kae-memory-mcp` (a `[project.scripts]` entry — none exist today).

Dependency direction is mandatory:

```text
MCP adapter -> application services -> domain and persistence ports
```

Never `MCP tool -> raw CockroachDB query`. MCP, REST, workers, and the discovery frontend must share one set of business behaviors.

Configuration reuses the existing mechanism (`KAE_DATABASE_URL`, `KAE_ENVIRONMENT`, and the same resolution used by `api/dependencies.py` and `worker/__main__.py`). Do not introduce a second configuration format.

## Tool set

Six read tools and exactly one write tool.

| Tool | Purpose | Backed by today's code? |
| --- | --- | --- |
| `kae_list_projects` | Identify available projects | **Yes** — `MemoryService.list_projects` |
| `kae_get_project_briefing` | Current concise project understanding, with Memory revision | **Yes** — `BlueprintService.generate` + `readiness_service.knowledge_revision` |
| `kae_get_module_context` | Implementation context for one module | **No** — modules do not exist in `KnowledgeKind`; see below |
| `kae_search_knowledge` | Scoped semantic search | **Yes** — `RetrievalService.search`; caveat below |
| `kae_get_open_decisions` | Unresolved questions affecting the agent's work | **Yes** — `KnowledgeKind.UNKNOWN` + `FindingKind.OPEN_QUESTION` |
| `kae_get_readiness` | Whether a scope is ready for an activity | **Partly** — project-wide only |
| `kae_submit_observation` | Agent-discovered evidence or proposed change | **Partly** — needs idempotent ingestion |

### Honesty requirements — non-negotiable

**`kae_get_module_context` must return a documented capability gap, not invent module records inside MCP.** Modules are not in `KnowledgeKind` (`domain/models.py:91`), there is no general relationship write path, and traversal does not exist. The tool ships returning a structured `capability_unavailable` response naming what is missing. Fabricating modules in the adapter would put a second, unversioned project model outside the domain — precisely the failure the whole architecture exists to prevent.

**`kae_get_readiness` must report its own limitation.** `ReadinessSnapshot` is keyed by `project_id`; module and integration scopes do not exist. The response states the scope it actually computed.

**`kae_submit_observation` must create evidence or a proposed knowledge change through existing behavior.** It must never confirm or overwrite a requirement. Agent submissions are `proposed` knowledge with provenance identifying the agent, the repository, the commit, and the Memory revision it was working from.

```json
{
  "project_id": "…",
  "source": {
    "type": "repository_observation",
    "repository": "crismag/KAE-Studio",
    "commit": "abc123",
    "paths": ["src/features/approval/api.ts"]
  },
  "observation": "The existing API accepts only one approver, but the current requirement allows multiple approval levels.",
  "classification_hint": "potential_conflict"
}
```

**Observation text is untrusted input.** It is recorded as evidence, never followed as instruction, even when it is phrased as one.

### Semantic search caveat

`RetrievalService.search` runs against real CockroachDB vectors, but the default `DeterministicEmbeddingAdapter` is hash-derived and has no notion of meaning. TASK-009 already established this honestly: measured recall@8 against the fixture is 50%, which is chance.

So the acceptance criterion "semantic search exercises the real retrieval path" is satisfiable locally, while **relevance quality is not demonstrated** unless the run uses the Titan adapter. The demonstration must say which embedder was used. Do not let a hash-derived ranking be presented as semantic recall.

## Resources

```text
kae://projects/{project_id}/briefing
kae://projects/{project_id}/requirements
kae://projects/{project_id}/open-decisions
kae://projects/{project_id}/readiness
```

Resources are readable context a client attaches to a conversation. Do not expose database rows as resources.

## Prompt

One guided workflow: `kae.prepare-implementation`, taking `project_id`, `module_or_scope`, `task`.

It instructs the agent to retrieve the briefing, retrieve the requested scope, check open decisions and readiness, inspect the local repository with its own tools, identify mismatches between Memory and code, produce a plan, **not invent missing requirements**, submit significant discoveries through `kae_submit_observation`, and record the Memory revision used.

This makes KAE legible to an agent instead of relying on it to guess a tool sequence.

## Demonstration

Use a real KAE project, not a synthetic example. The obvious candidate is KAE's own definition — see KAE-Studio's `ADR-0005`, which makes self-memory the intended first project.

**Demo A — Project understanding.** *"Use KAE to explain the current project, its objectives, unresolved decisions, and implementation readiness. Do not inspect the repository yet."* Proves tool discovery, real CockroachDB-backed context, and that the agent names the Memory revision and open questions.

**Demo B — Scoped preparation.** *"Prepare an implementation plan for the approval workflow module. Identify dependencies, acceptance criteria, and anything blocking development."* Proves scoping, no unrelated history loaded, no invented approver role, and a clear line between confirmed requirements and open decisions. **Given the module gap, this demo will surface `capability_unavailable` — that is a successful demonstration of honesty, and it should be shown, not hidden.**

**Demo C — Repository comparison.** *"Compare the KAE requirements with the current repository. Report missing implementation or contradictions."* Proves KAE supplies context while the agent supplies local tooling, ending in a submitted observation.

**Demo D — Continuity.** Restart the agent, or open a different MCP client, and ask what the previous analysis discovered. **This is the real demonstration of persistent agentic memory:** the answer comes from KAE-Memory, not from the prior conversation, and retains its source and proposed status.

## Installation

```bash
pip install -e .
kae-memory-mcp doctor
```

`doctor` verifies configuration presence, KAE-Memory initialization, CockroachDB reachability, migration state, readability of the configured project, that secrets are not printed, and that MCP can enumerate its capabilities.

Each client then starts the same executable with `KAE_DATABASE_URL` and `KAE_ENVIRONMENT` supplied securely.

## Acceptance criteria

1. The MCP server starts locally over STDIO.
2. Claude Code discovers and calls it.
3. Codex or Cursor connects independently to the same server.
4. At least five read operations return real KAE-Memory data.
5. Semantic search exercises the real CockroachDB retrieval path, **with the embedder in use stated**.
6. An implementation-context request returns a bounded response — or a structured capability gap.
7. An agent submits an observation without it being auto-confirmed.
8. Restarting the client does not lose the observation.
9. The same observation is visible from another supported client.
10. Every tool calls application services, never database tables.
11. Errors are structured and expose no credentials.
12. Tests cover schemas, application delegation, authorization scope, and failure behavior.
13. The demonstration distinguishes implemented capability from proposed future tools.

## Out of scope

Remote MCP deployment · OAuth · marketplace publishing · VS Code extension · client-specific plugins · GitHub writes · filesystem tools · Studio integration · autonomous implementation · granular mutation tools · UI inside MCP · organization and billing.

## Prerequisites and sequencing

From KAE-Studio's `docs/planning/CAPABILITY_MATRIX.md`:

- **Blocking for AC-7/8/9:** idempotent evidence ingestion. Ingestion is keyed by session and sequence number today; run enqueueing is idempotent but message recording is not. A retried observation would duplicate evidence.
- **Not blocking:** modules, traversal, scoped readiness. These are what `kae_get_module_context` reports as unavailable, and that report is itself part of the demonstration.
- **Deferred:** authentication and tenancy. Local STDIO with locally supplied configuration is why this milestone can proceed before they are settled. **They become blocking the moment a remote transport is introduced**, and that constraint should be recorded in the follow-on ADR rather than rediscovered.

## Decisions to record before implementation

- An ADR in this repository for the KAE MCP server: surface, dependency direction, proposal-only write semantics, and the boundary against `ADR-0004`.
- Whether `kae-memory-mcp` runs in-process with the application or as a separate process against the API.
- How the agent identity appears in provenance — a distinct `Agent` role, or an actor type on evidence.

## Value if this succeeds

```text
Agent -> KAE MCP -> real KAE-Memory context -> useful engineering decision
      -> observation returned to Memory -> continuity across clients
```

The central KAE value is demonstrated before committing heavily to the Studio interface, and Studio can then be built on the same application services with confidence that the platform claim holds.
