# Project Focus and Default Scope

Status: **option B implemented**, 2026-08-05. A and B are done; C and the
cross-project tool are deliberately not built.
Owning target: **T25** (`../09_development/MCP_TARGET_CHECKLIST.md`).

> **Project Focus Lock** — the active project defines the default retrieval,
> recommendation, observation, and context boundary. Leaving it requires
> explicit user intent.

**What exists now.** Every project-scoped tool accepts a project **key** as well
as an id — `kae_get_project_briefing(project_key="kae-memory")`, or the key
passed as `project_id`. Resolution happens once in `dispatch`; a response
resolved from a key carries `resolved_project` with `resolved_from`. There is
**no server-side focus**: §3C is not built, so nothing below describes stored
state. A call naming no project is an `invalid_argument` listing the available
keys, never an inferred project.

Accepted as a product principle on 2026-08-03. What remains is sequencing, not
design. This document records how it is realised without redesigning the
architecture, the schema, or the MCP contract.

---

## 1. Current behaviour, verified

| Property | Today |
| --- | --- |
| Tools requiring `project_id` | **6 of 8** |
| Tools without it | `kae_list_projects` (ids and names only, no knowledge) and `kae_create_project` (a write) |
| Cross-project reads | **None.** Every service call is scoped to one project |
| Server state | **None.** `ToolContext` holds services only; no session, no active project |
| Transport | stdio — one server process per client |
| Project identifier | UUID only. `kae-memory` is not accepted anywhere |

---

## 2. The gap is narrower than it looks

**Isolation is already enforced at the data layer.** No tool can return knowledge
from a project the caller did not name. `ChunkRepository` states it directly —
*"There are no cross-project reads: a project is the durable boundary that owns
everything derived within it."* Search, briefing, readiness, findings, and
assembly are all keyed on one `project_id`, and the only unscoped read returns a
list of names.

So the risks in the brief separate into two very different things:

| Risk | Status |
| --- | --- |
| A query silently spanning projects | **Already prevented.** Not reachable through any tool |
| Knowledge from project A appearing in a project B answer | **Already prevented** by the same mechanism |
| The agent naming the **wrong** project | **Real, and unaddressed** |
| The user having to repeat the project every turn | **Real, and unaddressed** |

The security argument is largely satisfied. What is missing is **ergonomics and
disambiguation**, which is a smaller and cheaper problem than tenant isolation —
and worth saying plainly, because it changes what should be built and how urgent
it is.

This session produced a live example of the real risk. Across five consecutive
calls the project was never named; the agent inferred `KAE-Memory` from an
earlier turn and carried it forward. It labelled the project in every response,
so the inference was visible — but it offered alternatives only once, and after
that a silent-by-repetition assumption was doing the routing. Nothing leaked.
The wrong project could easily have been queried for ten turns.

---

## 3. Three options, cheapest first

### A. Studio injects the project — **zero KAE change**

Studio already knows which project is open. It supplies `project_id` on every
call. No new tool, no new parameter, no state, nothing to test on this side.

**For Studio, this is the whole solution.** It should be built first and may be
all that is ever needed there.

It does nothing for agents outside Studio — Claude Code, Cursor, a CI job — which
is where B and C apply.

### B. Accept a project **key** as well as an id — small, no new concept

```
kae_get_project_briefing(project="kae-memory")
```

`project_key` already exists, is unique, and is now derived from the name
(`KAE-Memory` → `kae-memory`). Accepting it removes the `kae_list_projects` →
pick → call hop that currently makes an agent abandon routing and answer from
its own context instead.

- No schema change. No new concept. No state.
- Existing `project_id` callers keep working.
- One resolution helper, used by every tool.

**Recommended as the first KAE-side change.** Most of the friction is the UUID.

### C. A server-side active project — real state, real risk

```
kae_set_focus(project="kae-memory")   →  subsequent calls default to it
```

Feasible: stdio gives one process per client, so process state *is* client
state. But it changes the surface from stateless to stateful, and that has a
cost the brief does not price.

**If focus is implicit, resolution must be explicit.** Every response must state
which project answered and how that was decided:

```json
"scope": {
  "project_id": "74d38a4d-…",
  "project_key": "kae-memory",
  "resolved_from": "active_focus"      // or "explicit_argument"
}
```

Without that, C institutionalises exactly the failure in §2 — an answer about a
project nobody in the conversation named, indistinguishable from one they did.
This is the same rule the response policy applies elsewhere: a response may
reduce what it says, never what it admits (`MCP_RESPONSE_POLICY.md` §2).

Further constraints if C is built:

- **Explicit always wins.** A named project overrides focus, and the response
  says `resolved_from: explicit_argument`.
- **No focus and no argument is an error**, not a guess. `invalid_argument`
  naming the available projects beats inferring one.
- **Focus is a convenience, never an authorisation boundary.** It must not be
  the thing preventing access to another project; that is §5.

---

## 4. Explicit scope expansion

Comparing projects, or searching across them, is a **different operation**, not a
wider setting on the current one. It should be an explicit tool with its own
name and its own response shape, so a cross-project answer can never be produced
by a call that looks single-project.

Not designed here. Recorded so that C's "default scope" wording is not later
read as permission to widen an existing tool.

---

## 5. Access control — compatibility only

Focus is ergonomics. Authorisation is a boundary. They must not be conflated: a
user who cannot read project B must be stopped by permission, not by their focus
being set to A.

Keeping them separate now means later authorisation work sits at the project
boundary — which every tool already respects — without unpicking a focus
mechanism that had quietly become a security control.

No implementation requested. The design must simply not make it harder.

---

## 6. Compatibility

Focus composes with everything planned, because it resolves *which project*
before any other control applies:

| Feature | Interaction |
| --- | --- |
| Response profiles (T1B) | Orthogonal — focus picks the project, detail picks how much |
| Module scope (unbuilt) | Nests inside a project; focus resolves the outer boundary |
| Purpose-bounded assembly (T21) | Already project-scoped; focus removes one argument |
| Observation classification (T24) | Routes within the focused project |
| Multi-tenant (future) | Focus must remain a convenience, never the isolation itself |

---

## 7. What not to do

- **Do not add a `project` column, table, or migration.** Nothing here needs one.
- **Do not widen an existing tool to span projects.** §4.
- **Do not make focus mandatory.** Every tool must remain callable with an
  explicit project and no prior setup — a stateless call is what makes the
  surface testable and auditable.
- **Do not let focus become authorisation.** §5.
- **Do not infer a project silently.** The failure in §2 is what that looks like.

---

## 8. Recommended sequence

1. **A** — Studio injects `project_id`. Zero KAE change. Solves the Studio case
   entirely.
2. **B** — accept `project_key` alongside `project_id`. Small, stateless,
   removes most agent friction. **The one to do first on the KAE side.**
3. **C** — only if B proves insufficient in practice, and only with the scope
   echo in §3.

B and C are separable, and B is worth doing whether or not C is ever built.

---

## 9. Remaining questions

The principle is settled. These are implementation details, not blockers.

1. **Is a project key enough on its own?** It removes the lookup hop but still
   needs naming once per call, which may be entirely acceptable. T25.2 answers
   this in practice.
2. **Where would focus live for a non-stdio transport?** HTTP/SSE has no
   one-process-per-client guarantee, so server-side focus would need real
   session identity. Only relevant if T25.3 is reached.
3. **Should `kae_list_projects` be permission-scoped later?** It is the only
   read that sees every project. Belongs with access control, not here.
