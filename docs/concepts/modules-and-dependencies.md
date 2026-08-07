# Modules and dependencies

How a system under design is decomposed, and how the pieces relate.

> **Reachable over MCP only.** Not a gap — a decision, with reasons recorded per
> capability in the [capability matrix](../reference/capability-matrix.md).

---

## What a module is

A named part of the system being built. Modules are **proposed** like any other
knowledge and confirmed by a person; extraction can suggest a decomposition, and
suggesting is not deciding.

## Relationships

Typed edges between modules, or between a module and a statement. The common
case is a dependency, and the useful consequence is **build order**:
`kae_get_module_graph` returns the modules and the order they can be built in.

An implementing agent asks for that order. It is the question the graph exists
to answer.

> Cycle prevention appears to be implemented and is **not yet covered by a
> test** — [#88](https://github.com/crismag/KAE-Memory/issues/88).

## Module-scoped context

`kae_get_module_context` assembles what an agent needs to implement **one**
module, rather than everything the project knows.

That bounding is the point. An agent given the whole project spends its context
on material irrelevant to the task, and the relevant part competes with it.

## Why MCP only

Five capabilities are `agent_only`, each with its own recorded reason:

- **`module.define`, `module.relate`** — Studio's curation act is
  `recordModuleDecision`, a different contract that has not been reconciled
  (N12). Writing HTTP routes now would fix a shape the discussion has not
  settled.
- **`module.graph`, `module.context`** — the consumer is an implementing agent.
  A Studio view of the same graph is a rendering question, and rendering is
  Studio's.
- **`observation.submit`** — Studio's equivalent is a conversation message, a
  different durable act. Both over HTTP would give a client two ways to say one
  thing.

Tracked as [#85](https://github.com/crismag/KAE-Memory/issues/85). Whether the
curation contract eventually needs HTTP routes is a product question, not an
oversight to correct.

## Related

- [Capability matrix](../reference/capability-matrix.md)
- [MCP tools](../reference/mcp-tools.md)
- [Knowledge lifecycle](knowledge-lifecycle.md)
