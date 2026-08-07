# KAE-Memory

**Durable, reviewable project knowledge that outlives any single AI
conversation.**

KAE-Memory is the headless knowledge service of the KAE ecosystem. It holds what
a software project has established, keeps the record of how it came to be
established, and serves that to agents and applications over MCP and HTTP.

It renders no interface. What a person looks at belongs to
[KAE-Studio](#where-this-sits).

> **Under active development.** This documentation describes the current
> implementation. There is **no stable-interface or backward-compatibility
> guarantee**, and extensive documentation is not a claim of production
> readiness. Known gaps and outstanding validation are tracked in the
> [issues](https://github.com/crismag/KAE-Memory/issues) and in
> [`specifications/VERIFICATION_GATES.md`](specifications/VERIFICATION_GATES.md).

---

## Why it exists

An AI conversation forgets. Close the session, switch tools, hand the work to a
different agent, come back a month later — and the reasoning is gone. What
survives is a transcript nobody rereads and a codebase that cannot say why it is
shaped the way it is.

Projects lose more to that than to any individual mistake. The decision
carefully argued in March gets re-argued in June, differently, because nothing
carried it forward.

KAE-Memory keeps the knowledge separately from the conversation, so it belongs
to the project rather than to whichever chat happened to produce it.

## What makes it more than a vector store

A vector store retrieves text resembling a query. Everything below is
implemented and testable, and none of it is similarity search.

**A lifecycle, not a pile.** Knowledge is `proposed`, `validated`, `rejected` or
`superseded`. Transitions are enforced, rejection is terminal, and rejected
items are kept — what a project decided *against* is part of what it knows.

**Nothing is true because a model said it.** Everything extraction produces
arrives as a candidate. A person confirms it or it stays a candidate, and only
confirmed knowledge counts toward readiness or reaches assembled context.

**Provenance, not vibes.** Any statement resolves back to the message or
document that produced it.

**Correction preserves history.** Rewording adds a version and supersedes the
old one. Nothing is edited in place.

**Unknowns are recorded as unknowns.** Where evidence does not settle something,
it is stored as a typed `unknown` rather than filled with a plausible guess —
and becomes a question someone can answer.

**Context is assembled, not dumped.** A bounded package for a specific task,
which reports what it could not resolve rather than quietly omitting it.

**Structure.** Modules, dependencies, build order, deliverables with manifests
and hashes.

The [capability matrix](docs/reference/capability-matrix.md) is generated from
the registry that enforces it — 43 capabilities across two adapters.

---

## Start here

| You want to | Go to |
|---|---|
| Learn the vocabulary | [Glossary](docs/glossary.md) |
| Understand how knowledge forms | [Knowledge lifecycle](docs/concepts/knowledge-lifecycle.md) |
| Call it from an agent | [MCP tools](docs/reference/mcp-tools.md) |
| Build against HTTP | [HTTP API](docs/reference/http-api.md) |
| Know which adapter has what | [Capability matrix](docs/reference/capability-matrix.md) |
| Configure it | [Configuration](docs/reference/configuration.md) |
| Run it safely | [Security boundaries](docs/architecture/security-boundaries.md) |
| Read everything | [Documentation index](docs/index.md) |

## Running it locally

```bash
make install     # uv sync --extra dev --extra api
make dev         # database, migrations, API, and worker
```

The API is then on <http://localhost:8000> — `/health` for status, `/docs` for
the routes. Nothing needs AWS and no credentials are required; extraction falls
back to a deterministic fixture offline.

```bash
make check       # ruff, ruff format, mypy strict, pytest
```

---

## Where this sits

| Component | Owns | Repository |
|---|---|---|
| **KAE-Memory** | Durable project knowledge, retrieval, context assembly | this one |
| **KAE-Studio** | The product interface — everything a person looks at | separate |
| **CIE** | Conversation and interview intelligence | separate |

KAE-Memory is headless by decision
([ADR-0026](specifications/ADR/ADR-0026-kae-memory-is-headless.md)). Deployment
coordination for the wider ecosystem is not part of this component, and this
repository ships no cloud provisioning automation.

## Maturity, plainly

- Under active development, with a working deployment and a substantial test
  suite.
- **No stable-interface or backward-compatibility guarantee.**
- **PostgreSQL is the database target**, with Amazon RDS for PostgreSQL as the
  hosted environment. An earlier CockroachDB provider integration remains in the
  codebase; compatibility with the current schema has not been reverified, and
  CockroachDB deployment and parity testing are deferred
  ([#81](https://github.com/crismag/KAE-Memory/issues/81)).
- Several behaviours are reasoned from the implementation rather than
  demonstrated by a test. Those are
  [open issues](https://github.com/crismag/KAE-Memory/issues), not silent
  assumptions.
- Documentation states limitations where they exist. A system whose limits are
  written down is more usable than one whose limits are discovered.

## Repository

| | |
|---|---|
| `src/kae_memory/` | Application, domain, adapters, worker |
| `specifications/` | Current contracts, ADRs, verification gates |
| `docs/` | This documentation |
| `deploy/server/` | Generic Linux installation |
| `operations/runbooks/` | Operator procedures |
| `migrations/` | Schema revisions |

## Licence

Apache-2.0. See [`LICENSE`](LICENSE).
