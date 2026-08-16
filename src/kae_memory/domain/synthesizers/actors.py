"""Actor synthesis — 22 peer `actor v1` rows to a responsibility model.

`03-ACTORS-STAKEHOLDERS.md`: a better list of actors does not fix a list of
actors. A taxonomy of role types is still one-dimensional, and the reader still
cannot answer the only question that matters — **who is responsible for what**.

So the spine is the relation, not the cast list:

    Role  ×  Subject  →  Responsibility

## The persona split is the relation, not a word list (`D-120`)

Doc 03 line 10: *"a role with no responsibility anywhere is a persona, not a
project actor."* That sentence is implemented here rather than paraphrased. A
human-shaped candidate that acquires an assignment is a **project role**; one
that acquires none is a **persona** — somebody the product serves, who holds
nothing in the project. `D-119` refused to build the taxonomy without the
relation for exactly this reason: the discriminator lives in the relation.

A qualifier signal (`first-time`, `aspiring`, `experienced`) exists as a
*secondary* mark, and it is the weakest thing in this module. It can only
describe a candidate that already acquired no responsibility, so being wrong
about it moves a row between two non-authoritative renderings. It can never
manufacture an assignment, and it must not grow into `D-16`'s tuned table.

## Silence is a refusal

Doc 03: *"attach responsibilities only where evidence names both a role and a
subject"*, and *"refuse to guess an Accountable party; an unowned subject is a
legitimate finding."* Where a statement names no area, or names two equally,
nothing is written. `area_classification.DEFAULT_AREA_FOR_KIND` is deliberately
not consulted — defaulting is right when the question is *where does this
sentence file* and wrong when it is *what does this person own*.

Everything here is pure. Storage, clustering over vectors and the run live above.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..area_classification import areas_named_by


class RoleKind(StrEnum):
    """What kind of thing a clustered actor description turned out to be.

    Doc 03 keeps humans, AI and systems in separate models and connects them
    through the same relation. ``unclassified`` is a real answer: a bare proper
    noun names no function, and guessing one would put a model provider in the
    human responsibility model.
    """

    PROJECT_ROLE = "project_role"
    PERSONA = "persona"
    AI_ROLE = "ai_role"
    SYSTEM = "system"
    UNCLASSIFIED = "unclassified"


class Responsibility(StrEnum):
    """RACI. Four letters, one Accountable, human only — doc 03's *Not adopted*."""

    RESPONSIBLE = "responsible"
    ACCOUNTABLE = "accountable"
    CONSULTED = "consulted"
    INFORMED = "informed"


#: Words that make a description a *system* rather than an actor.
#:
#: Doc 03 names the category in its own words — "MCP servers, APIs,
#: repositories, databases, model providers and external services". These are
#: the category's nouns, not any project's proper nouns.
_SYSTEM: Final = re.compile(
    r"\b(mcp|api|apis|server|servers|service|services|database|databases|"
    r"repository|repositories|endpoint|endpoints|webhook|webhooks|"
    r"integration|integrations|provider|providers|platform|queue|broker)\b",
    re.IGNORECASE,
)

#: Words that make a description an *AI* role.
#:
#: An assistant, an agent or a model. ``kae`` is here because the product is the
#: AI in its own corpus; it is one proper noun and it is the subject of the
#: whole estate rather than a term read off a fixture.
_AI: Final = re.compile(
    r"\b(ai|llm|model|models|agent|agents|assistant|assistants|bot|bots|"
    r"copilot|kae|interviewer|synthesizer)\b",
    re.IGNORECASE,
)

#: Project *functions* — a position somebody holds over the work.
#:
#: Doc 03's own list: owner, decision maker or approval authority, domain
#: experts and contributors, implementers, testers, reviewers, administrators
#: and operators.
_FUNCTION: Final = re.compile(
    r"\b(owner|owners|authority|authorities|approver|approvers|steward|"
    r"maintainer|maintainers|reviewer|reviewers|tester|testers|"
    r"implementer|implementers|operator|operators|administrator|"
    r"administrators|admin|expert|experts|contributor|contributors|"
    r"sponsor|sponsors|lead|architect|analyst|auditor)\b",
    re.IGNORECASE,
)

