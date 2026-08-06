# Configuration and message inventory (N7, N8)

Status: **audited** 2026-08-05.
Focus: [`CONFIGURATION_AND_MESSAGES.md`](../00_project/focus/CONFIGURATION_AND_MESSAGES.md).

The focus file asks for an auditable inventory and a classification *before*
behaviour changes, then one migrated slice. This is the inventory. What was
migrated is the pagination and response-limit slice, chosen because T4/T5
already test its contract — a migration that changed behaviour would fail
loudly rather than be taken on trust.

## Placement decisions

Every behaviour-changing literal found in executable Python, classified against
the focus file's placement table. The classification is the point of the audit;
only the first row was migrated.

| Value | Where it was | Classification | Action |
| --- | --- | --- | --- |
| `DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`, `MAX_PAGE`, `CLARIFICATION_LIMIT` | MCP response policy, HTTP router, MCP tools | safe product default | **governed** — `settings/defaults.toml` |
| `MAX_BODY_BYTES` (2 MB) | `api/security.py` | absolute resource ceiling | stays in code, documented non-overridable |
| `DRAFT_THRESHOLD` (50.0), `SPARSE_KNOWLEDGE_THRESHOLD` (40) | readiness, capability readiness | product judgement with a stated rationale | stays; a deployment tuning what "sparse" means would change what readiness *claims*, not how it behaves |
| `MAX_DISTANCE` (0.85), `MAX_TOKENS` (1000) | `domain/chunks.py` | mathematical / tokeniser property | named constant near the code |
| `DEFAULT_LEASE_SECONDS`, `DEFAULT_HEARTBEAT_SECONDS` | `domain/execution.py` | product default, already env-overridable per worker | not migrated; worker configuration is a coherent second slice |
| `DEFAULT_MAX_CHUNKS`, `DEFAULT_MAX_ITEMS_PER_CHUNK` | ingestion | product default, already env-overridable | not migrated; belongs with the ingestion slice |
| `DEFAULT_BATCH_SIZE` (50) | re-embedding | operational batch size | not migrated |
| `DEFAULT_MODEL`, `DEFAULT_MAX_TOKENS` | bedrock, semantic classifier | deployment/provider value | environment; never a committed default |
| `KAE_DATABASE_URL`, `KAE_API_TOKENS`, provider selection | config, security, provider | secret or deployment fact | environment only — a committed file is read by everyone who clones the repository |

**What the audit found.** `MAX_PAGE_SIZE` in the MCP response policy and
`MAX_PAGE` in the HTTP router were the same number, written twice, carrying the
same docstring. Nothing would have noticed them diverging. They are now one
governed value read by both adapters, and a test asserts they are the same
object rather than merely equal.

## Schema

Each governed setting declares, in `settings/catalog.py`: a stable dotted key,
type, unit, rationale, scope, reload behaviour, the environment variable that
overrides it (or `None`), an allowed range, an optional non-overridable
ceiling, and any security, cost, or performance implication.

The **value** lives in `settings/defaults.toml`. The **contract** lives in the
catalog. A catalog entry with no committed value is refused at construction, and
so is a value out of range — both at startup rather than on the first call that
reads the setting, which is reliably the one furthest from anyone who could fix
it.

## Precedence

1. a **coded ceiling** — an absolute boundary no deployment may cross. Not a
   value it supplies, but a refusal it cannot argue with;
2. an **environment override** — what this installation chose;
3. the **committed default** — what ships.

The two further layers the focus file reserves — administrative and
project-level overrides — are deliberately **absent**. Both need an
authorisation model this repository does not have, and building the plumbing
before the authority produces a system overridable by whoever reaches it first.

An override outside its range is **refused, not clamped**: a caller silently
given a different number than they asked for will debug everything except the
number. An exported-but-empty variable is not an override.

## Traceability

`Settings.explain(key)` returns the effective value, its source, its unit, its
scope, the variable that overrides it, and the committed default it would
otherwise have. `explain_all()` returns the whole picture at once — "why is the
page size 40" is asked at the worst possible moment, and an answer requiring
three files is not one.

`unknown_overrides()` reports `KAE_*` variables that govern nothing. A variable
nothing reads is worse than no variable: someone sets it, watches nothing
change, and concludes the setting is broken. It reports rather than refuses,
because it cannot tell a typo from a subsystem knob that has not been migrated —
and `_UNGOVERNED` is the honest record of the second category rather than a
claim that the first slice covered everything.

## TOML, not YAML

The focus file's placement table names YAML. `tomllib` is in the standard
library and is read-only, which is exactly the shape of a committed defaults
file: the application never writes it, and a parser that *cannot* write it
removes a category of mistake. YAML would have added a dependency to gain
nothing this file needs.

## Messages (N8)

Inventoried by finding every string of forty characters or more appearing in
more than one module. The result was small, and most of it was docstrings.

Migrated to `messages.py` with stable keys — the narrow set where drift is not
cosmetic:

- **integrity notes**, said by both adapters. Each is a caveat about what a
  response does *not* establish; an adapter that softened its copy would claim
  more than KAE knows. Three copies of "Reported, not verified" existed and two
  ended differently. That divergence was not a decision.
- **cross-adapter refusals** — unknown purpose, unconfigured capability. A
  caller reading two explanations for one rejection learns the two surfaces are
  different products. The capability refusal had eight near-identical copies.
- **environment failures** — the missing-extra instruction, in three adapters.

**Not migrated, deliberately:** docstrings, one-off errors, domain invariant
messages that name their own field, and anything said in exactly one place. A
message with one caller is not duplicated; moving it would cost a lookup and buy
nothing. A test bounds the catalog at twenty entries so growth is a decision
rather than a habit.

**One split rather than a merge.** The two classification notes looked like
drift and are not: a read cannot change an operational status and must not deny
having done so, because a caveat about an action nobody took reads as
reassurance about the wrong thing. They are two keys.

Frontend copy belongs to KAE-Studio and never enters this catalog.
