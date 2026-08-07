# Assembling context

Producing a bounded package of what an agent needs for a task.

> Drafted from source and tests; executable validation outstanding.

---

## The call

`kae_assemble_context`, or `POST /v1/projects/{project_id}/context`.

Returns confirmed knowledge relevant to the task, bounded, with versions pinned
and unresolved gaps named.

## Why not just send everything

Two reasons, and the second is the one people miss.

**Budget.** A whole project does not fit, and what does fit crowds out the
agent's reasoning.

**Relevance is a decision.** Sending everything moves the judgement about what
matters onto the agent, which has less information about the project than the
service does.

## What makes it more than a query

**Versions are pinned.** The package names the exact versions it drew on, so
what an agent worked from is reconstructable afterwards. Without that,
"why did it do that" has no answer once the knowledge moves.

**Gaps are reported, not omitted.** Where the project does not know something
the task needs, the package says so. An agent that receives silence assumes
completeness; one that receives a named gap can ask, or proceed knowingly.

**Only confirmed knowledge.** Candidates are not context. An agent acting on
unconfirmed extraction is acting on something nobody agreed to.

## Deliverables

`kae_record_deliverable` records an output with a manifest, per-artifact hashes
and provenance.

**The record is not the artifact.** KAE-Memory holds what it was, what it
contained, and where it came from. Rendered bytes are an artifact concern —
rendered means produced, published means written somewhere, and the two are
distinct states.

## Related

- [Retrieval and search](retrieve-and-search.md)
- [Knowledge lifecycle](../concepts/knowledge-lifecycle.md)
- [MCP tools](../reference/mcp-tools.md)
