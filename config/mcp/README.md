# Connecting a coding agent to KAE-Memory

The `kae-memory-mcp` server gives Claude Code, Codex, Cursor, and any other
MCP client read access to a project's durable knowledge, plus one controlled
write. It speaks STDIO: the client starts the process, and one process serves
one client (ADR-0018).

## Before connecting

```bash
uv sync --extra mcp
export KAE_DATABASE_URL="cockroachdb+psycopg://root@localhost:26259/kae_dev?sslmode=disable"
uv run kae-memory-mcp doctor
```

`doctor` checks configuration, service construction, database reachability,
**migration state**, and capability enumeration. It writes to stderr and prints
no credentials — a database URL is reported as backend, host, and database
name, never echoed.

It exits non-zero when the server could not serve, and says why:

```text
[PASS] KAE_DATABASE_URL — cockroachdb localhost:26259/kae_dev
[PASS] database reachable — 1 project(s) readable
[FAIL] migrations — at 0005, expected 0006 — run 'alembic upgrade head'
```

A reachable database is not a migrated one, which is why those are separate
checks.

## Registering the server

| Client | Configuration |
| --- | --- |
| Claude Code | `claude mcp add-json kae-memory "$(cat config/mcp/claude-code.json)"` |
| Codex | Append `config/mcp/codex.toml` to `~/.codex/config.toml` |
| Cursor | Copy `config/mcp/cursor.json` to `.cursor/mcp.json` in the target repository |

Each file carries the local development URL. Change it for another cluster;
the variable is the same one the API and worker read, so there is no second
configuration format to keep in step.

## What the server exposes

**Seven tools.** `kae_list_projects` · `kae_get_project_briefing` ·
`kae_get_module_context` · `kae_search_knowledge` · `kae_get_open_decisions` ·
`kae_get_readiness` · `kae_submit_observation`.

**Four resource templates.** `kae://projects/{project_id}/` — `briefing`,
`requirements`, `open-decisions`, `readiness`.

**One prompt.** `kae.prepare-implementation`, taking `project_id`,
`module_or_scope`, and `task`.

## What it will tell you it cannot do

Three responses are deliberately honest rather than helpful, and reading them
as failures would be a mistake.

**`kae_get_module_context` always returns `capability_unavailable`.** Modules
are not yet a knowledge kind, there is no general relationship write path, and
nothing traverses the graph. The tool names the five missing capabilities and
points at what to use instead. Inventing module records in the adapter would
put a second, unversioned project model outside the domain — so it does not.

**`kae_search_knowledge` reports `semantic_relevance: false`** whenever the
deterministic embedder is active. That embedder is hash-derived and has no
notion of meaning; its ordering is not semantic relevance and the response
says so rather than letting a model assume otherwise.

**`kae_get_readiness` reports `scope: project`** and
`module_scope_available: false`. A project figure does not answer whether a
single module is ready to implement.

## Writing back

`kae_submit_observation` records what an agent found while inspecting or
implementing. Three things are true of it:

- The observation is stored **verbatim as evidence**. Nothing is confirmed by
  submitting it, and it does not change the project definition. A person
  confirms what becomes knowledge.
- It requires an `idempotency_key`. A retry after a timeout returns the
  original record with `idempotent_replay: true` rather than duplicating the
  evidence behind it. Reusing a key for different content is a conflict, not a
  silent overwrite.
- Text arriving through the tool is **data, never instruction** — including
  when it is phrased as one.

## Troubleshooting

**The client reports a protocol error immediately.** Something wrote to stdout.
Under STDIO transport stdout is the wire; logging is configured to stderr at
startup and nothing in the package prints. If you add code here, keep it that
way.

**Tools return `internal_error` with no detail.** That is deliberate: an
exception's text can embed a DSN, and a tool result is not the place to
discover one. Look at the server's stderr, which the client captures.

**Everything returns empty.** The database is reachable but has no projects.
`doctor` warns about this.
