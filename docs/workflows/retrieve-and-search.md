# Retrieval and search

Finding what a project knows.

> Drafted from source and tests; executable validation outstanding.

---

## Searching

`kae_search_knowledge`, or `GET /v1/projects/{project_id}/knowledge/search`.

Semantic: it matches meaning rather than keywords, so a query about "who uses
this" can return a statement phrased as "the operations team files the report"
without sharing a word.

Filter by lifecycle to separate what is confirmed from what is merely proposed —
usually the first thing you want, since the two carry very different weight.

## A limitation worth knowing before you rely on it

The relevance threshold (`MAX_DISTANCE = 0.85`) was fitted to **twenty queries
over thirty-two chunks**. The window between the worst genuine match (0.840) and
the nearest noise (0.847) is **0.005 wide**, and one weak query already leaked
at fitting time.

On a materially larger corpus, expect the boundary to be less reliable than that
number suggests — in both directions. Tracked as
[#82](https://github.com/crismag/KAE-Memory/issues/82); hybrid ranking rather
than a different constant is the durable answer.

Read results as candidates for your attention, not as an authoritative set.

## Assembled context, not raw results

For handing work to an agent, prefer
[context assembly](assemble-context.md) over a search. It bounds the result,
pins versions, and reports what it could not resolve — a raw result set does
none of that, and an agent cannot tell a short answer from a truncated one.

## Module scope

`kae_get_module_context` retrieves for one module rather than the whole project.
Narrower, and usually what an implementing agent should ask for.

## Related

- [Context assembly](assemble-context.md)
- [Modules and dependencies](../concepts/modules-and-dependencies.md)
- [MCP tools](../reference/mcp-tools.md)
