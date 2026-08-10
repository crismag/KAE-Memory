# KAE-Memory documentation

Durable project knowledge for AI-assisted software work. Headless — MCP and
HTTP, no interface of its own.

> **Under active development.** These pages describe the current implementation.
> **No stable-interface or backward-compatibility guarantee**, and documentation
> existing is not a claim of production readiness. Limitations are stated where
> they exist rather than left to be discovered.

---

## By what you are doing

### Understanding it

| | |
|---|---|
| [Glossary](glossary.md) | The vocabulary, meaning what the code means |
| [Knowledge lifecycle](concepts/knowledge-lifecycle.md) | How something becomes known, and why most things stop short |

### Building against it

| | |
|---|---|
| [Capability matrix](reference/capability-matrix.md) | Which adapter exposes what, and why they differ — *generated* |
| [MCP tools](reference/mcp-tools.md) | 31 tools — *generated* |
| [HTTP API](reference/http-api.md) | 49 paths, 57 operations — *generated* |
| [Errors](reference/errors.md) | The envelope, the codes, and why 409 is not 422 |
| [Configuration](reference/configuration.md) | Environment and governed settings |

### Running it

| | |
|---|---|
| [Security boundaries](architecture/security-boundaries.md) | **Read before exposing the service** |
| [Persistence and providers](architecture/persistence-and-providers.md) | PostgreSQL, Amazon RDS, and the deferred provider |

---

## Three things worth knowing before anything else

**Nothing is true because a model produced it.** Extraction proposes; a person
confirms. Only confirmed knowledge reaches assembled context. Readiness counts
candidates too, at half credit — an area with candidates and no confirmations is
*partial*, not *missing*. If you expect submitted observations to become project
truth, the system will look broken when it is working.

**Extraction is asynchronous.** A message is durable immediately; what is
derived from it appears when the run completes. An empty result a moment after
submitting usually means the run has not finished.

**The two adapters are peers, not mirrors.** 26 capabilities on both, 16 HTTP
only, 5 MCP only, 1 on neither — each difference declared with a reason. An
empty column in the matrix is a decision, not a gap.

---

## Where authority lives

Documentation is not the contract. When they disagree, the contract wins and the
documentation is wrong.

| Question | Authority |
|---|---|
| What an adapter exposes | `src/kae_memory/capabilities.py` |
| What the HTTP contract is | [`specifications/openapi.json`](../specifications/openapi.json) |
| What a lifecycle transition may do | `src/kae_memory/domain/lifecycle.py` |
| Why a decision was made | [`specifications/ADR/`](../specifications/ADR/) |
| What is not yet demonstrated | [`specifications/VERIFICATION_GATES.md`](../specifications/VERIFICATION_GATES.md) |

The capability matrix, MCP tools and HTTP API pages are **generated** from those
sources, and tests fail when they drift. The others are written, and are
therefore the ones to distrust first if something looks wrong.

## What is not documented yet

Honest gaps, not oversights:

- Quickstart, MCP client connection, and a first-project walkthrough — drafted
  against source and awaiting executable validation before publication
- Workflow guides for observation, review, clarification, retrieval and assembly
- Deployment and operations
- Architecture overview and diagrams beyond the lifecycle
- Troubleshooting, which is best written from real failures

Tracked in
[`specifications/documentation-plan/`](../specifications/documentation-plan/).

## Known limitations

Each is a real constraint on what you can rely on:

| | |
|---|---|
| Retrieval threshold fitted to a small corpus | [#82](https://github.com/crismag/KAE-Memory/issues/82) |
| Reviewer identity is unattested | [#83](https://github.com/crismag/KAE-Memory/issues/83) |
| Extraction can run without a model, visibly only in the run record | [#84](https://github.com/crismag/KAE-Memory/issues/84) |

Plus [verification gates](../specifications/VERIFICATION_GATES.md) for claims
that are reasoned rather than demonstrated.
