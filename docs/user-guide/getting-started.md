# Getting Started

Connecting a client, creating a project, and putting the first knowledge in it.

## 1. Run the database

KAE stores everything in CockroachDB.

```bash
make dev-db-up
```

## 2. Connect an MCP client

Point your client at the server binary and give it a database URL.

```jsonc
{
  "mcpServers": {
    "kae-memory": {
      "command": "/path/to/KAE-Memory/.venv/bin/kae-memory-mcp",
      "env": { "KAE_DATABASE_URL": "…", "KAE_ENVIRONMENT": "local" }
    }
  }
}
```

In Claude Code that lives in `~/.claude.json`. Other clients differ in file
location but not in shape.

**The server reads code at startup.** After pulling changes, reconnect the
server or restart the client — a stale process keeps serving the old behaviour
with no sign that it is doing so.

Check the connection:

```
kae_list_projects()
```

## 3. Create a project

```
kae_create_project(name="KAE-Memory")
```

Or in plain language to your client: *"create a KAE project called
KAE-Memory"*.

The key is derived from the name, so this project is `kae-memory`. Creating it
again returns the same project rather than failing.

## 4. Tell it something

```
kae_submit_observation(
  project_id="…",
  observation="Every published report must have an identifiable approver.",
  idempotency_key="obs-1",
)
```

This is now a **proposal**. It is recorded, attributed, and retrievable — and it
is not yet project knowledge.

## 5. Confirm it

Not over MCP. Confirmation is a human act and no MCP tool performs it, so today
this goes through the HTTP API:

```bash
make api
curl -X POST http://127.0.0.1:8000/knowledge/{item_id}/confirm
```

## 6. Classify it

A confirmed statement still counts for nothing until it is assigned to a
discovery area — this is what stops a project scoring well by holding a pile of
unsorted facts.

```bash
curl -X POST http://127.0.0.1:8000/projects/{project_id}/readiness/areas \
  -H 'Content-Type: application/json' \
  -d '{"knowledge_item_id": "…", "area_key": "functional_requirements"}'
```

## 7. Read the state back

```
kae_get_readiness(project_id="…")
kae_get_project_briefing(project_id="…")
```

Readiness will have moved. It moves on **confirm and classify**, not on submit.

---

## What you will run into

**Steps 5 and 6 are not on the MCP surface.** An agent can propose but cannot
confirm, and cannot classify. That gap is what `T12`–`T14` of the
[MCP target checklist](../09_development/MCP_TARGET_CHECKLIST.md) close.

**Search is lexical unless a semantic model is configured.** Word families work;
paraphrases do not. `search_mode` in every response tells you which ran.

**Document ingestion is built but not exposed.** `IngestionService` will split a
large file into per-chunk extractions with full provenance; there is no
`kae_ingest_document` tool yet (`T19`).

**A new project's briefing is large and mostly gaps.** Expected — it is
reporting ten uncovered areas. It gets smaller as the project fills in.
