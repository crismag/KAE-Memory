# MCP Tools

The eight tools KAE exposes to an MCP client. In Claude, Cursor, or any other
MCP client you normally ask in plain language — *"create a project called
KAE-Memory"* — and the client picks the tool. The signatures below are what it
picks from, and are worth knowing when a result is not what you expected.

Six tools read. Two write, and **neither confirms anything**.

| Tool | Reads / writes | One line |
| --- | --- | --- |
| [`kae_create_project`](#kae_create_project) | writes | Create a project |
| [`kae_list_projects`](#kae_list_projects) | reads | What projects exist |
| [`kae_get_project_briefing`](#kae_get_project_briefing) | reads | Everything about one project |
| [`kae_get_readiness`](#kae_get_readiness) | reads | How complete it is, area by area |
| [`kae_get_open_decisions`](#kae_get_open_decisions) | reads | What nobody has decided yet |
| [`kae_search_knowledge`](#kae_search_knowledge) | reads | Find statements |
| [`kae_get_module_context`](#kae_get_module_context) | reads | Not available yet — reports the gap |
| [`kae_submit_observation`](#kae_submit_observation) | writes | Propose something the project should know |

---

## kae_create_project

```
kae_create_project(name)
```

The only required argument is the name.

```
kae_create_project(name="KAE-Memory")
```

Optional `key` and `description`:

```
kae_create_project(
  name="KAE-Memory",
  key="kae-memory",
  description="Persistent AI memory platform for software engineering",
)
```

**The key is derived from the name** when you omit it — `KAE-Memory` becomes
`kae-memory`. You will see this key in listings and URLs, so leaving it to be
derived is usually better than inventing one.

**Creating twice is not an error.** A second call with the same name returns the
project that already exists, with `created: false`. Safe to retry if a response
is lost.

```json
{
  "project_id": "74d38a4d-...", "name": "KAE-Memory", "key": "kae-memory",
  "status": "active", "created": true, "knowledge_statements": 0,
  "next_steps": ["Record what the project knows: kae_submit_observation.", "..."]
}
```

A new project is **empty**. `knowledge_statements: 0` says so, because
`created: true` on its own would be easy to read as "ready to use".

Naming two projects the same is allowed — the second gets `kae-memory-2`. An
*explicit* key that is already taken is an error instead, because you asked for
that key specifically.

---

## kae_list_projects

```
kae_list_projects()
```

Every project, newest first, with id, name, key, and status. Start here when you
do not have a project id.

---

## kae_get_project_briefing

```
kae_get_project_briefing(project_id)
```

The fullest single answer KAE gives: readiness and how it was calculated, the
confirmed statements grouped by area, every finding with its severity and
recommended action, knowledge health counts, and open questions.

Worth knowing: **this is a large response** (around 3,000 tokens on a small
project). If you only need the state, [`kae_get_readiness`](#kae_get_readiness)
is a fifth of the size. Response profiles that let you ask for less are designed
but not yet built.

Read these fields first:

- `readiness.percentage` and `readiness.status_label` — where the project is
- `findings_by_severity.critical` — what is actually blocking
- `recommended_next_steps` — what to do, most severe first
- `knowledge_health` — confirmed vs proposed vs unanswered, in one object

---

## kae_get_readiness

```
kae_get_readiness(project_id)
```

The percentage, the status, and a per-area breakdown with confirmed and proposed
counts.

`scope: "project"` and `module_scope_available: false` are there on purpose:
**this figure does not tell you whether any single module is ready to
implement**, and reading it that way is the mistake the fields exist to prevent.

---

## kae_get_open_decisions

```
kae_get_open_decisions(project_id)
```

Questions the project recorded about itself, plus unresolved contradictions and
blockers.

These are **yours to answer**. An agent reading this should report a blocker and
stop, not pick an answer on the project's behalf. The `guidance` field says so.

---

## kae_search_knowledge

```
kae_search_knowledge(project_id, query)
kae_search_knowledge(project_id, query, limit=20, kinds=["rule"], diagnostics=True)
```

| Argument | Default | Notes |
| --- | --- | --- |
| `query` | — | Required |
| `limit` | 8 | 1–50 |
| `kinds` | all | `goal`, `actor`, `requirement`, `rule`, `constraint`, `decision`, `assumption`, `unknown` |
| `mode` | `auto` | `lexical`, `semantic`, or `auto` |
| `diagnostics` | `false` | Adds vector distances and coverage scores |

**Check `search_mode` in the response.** Without a semantic model configured,
`auto` falls back to `lexical`, which matches word families — a query for
`approval` finds *approve*, *approved*, *approver*. It will **not** find
statements that mean the same thing in different words. A conceptual query
returns zero results and a warning saying why. That is the honest answer, not a
failure.

Results carry `relevance` (`strong` / `partial`) and `matched_terms` rather than
raw distances. Set `diagnostics=True` if you want the underlying numbers.

---

## kae_get_module_context

```
kae_get_module_context(project_id, module)
```

**This capability does not exist yet**, and the tool says so rather than
inventing an answer. You get a structured gap: which module you asked for, that
it is `not_registered`, what is missing from this version, and the project-level
statements whose wording matches the name.

Those statements come with a caveat that matters: a **term match is not module
membership**. Nothing records which knowledge belongs to which module yet.

---

## kae_submit_observation

```
kae_submit_observation(project_id, observation, idempotency_key)
```

Records something the project should know. Optional `source` and
`classification_hint`.

`idempotency_key` is required so a retry cannot duplicate evidence — any stable
string of your choosing.

**What you submit stays proposed.** It is candidate evidence, not confirmed
project knowledge, and it does not change the project definition or move
readiness until a person accepts it. Confirming is not available over MCP at
all; use the HTTP API.

---

## Things that will surprise you

**An empty project produces a *bigger* briefing than a full one.** The response
grows with what is *missing* — every uncovered area adds a finding and a
recommended step. A brand-new project has ten of them.

**Readiness moves when you classify, not when you confirm.** A statement has to
be both confirmed *and* assigned to a discovery area before it counts.

**Nothing here can confirm knowledge.** Confirmation, rejection, correction,
document ingestion, and context assembly all exist in KAE but are not on the MCP
surface yet. They are reachable through the HTTP API. See
[`../09_development/MCP_TARGET_CHECKLIST.md`](../09_development/MCP_TARGET_CHECKLIST.md)
for what is planned.
