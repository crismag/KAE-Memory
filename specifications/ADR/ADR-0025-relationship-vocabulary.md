# ADR-0025 — Relationship vocabulary

**Status:** accepted, 2026-08-05. Target **N16** of
`docs/09_development/NEXT_PHASE_CHECKLIST.md`. **Settles** the alternative list
in ADR-0005 §relationships. Gates N17–N19.

## Decision

> There are **two** relationship vocabularies, and the boundary between them is
> what a relation connects.
>
> **Epistemic** — `supports`, `contradicts`, `supersedes` — relates one
> statement to another.
>
> **Structural** — `depends_on`, `owns`, `exposes`, `consumes`, `satisfies`,
> `verified_by` — relates parts of a system, or a part to a requirement.

An edge between two statements is epistemic. An edge that touches a module is
structural.

## Why four lists was the wrong framing

The register called this "four competing lists; only `depends_on` appears in
three". Reading them together, they are not four versions of one thing:

| Source | Vocabulary |
| --- | --- |
| `RelationshipType` (shipped) | supports, contradicts, derives_from, implements, validates, supersedes, blocks |
| ADR-0005 | depends_on, refines, conflicts_with, supports, derived_from, implements, reviews |
| `KAE_PACKAGE_MODEL.md` | depends_on, owns, satisfies, verified_by |
| Studio `MODULE_SPECIFICATION.md` §4 | depends_on, owns, exposes, consumes, satisfies, verified_by |

`depends_on` appears in three of four **because three of the four are about
structure**. The shipped enum is the only one describing how statements relate,
and it is the only one without `depends_on` — correctly, because one statement
does not depend on another. It follows from it, contradicts it, or is replaced
by it.

Picking a winner would have produced a vocabulary serving neither purpose:
`owns` gating readiness, `contradicts` computing build order.

## The epistemic register shrank

Seven values became three. `derives_from`, `implements`, `validates`, and
`blocks` **had no writer and no stored row** — verified at decision time: zero
rows in `knowledge_relationships`, and only `SUPPORTS`, `CONTRADICTS`, and
`SUPERSEDES` referenced anywhere in `src/`.

A vocabulary term nobody writes has no defined meaning. The first caller to use
one would be inventing the semantics rather than applying them, and would do it
in whichever direction their feature needed.

Two of the four were not lost. They were structural all along:

- `implements` → **`satisfies`**. A module satisfies a requirement. Two
  statements do not implement each other.
- `validates` → **`verified_by`**. A test verifies a requirement.

Two were genuinely retired, with the reason recorded in
`relationships.RETIRED` so an older document resolves to its replacement rather
than to silence:

- `derives_from` — provenance links already record where a statement came from.
  A second mechanism for the same fact lets the two disagree.
- `blocks` — blockers are their own record with their own resolution. An edge
  meaning the same thing gave readiness two sources for one answer.

ADR-0005's `refines` is **not adopted**. Narrowing without replacing is a real
relation and no code wrote it; declaring it again ahead of a writer repeats
exactly the mistake this decision corrects.

## Names that collided

| Two spellings | Settled | Why |
| --- | --- | --- |
| `conflicts_with` / `contradicts` | **`contradicts`** | ADR-0015 already gates readiness on it, and it is written by `record_contradiction` |
| `derived_from` / `derives_from` | neither | Both retired; the disagreement was about a term nothing used |
| `reviews` / `validates` | **`verified_by`** | And structural, not epistemic |

## The structural register matches Studio exactly

Six terms, identical to `MODULE_SPECIFICATION.md` §4. Not deference — Studio's
module view is the consumer, and a vocabulary the consumer must translate is a
vocabulary that will be translated inconsistently, in two places, differently.

Two constraints are declared with it:

- **`depends_on` and `owns` must stay acyclic.** A build order needs the first;
  the second because two modules that each own the other own nothing —
  ownership means exactly one part is answerable.
- **`owns` is exclusive.** A target has one owner. "Never let a module own data
  another module also owns" is Studio's rule and the reason `owns` is worth
  distinguishing from `depends_on` at all.

`consumes` is deliberately **not** acyclic. Two modules may legitimately consume
each other's interfaces, and forbidding it would model a rule the architecture
does not have.

## Why now, and why only this

Names are near-impossible to change once graph data exists. Today there is
none: `knowledge_relationships` holds **zero rows**, which is what made
retiring four values a rename rather than a migration. That window closes the
moment N17 writes the first edge.

This decision is vocabulary only. No schema, no migration, no write path, no
traversal. `ModuleRelation` is declared ahead of the model that stores it
because names are the part that cannot be fixed afterwards — and every term in
it has a consumer waiting in N17–N19, which is the distinction from the four
speculative values just retired.

## Consequences

**Accepted.** `RelationshipType` is now an alias of `KnowledgeRelation` rather
than its own enum. The name stays because `review_service`,
`readiness_repositories`, and ADR-0015 refer to it, and renaming call sites in
the service that gates readiness — for a rename — is churn.

**Accepted.** A document naming a retired term now raises with its replacement.
That is louder than ignoring it and is the point: three of the four source
documents use at least one retired name.

**Rejected: one merged vocabulary.** It would answer neither question. A
readiness calculation that had to skip `owns` edges, and a build order that had
to skip `contradicts` edges, are two filters over one list that was never one
list.

**Rejected: keeping the four unused values "in case".** They cost nothing to
keep and everything to have kept — the next person to need an edge would have
found a plausible name already declared and used it with whatever meaning they
had in mind.