#: Experience qualifiers that describe a *person*, not a project position.
#:
#: The weakest signal in this module, and secondary by construction — see the
#: module docstring. Doc 03 names this exact pattern when it calls `first-time
#: founder` and `aspiring developer` variants of a user.
_PERSONA_QUALIFIER: Final = re.compile(
    r"\b(first[- ]time|aspiring|experienced|novice|seasoned|casual|power|"
    r"prospective|would[- ]be|new)\b",
    re.IGNORECASE,
)

#: Wordings that carry decision authority — doc 03's Accountable.
#:
#: "Answers for the outcome and holds decision authority." Approving, accepting
#: and signing off are the same act under different verbs.
#: Deliberately *not* ``accept\w*``. "Tester who validates acceptance criteria"
#: names acceptance as the thing being tested, not as an act of authority, and
#: reading it as Accountable would hand decision rights to the tester. Only the
#: verb forms count.
_ACCOUNTABLE: Final = re.compile(
    r"\b(accountable|authority|authorities|approves?|approving|approval|"
    r"accepts?|accepting|signs? off|sign[- ]off|decides|deciding|"
    r"decision maker|owner|owners|owns)\b",
    re.IGNORECASE,
)

#: Wordings that carry the work itself — doc 03's Responsible.
_RESPONSIBLE: Final = re.compile(
    r"\b(implement\w*|build\w*|writ\w*|produc\w*|maintain\w*|operat\w*|"
    r"administer\w*|administrator|admin|test\w*|validat\w*|verif\w*|"
    r"run\w*|deliver\w*|generat\w*|review\w*)\b",
    re.IGNORECASE,
)

#: Wordings that carry advice before the fact — doc 03's Consulted.
_CONSULTED: Final = re.compile(
    r"\b(consult\w*|advis\w*|expert|experts|contribut\w*|input|"
    r"asked before|weighs in)\b",
    re.IGNORECASE,
)

#: Wordings that carry notification after the fact — doc 03's Informed.
_INFORMED: Final = re.compile(
    r"\b(informed|notified|told|kept up to date|receiv\w*|consum\w*|"
    r"downstream|subscrib\w*)\b",
    re.IGNORECASE,
)


#: Nouns that say the description is about a human being.
#:
#: These outrank the AI and system markers, because those markers appear in a
#: human description as the thing the human *uses*: "A person using KAE" names a
#: person, and "Administrator of credentials and providers" names an
#: administrator. A marker alone is what the description is *about* only when no
#: human is named in it.
_PERSON: Final = re.compile(
    r"\b(person|people|human|humans|user|users|customer|customers|buyer|buyers|"
    r"beneficiary|beneficiaries|founder|founders|developer|developers|"
    r"someone|somebody|stakeholder|stakeholders|team|colleague|staff)\b",
    re.IGNORECASE,
)


def kind_of(statement: str, *, holds_responsibility: bool) -> RoleKind:
    """Classify one clustered actor description.

    ``holds_responsibility`` is what the relation found, and it is what decides
    the human split — doc 03's own definition of a persona. Systems and AI are
    separated first, because doc 03 keeps them in their own models and they must
    not be flattened into human stakeholders whether they own something or not;
    but only where the description is not already about a person.
    """

    human = bool(_PERSON.search(statement))
    function = bool(_FUNCTION.search(statement))
    if not human:
        if _SYSTEM.search(statement) and not function:
            return RoleKind.SYSTEM
        if _AI.search(statement):
            return RoleKind.AI_ROLE
    if holds_responsibility or function:
        return RoleKind.PROJECT_ROLE
    if human or _PERSONA_QUALIFIER.search(statement):
        return RoleKind.PERSONA
    return RoleKind.UNCLASSIFIED


def letter_of(statement: str) -> Responsibility | None:
    """Which RACI letter the wording carries, or ``None`` if it carries none.

    Ordered by how much the letter claims. Accountable is checked first because
    it is the strongest reading and the one doc 03 refuses to guess at — a
    statement that says both *approves* and *reviews* is claiming authority, and
    reading it as merely Responsible would understate what the evidence says.
    """

    if _ACCOUNTABLE.search(statement):
        return Responsibility.ACCOUNTABLE
    if _RESPONSIBLE.search(statement):
        return Responsibility.RESPONSIBLE
    if _CONSULTED.search(statement):
        return Responsibility.CONSULTED
    if _INFORMED.search(statement):
        return Responsibility.INFORMED
    return None


