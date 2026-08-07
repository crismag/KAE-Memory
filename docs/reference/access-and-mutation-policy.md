# Access and mutation policy

What a client may do, and where the line is.

Canonical decision:
[ADR-0027](../../specifications/ADR/ADR-0027-application-contracts-are-the-write-path.md).
This page summarises it; the ADR governs.

---

## The rule

**Act through the supported application contracts** — MCP, HTTP, the CLI.
Those contracts perform domain operations, including writes.

**Do not reach the persistence schema directly** — not raw SQL, not a
database-provider MCP server, not provider administration tooling — as part of
any normal agent or product workflow.

The boundary is between *application contract* and *persistence schema*, and it
holds whichever database engine is configured.

## MCP is not read-only

Worth saying plainly, because an older decision's title suggested otherwise.

**30 MCP tools; 13 of them change durable state.** Submitting observations,
confirming, rejecting and correcting knowledge, answering clarifications,
recording assumptions and deliverables, defining and relating modules, settling
operational records, creating projects, ingesting documents.

ADR-0004 was titled *"CockroachDB MCP is inspection-only"*. Its subject was a
**database** MCP server pointed at the cluster — never KAE-Memory's own adapter.
ADR-0027 restates the boundary without the ambiguous noun.

## What this does not restrict

**Operators.** Migrations, backup and restore, capacity work, incident recovery —
these use database tooling directly and always will. They are administration,
not product workflow, and no policy that forbade them would be followed.

**Debugging.** Reading the schema to understand a fault is inspection, and
inspection was never the problem.

**Provider choice.** This says nothing about which engine to run.

The line is **normal operation versus administration**, not *read versus write*.

## Why

Domain rules live in application code, not in the schema:

| Rule | Where |
|---|---|
| Lifecycle transitions | `domain/lifecycle.py` |
| Run-status transitions | `domain/execution.py` |
| Append-only versions, supersession without deletion | domain services |
| Mandatory provenance | the write paths |
| Optimistic concurrency on review | `expected_version`, refused with 409 |

`UPDATE knowledge SET lifecycle = 'validated'` succeeds at the SQL level. It
produces a statement the project believes a person confirmed — with no reviewer,
no version check, no transition validation, no trace. **Nothing downstream can
tell it apart from a real confirmation**, which is precisely the confusion the
review surface exists to prevent.

The database cannot reconstruct those rules, and asking it to would mean
duplicating the domain in schema constraints on every supported engine.

> That direct writes bypass these rules is currently **reasoned from where the
> enforcement lives, not demonstrated by a test** —
> [#86](https://github.com/crismag/KAE-Memory/issues/86).

## Authentication

A bearer token from `KAE_API_TOKENS`, optionally scoped to named projects.

**Before exposing the service, read
[security boundaries](../architecture/security-boundaries.md).** The startup
guards do not cover every deployment shape, and the page says which.

## Attribution is not verified

The `reviewer` on a confirmation or rejection is caller-supplied free text. An
authenticated caller can attribute a decision to someone who never made it.

Provenance is reliable about *what* was decided and *when*. It is only as
reliable as the caller about *who*
([#83](https://github.com/crismag/KAE-Memory/issues/83)).

Treat reviewer attribution as advisory.

## Needing something that is not exposed

The answer is a **new capability** — declared in `capabilities.py`, enforced on
both adapters by `tests/api/test_adapter_parity.py` — not a SQL workaround.

That is how the twelve-capability divergence N1 measured was found: the registry
made it findable. A workaround would have made it permanent and invisible.

## Related

- [ADR-0027](../../specifications/ADR/ADR-0027-application-contracts-are-the-write-path.md)
- [Capability matrix](capability-matrix.md) · [Errors](errors.md)
- [Knowledge lifecycle](../concepts/knowledge-lifecycle.md)
