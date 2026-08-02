# KAE Package Delivery and AI-Tool Compatibility

Status: **proposed design**, 2026-08-01. Companion to `KAE_PACKAGE_MODEL.md`. No implementation is authorized.

Covers: publication workflows for GitHub, local folder, and S3 · AI-tool compatibility requirements.

## 1. Generation and publication are separate

One bundle is generated from a pinned `knowledge_revision`; a publisher writes it somewhere. **The destination never changes the artifact.** This is already recorded in KAE-Studio's ADR-0003 and is restated here because lineage depends on it: the same `content_hash` must be verifiable at every destination.

```text
KAE-Memory knowledge @ revision N
    -> context assembly (Memory)
    -> render (delivery)
    -> package bundle + manifest
    -> publisher: GitHub | local folder | S3
    -> publication recorded in Memory
```

## 2. Publication workflows

All three share one precondition and one prohibition.

**Precondition — classify before writing.** Every target path is classified as *generated artifact* (in this package's manifest), *previously generated* (in an earlier manifest), *human override*, or *unknown*. A path that is not a generated artifact is never written.

**Prohibition — no silent overwrite, ever.** If a previously generated file's on-disk hash differs from the hash recorded at its last publication, it was edited by hand. That is a **conflict**, not a stale file.

### 2a. GitHub

```text
generate -> compute proposed changes against the base branch
         -> present the diff for review
         -> create a branch
         -> commit
         -> open a draft pull request (default)
         -> record publication in Memory
```

- Never write to the default branch without explicit per-project opt-in.
- Draft PR by default, so review is structural rather than procedural.
- Credentials live server-side or in the installed agent — **never in the browser**.
- Base-branch movement between preview and publish invalidates the preview; recompute rather than force.

### 2b. Local folder — requires the installed agent

The browser cannot write to a filesystem. A local agent, CLI, IDE extension, or MCP tool performs the operation.

```text
Studio -> local agent (registered workspaceId) -> approved root -> files
```

The agent must: restrict writes to an approved root it enforces itself; preview proposed changes; preserve unrelated files; detect existing git changes and refuse to write into a dirty tree without confirmation; apply updates as patches rather than wholesale rewrites; report conflicts; optionally branch and commit.

**The server never stores a filesystem path as a reachable target.** It stores a `workspaceId`; the agent resolves it locally. The agent does not trust a path supplied by the server.

### 2c. S3 — managed destination

Used when neither a repository nor a local agent is connected, and as staging for all packages regardless of final destination.

Bytes in S3; metadata in CockroachDB: `artifact_id`, `project_id`, `artifact_type`, `version`, `content_hash`, `storage_target`, `storage_reference`, `source_memory_revision`, `generated_at`, `generation_status`.

Access is short-lived or server-mediated — never a permanent public URL. **S3 is not authoritative when a repository target is designated.**

### 2d. Precedence when unset

GitHub if connected → local workspace if an agent is registered → S3 with controlled download.

## 3. AI-tool compatibility requirements

### 3a. What every tool needs, regardless of vendor

1. **An entry point that names itself as the entry point.** `CONTEXT_INDEX.md` must state that it is read first and that `CURRENT_STATE.md` wins conflicts.
2. **Selective loading, not bulk.** Layers declared by activity. Handing an agent thirty documents defeats the purpose — the failure mode of large packages is undifferentiated information, not missing information.
3. **Stable identifiers** (`FR-APR-001`, `MOD-APR`, `OD-011`) so a task, a test, and a commit can reference the same thing.
4. **Explicit non-authorisation.** Documents state that they do not authorise implementation on their own.
5. **Open decisions marked as open**, with what they block — so the agent refuses rather than invents.
6. **Confirmation state visible.** Proposed knowledge is labelled proposed, in the artifact itself, not only in the manifest.
7. **A per-task extraction path.** One task's context, not the package.

### 3b. Tool-specific surfaces

| Tool | File | Notes |
| --- | --- | --- |
| Claude Code | `CLAUDE.md` | Read automatically; keep short and directive; point at the index rather than inlining content |
| Codex | `AGENTS.md` | Same policy, Codex idiom |
| Cursor | `.cursor/rules/*.md` | Rule files; may be scoped by glob |
| Copilot | `.github/copilot-instructions.md` | Terse; least context budget |
| Generic | `agents/project-context.yaml` | Machine-readable fallback |

**One policy, several idioms.** The same rules — read the binding, retrieve current context, identify blocking decisions, do not invent missing requirements, submit discoveries rather than editing the definition, record what was implemented — expressed per tool. Divergent policies across tools would produce divergent implementations of the same module.

### 3c. Package-plus-MCP, not package-or-MCP

The package is a **snapshot**; MCP is **live**. They are complementary and the agent instruction should say which to trust:

> Files in this package are current as of knowledge revision *N*. If the KAE MCP server is available, retrieve the current briefing before planning — knowledge may have advanced. Where they disagree, KAE-Memory is authoritative.

Without this, a stale package silently outranks live truth.

### 3d. Context-budget discipline

A full project package will exceed a comfortable context window. The package must therefore ship, and the index must advertise:

- a **module package** as the default unit of work;
- **dependency stubs** rather than neighbour specifications;
- **per-task extraction** via the task template;
- a **compressed project summary** for orientation, with pointers rather than content.

This is what `TASK_CONTEXT_TEMPLATE.md` already does by hand — *"Do not hand an agent the whole context package."*

## 4. What Memory records about publication

That an artifact was generated, from which revision, covering which knowledge; its content hash; where it was published and when; and whether publication succeeded, failed, or conflicted.

**Memory performs no commits, filesystem writes, or object transfers.** Those belong to the delivery subsystem.
