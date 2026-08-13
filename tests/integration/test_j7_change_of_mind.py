"""`J7` — a person changes their mind, and the project changes with them.

From `END_TO_END_JOURNEYS.md`, verbatim:

> **J7 — Change of mind.** User reverses or materially modifies an earlier
> requirement. Pass when affected knowledge can be corrected/superseded,
> conflicts and downstream impact become visible, and **old material does not
> remain silently authoritative in the next package**.

`J1`–`J10` have had no recorded run, date or verdict since they were written.
Most need the deployed stack and a credential this loop does not hold. This one
is entirely inside KAE-Memory, so it runs against an ordinary test database.

## Why this journey rather than a unit test of `supersede_knowledge`

`D-34` made a superseded statement visible in Studio; `D-35` kept one out of a
development package. Both were reasoned from reading code, and both are guarded
by tests that assert what the code was written to do. That is a different
question from whether **a person who changes their mind ends up with a project
that agrees with them**, which is what a journey asks and what the inventory
means by *"every significant defect this estate has found was found by using the
product or by writing a journey, not by a suite."*

## The three clauses, kept apart

The journey's pass condition is a conjunction and each half is asserted on its
own, because they fail independently:

1. the correction **can be made** — superseding is reachable and does not
   require deleting the original;
2. the change is **visible** — the retired statement stays readable as a
   decision, with what replaced it, so a later reader can tell *"we changed our
   mind"* from *"nobody ever said this"*;
3. the old material is **not silently authoritative** — it stops counting toward
   readiness and does not appear in an assembled package.

The third is the one with teeth. A system that hides the old statement passes
(3) and fails (2); one that keeps it in the corpus passes (2) and fails (3).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyPurpose, AssemblyService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.relationships import KnowledgeRelation
from kae_memory.domain.workspace import ActorType, SessionType

#: What the person said first, and confirmed.
ORIGINALLY = "Reports are published to the national board as soon as they are approved."

#: What they say later. A material change, not a rewording — publication now
#: waits for something, which is the kind of reversal that invalidates work
#: already done against it.
INSTEAD = "Reports are published to the national board only after a scheduled monthly release."

#: An unrelated statement, to prove the correction is surgical. A change of mind
#: that quietly retires a neighbouring statement is worse than one that fails.
UNTOUCHED = "Every report names the church that submitted it."


@pytest.fixture
def changed_mind(factory: sessionmaker[Session]) -> dict[str, Any]:
    """A project where somebody settled a rule and then reversed it."""

    ReadinessService(factory).install_template()
    memory = MemoryService(factory)

    project = ProjectId(str(memory.create_project("Ministry reporting").id))
    session = memory.open_session(project, SessionType.DISCOVERY)
    memory.record_message(
        project,
        session.id,
        "Approved reports go straight to the national board.",
        ActorType.USER,
        idempotency_key="j7-first-turn",
    )

    run = memory.start_run(project, AgentRole.REQUIREMENTS, "j7-extraction")
    written = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(KnowledgeKind.RULE.value, ORIGINALLY, "interview"),
            WriteKnowledgeRequest(KnowledgeKind.RULE.value, UNTOUCHED, "interview"),
        ],
    )
    by_text = {item.current_version.content: item for item in written}

    # Confirmed, so the reversal is a change of mind rather than a discarded
    # candidate. Rejecting a proposal is `J2`; this journey is about reversing
    # something the project had settled.
    memory.confirm_knowledge(by_text[ORIGINALLY].id)
    memory.confirm_knowledge(by_text[UNTOUCHED].id)

    readiness = ReadinessService(factory)
    for content in (ORIGINALLY, UNTOUCHED):
        readiness.assign_area(project, by_text[content].id, "domain_model_and_data")

    return {
        "project": project,
        "run_id": run.id,
        "original": by_text[ORIGINALLY].id,
        "untouched": by_text[UNTOUCHED].id,
    }


def _find(factory: sessionmaker[Session], changed_mind: dict[str, Any], text: str) -> Any:
    """One statement, read back through the ordinary listing.

    By text rather than by identifier, and with no lifecycle filter — the
    journey is about what a later reader finds, and a helper that fetched by id
    would prove the row exists without proving it is reachable.
    """

    memory = MemoryService(factory)
    for item in memory.retrieve_knowledge(changed_mind["project"], lifecycle=None):
        if item.current_version.content == text:
            return item
    raise AssertionError(f"no statement reads {text!r}")


def _relationships(factory: sessionmaker[Session], project: ProjectId) -> Any:
    from kae_memory.persistence.readiness_repositories import RelationshipRepository

    with factory() as db_session:
        return RelationshipRepository(db_session).list_for_project(project)


def _supersede(factory: sessionmaker[Session], changed_mind: dict[str, Any]) -> Any:
    """The reversal itself: a new statement replaces the settled one."""

    memory = MemoryService(factory)
    # A later run, because a run completes when it writes — and because a change
    # of mind happens in a later turn, which is what the journey describes.
    later = memory.start_run(changed_mind["project"], AgentRole.REQUIREMENTS, "j7-correction")
    replacement = memory.write_knowledge(
        later.id,
        [WriteKnowledgeRequest(KnowledgeKind.RULE.value, INSTEAD, "interview")],
    )[0]
    memory.confirm_knowledge(replacement.id)
    memory.supersede_knowledge(changed_mind["original"], replacement.id)
    ReadinessService(factory).assign_area(
        changed_mind["project"], replacement.id, "domain_model_and_data"
    )
    return replacement


class TestTheCorrectionCanBeMade:
    """Clause one. A reversal that requires deleting the original is not a
    change of mind, it is an erasure — and the project loses the fact that it
    ever believed something else."""

    def test_a_settled_statement_can_be_superseded(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        _supersede(factory, changed_mind)

        # Read back by text through the ordinary listing, not by the identifier
        # the helper returned — the journey asks what a later reader finds.
        assert _find(factory, changed_mind, INSTEAD).lifecycle is LifecycleState.VALIDATED

    def test_the_original_is_still_there(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        _supersede(factory, changed_mind)

        original = _find(factory, changed_mind, ORIGINALLY)

        assert original is not None
        assert original.current_version.content == ORIGINALLY


class TestTheChangeIsVisible:
    """Clause two. A later reader must be able to tell *we changed our mind*
    from *nobody ever said this* — and the second is what an erasure leaves
    behind."""

    def test_the_retired_statement_reads_as_a_decision(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        _supersede(factory, changed_mind)

        original = _find(factory, changed_mind, ORIGINALLY)

        # `superseded`, not `rejected`. One says *this was replaced*, the other
        # says *this was wrong*, and a project that conflates them loses the
        # reason it changed course.
        assert original.lifecycle is LifecycleState.SUPERSEDED

    def test_a_reader_following_the_old_statement_arrives_somewhere(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        """The edge is the whole point of superseding rather than rejecting.

        `supersede_knowledge`'s own docstring: *"the edge records what replaced
        it, so a reader who follows an old reference arrives somewhere rather
        than nowhere."*
        """

        replacement = _supersede(factory, changed_mind)

        edges = _relationships(factory, changed_mind["project"])
        supersedes = [edge for edge in edges if edge.type is KnowledgeRelation.SUPERSEDES]

        assert [(e.source_id, e.target_id) for e in supersedes] == [
            (replacement.id, changed_mind["original"])
        ]


class TestTheOldMaterialIsNotSilentlyAuthoritative:
    """Clause three, and the one with teeth.

    A system that hides the old statement passes clause three and fails clause
    two; one that leaves it in the corpus passes two and fails three. Both
    halves have to hold at once.
    """

    def test_it_does_not_reach_an_assembled_package(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        """*"Old material does not remain silently authoritative in the next
        package"* — the journey's own words, and the clause a coding agent
        depends on."""

        _supersede(factory, changed_mind)

        assembly = AssemblyService(factory)
        assembled = assembly.assemble(changed_mind["project"], AssemblyPurpose.IMPLEMENTATION)
        texts = [
            statement.text for section in assembled.sections for statement in section.statements
        ]

        assert ORIGINALLY not in texts

    def test_what_replaced_it_does(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        # Otherwise the reversal has simply deleted a rule, and the package
        # describes a project that has said nothing about publication at all.
        _supersede(factory, changed_mind)

        assembly = AssemblyService(factory)
        assembled = assembly.assemble(changed_mind["project"], AssemblyPurpose.IMPLEMENTATION)
        texts = [
            statement.text for section in assembled.sections for statement in section.statements
        ]

        assert INSTEAD in texts

    def test_it_stops_counting_toward_readiness(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        """A retired statement that still counts is coverage the project does
        not have, which is the quietest way for a number to become wrong."""

        readiness = ReadinessService(factory)
        before = readiness.calculate(changed_mind["project"])
        confirmed_before = sum(area.confirmed_count for area in before.areas)

        _supersede(factory, changed_mind)

        after = readiness.calculate(changed_mind["project"])
        confirmed_after = sum(area.confirmed_count for area in after.areas)

        # One retired, one added: the count holds steady rather than growing,
        # which is what it would do if the superseded statement still counted.
        assert confirmed_after == confirmed_before

    def test_the_neighbouring_statement_is_untouched(
        self, factory: sessionmaker[Session], changed_mind: dict[str, Any]
    ) -> None:
        # A change of mind that quietly retires a neighbouring statement is
        # worse than one that fails outright, because nobody is looking there.
        _supersede(factory, changed_mind)

        assert _find(factory, changed_mind, UNTOUCHED).lifecycle is LifecycleState.VALIDATED