def subject_of(statement: str) -> str | None:
    """The single readiness area this description names, or ``None``.

    ``None`` where nothing fired and where two areas tied. Both are refusals,
    and both are correct: doc 03 wants an unowned subject to stay a legitimate
    finding rather than become a guessed assignment.
    """

    named = areas_named_by(statement)
    if len(named) != 1:
        return None
    return named[0]


@dataclass(frozen=True, slots=True)
class RoleCandidate:
    """One cluster of actor evidence, before anything decides what it is."""

    members: tuple[str, ...]
    """Opaque member keys — the caller's knowledge item ids, as strings."""

    canonical_key: str
    statement: str


@dataclass(frozen=True, slots=True)
class Assignment:
    """One cell of the matrix: a role, a subject, and what it holds there."""

    role_statement: str
    subject_key: str
    letter: Responsibility
    basis: str


@dataclass(frozen=True, slots=True)
class RoleModelPlan:
    """What an actor synthesis run would write, before it writes anything."""

    roles: tuple[tuple[RoleCandidate, RoleKind], ...]
    assignments: tuple[Assignment, ...]
    conflicts: tuple[tuple[str, str], ...]
    """Subjects with a second Accountable claimant, each with the reason.

    Invariant 2 in doc 03's own words: *"Where evidence supports two, that is a
    conflict for the human-attention model, not a second row."*
    """

    downgraded: tuple[tuple[str, str], ...]
    """Non-human claimants of Accountable, each with the reason it was refused.

    Invariant 1 is the governance line KAE already holds. Dropping the row would
    hide that the evidence claimed it, so the claim is kept as Responsible and
    the refusal is reported.
    """


def plan_role_model(candidates: Sequence[RoleCandidate]) -> RoleModelPlan:
    """Turn clustered actor descriptions into roles and responsibilities.

    Two passes, because the persona split reads the relation. The first derives
    every assignment the wording supports and applies the invariants; the second
    classifies each candidate knowing whether it ended up holding anything.
    """

    assignments: list[Assignment] = []
    conflicts: list[tuple[str, str]] = []
    downgraded: list[tuple[str, str]] = []
    accountable_for: dict[str, str] = {}
    holders: set[str] = set()

    for candidate in candidates:
        subject = subject_of(candidate.statement)
        letter = letter_of(candidate.statement)
        if subject is None or letter is None:
            continue

        non_human = kind_of(candidate.statement, holds_responsibility=False) in {
            RoleKind.AI_ROLE,
            RoleKind.SYSTEM,
        }
        if letter is Responsibility.ACCOUNTABLE and non_human:
            downgraded.append(
                (
                    candidate.statement,
                    "An AI role or a system is never Accountable, so the evidence's "
                    "claim of authority is recorded as doing the work instead.",
                )
            )
            letter = Responsibility.RESPONSIBLE

        if letter is Responsibility.ACCOUNTABLE:
            held_by = accountable_for.get(subject)
            if held_by is not None and held_by != candidate.statement:
                conflicts.append(
                    (
                        candidate.statement,
                        f"{held_by!r} is already accountable for {subject}. Two "
                        "accountable parties means nobody is, so this is a conflict "
                        "for a person rather than a second assignment.",
                    )
                )
                holders.add(candidate.statement)
                continue
            accountable_for[subject] = candidate.statement

        assignments.append(
            Assignment(
                role_statement=candidate.statement,
                subject_key=subject,
                letter=letter,
                basis=f"the description names {subject} and reads as {letter.value}",
            )
        )
        holders.add(candidate.statement)

    roles = tuple(
        (
            candidate,
            kind_of(
                candidate.statement,
                holds_responsibility=candidate.statement in holders,
            ),
        )
        for candidate in candidates
    )

    return RoleModelPlan(
        roles=roles,
        assignments=tuple(assignments),
        conflicts=tuple(conflicts),
        downgraded=tuple(downgraded),
    )
