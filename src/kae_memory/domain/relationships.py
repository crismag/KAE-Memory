"""The relationship vocabulary (N16, ADR-0025).

Four lists existed. They were never four versions of one thing, which is why
reconciling them by picking a winner would have produced a vocabulary that
served neither purpose:

* the shipped `RelationshipType` describes how two **statements** relate —
  whether one supports, contradicts, or replaces another;
* ADR-0005, `KAE_PACKAGE_MODEL.md`, and KAE-Studio's `MODULE_SPECIFICATION.md`
  describe how **parts of a system** relate — what depends on what, who owns
  what, what satisfies which requirement.

`depends_on` appears in three of the four because three of the four are about
structure. One statement does not depend on another; it follows from it, or
contradicts it, or is replaced by it. A *module* depends on a module.

So there are two registers here, deliberately separate, and one rule:

    an edge between two statements is epistemic;
    an edge that touches a module is structural.

Merging them would put `owns` in the vocabulary that gates readiness, and
`contradicts` in the vocabulary that computes build order. Neither is a
question the other can answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import DomainInvariantError


class KnowledgeRelation(StrEnum):
    """How one statement relates to another.

    Three values, and the count is the decision. The shipped enum declared
    seven; `derives_from`, `implements`, `validates`, and `blocks` were never
    written by any code path and never stored by any row. A vocabulary term
    with no writer has no defined meaning, and the first person to use one
    would be inventing the semantics rather than applying them.

    Two of the four are not lost — they were structural all along and moved to
    :class:`ModuleRelation`. A module implements a requirement; a test verifies
    one. Neither is a relation between two statements.
    """

    SUPPORTS = "supports"
    """The source is evidence for the target."""

    CONTRADICTS = "contradicts"
    """The two cannot both hold. Gates readiness until resolved (ADR-0015)."""

    SUPERSEDES = "supersedes"
    """The source replaces the target, which stays readable as history."""


class ModuleRelation(StrEnum):
    """How a part of the system relates to another part, or to knowledge.

    Matches KAE-Studio's `MODULE_SPECIFICATION.md` §4 exactly. That is not a
    coincidence and not deference: Studio's module view is the consumer, and a
    vocabulary the consumer has to translate is a vocabulary that will be
    translated inconsistently.

    Declared before the model that stores it (N17) because names are the part
    that cannot be changed afterwards. That was the state when this was written
    and it stopped being true: every member is writable through
    :meth:`ModuleService.relate`, stored in ``module_relationships``, and
    reachable from outside the process by the ``kae_relate_modules`` MCP tool.
    ``GET /modules/graph`` returns them.

    The rule the old sentence carried still holds and is now about consumers
    rather than writers: a term added here arrives at KAE-Studio through that
    route, where the architecture diagram draws one member and accounts for the
    rest in ``drawnRelations.ts``. A seventh added without placing it there is a
    relation somebody records and no picture shows (`D-219`).
    """

    DEPENDS_ON = "depends_on"
    """The source needs the target to function. Must stay acyclic."""

    OWNS = "owns"
    """The source is the single authority for the target — data, or a decision."""

    EXPOSES = "exposes"
    """The source offers the target as an interface others may consume."""

    CONSUMES = "consumes"
    """The source uses an interface the target exposes."""

    SATISFIES = "satisfies"
    """The source implements the requirement or objective the target states."""

    VERIFIED_BY = "verified_by"
    """The target is the acceptance test or check that proves the source."""


ACYCLIC: frozenset[ModuleRelation] = frozenset({ModuleRelation.DEPENDS_ON, ModuleRelation.OWNS})
"""Relations a cycle would make meaningless.

`depends_on` because a build order needs one. `owns` because two modules that
each own the other own nothing — the point of ownership is that exactly one
part is answerable.

`consumes` is deliberately absent: two modules may legitimately consume each
other's interfaces, and forbidding that would model a rule the architecture
does not have.
"""

EXCLUSIVE: frozenset[ModuleRelation] = frozenset({ModuleRelation.OWNS})
"""Relations where a target may have only one source.

"Never let a module own data another module also owns" — Studio's module
specification, and the reason `owns` is worth distinguishing from `depends_on`
at all.
"""


@dataclass(frozen=True, slots=True)
class RelationDirection:
    """What a directed edge means read forwards and backwards.

    Recorded because "A depends_on B" and "B depends_on A" are both readable
    English and only one is true, and the cost of getting it backwards is a
    build order that runs in reverse.
    """

    relation: ModuleRelation
    forward: str
    inverse: str


DIRECTIONS: tuple[RelationDirection, ...] = (
    RelationDirection(ModuleRelation.DEPENDS_ON, "needs", "is needed by"),
    RelationDirection(ModuleRelation.OWNS, "is the authority for", "is owned by"),
    RelationDirection(ModuleRelation.EXPOSES, "offers", "is offered by"),
    RelationDirection(ModuleRelation.CONSUMES, "uses", "is used by"),
    RelationDirection(ModuleRelation.SATISFIES, "implements", "is implemented by"),
    RelationDirection(ModuleRelation.VERIFIED_BY, "is proven by", "proves"),
)

RETIRED: dict[str, str] = {
    # Kept as a lookup rather than deleted, so a document or a branch that
    # still names one of these resolves to what replaced it instead of to
    # silence. Every one had zero writers and zero stored rows when it was
    # retired, which is the only reason this was cheap.
    "derives_from": (
        "retired: provenance links already record where a statement came from, "
        "and a second mechanism for the same fact would let the two disagree"
    ),
    "derived_from": "retired: a spelling of derives_from that never shipped",
    "implements": "moved to ModuleRelation.SATISFIES — a module satisfies a requirement",
    "validates": "moved to ModuleRelation.VERIFIED_BY — a test verifies a requirement",
    "blocks": (
        "retired: blockers are their own record with their own resolution, and "
        "an edge that meant the same thing gave readiness two sources for one answer"
    ),
    "conflicts_with": "renamed: CONTRADICTS, which ADR-0015 already gates readiness on",
    "refines": (
        "not adopted: narrowing without replacing is real, and no code wrote it. "
        "Declaring it again ahead of a writer is the mistake this target corrected"
    ),
    "reviews": "renamed: VERIFIED_BY, and structural rather than epistemic",
}


def resolve(name: str) -> KnowledgeRelation | ModuleRelation:
    """Return the relation a name refers to, or say what replaced it.

    A vocabulary settled across four documents needs a migration path for the
    names the other three used. Raising with the replacement is more useful
    than raising with "unknown", because the caller reading it is almost
    certainly holding an older document.
    """

    normalised = name.strip().lower()
    current: tuple[KnowledgeRelation | ModuleRelation, ...] = (*KnowledgeRelation, *ModuleRelation)
    for relation in current:
        if relation.value == normalised:
            return relation
    if normalised in RETIRED:
        raise DomainInvariantError(f"{name!r} is not a current relation — {RETIRED[normalised]}")
    known = ", ".join(sorted(r.value for r in (*KnowledgeRelation, *ModuleRelation)))
    raise DomainInvariantError(f"unknown relation {name!r}; the vocabulary is: {known}")


def is_structural(relation: KnowledgeRelation | ModuleRelation) -> bool:
    """Whether this relation describes system structure rather than epistemics."""

    return isinstance(relation, ModuleRelation)
