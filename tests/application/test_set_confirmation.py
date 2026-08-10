"""Confirming a reading, not a row.

A conversation synthesises nine statements into one sentence and asks whether it
holds. The answer is a single yes. With only per-item confirmation there was
nothing for that yes to act on, so an interviewer wrote "Confirmed" while the
panel beside it read "Problem and value proposition — missing · 0 of 1
confirmed". Both were correct. They were describing different things with the
same word, and the word belongs to the panel.

The set is the turn's provenance — the items the synthesis was drawn from — so
agreement lands on what was actually shown rather than on whatever is proposed
at the moment the click arrives.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, Project

STATEMENTS = [
    ("goal", "People cannot move a project forward when their thinking is scattered."),
    ("actor", "Individual founders are the first users."),
    ("requirement", "The system must record what a person confirmed."),
]


def _seed(memory: MemoryService, name: str, key: str) -> tuple[Project, list[KnowledgeItem]]:
    project = memory.create_project(name, key=key)
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, f"{key}-seed")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in STATEMENTS
        ],
    )
    return project, list(items)


def test_one_act_confirms_every_statement_a_synthesis_drew_on(
    factory: sessionmaker[Session],
) -> None:
    memory = MemoryService(factory)
    project, items = _seed(memory, "Synthesis", "set-confirm-basic")

    confirmed = memory.confirm_knowledge_set(project.id, [item.id for item in items])

    assert len(confirmed) == len(items)
    assert all(item.lifecycle is LifecycleState.VALIDATED for item in confirmed)
    assert not memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)


def test_the_revision_moves_once_because_one_thing_happened(
    factory: sessionmaker[Session],
) -> None:
    """A caller comparing revisions to detect movement should not see three.

    The revision means "this project's knowledge changed". One act changed it
    once, however many rows it touched.
    """

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project, items = _seed(memory, "Revisions", "set-confirm-revision")

    before = readiness.knowledge_revision(project.id)
    memory.confirm_knowledge_set(project.id, [item.id for item in items])
    after = readiness.knowledge_revision(project.id)

    assert after == before + 1


def test_an_unknown_item_confirms_nothing_at_all(factory: sessionmaker[Session]) -> None:
    """All or nothing.

    A partial confirmation would leave a person believing they agreed to a
    reading while part of what composed it stayed proposed — and no surface
    distinguishes "you confirmed two of three" from "you confirmed it".
    """

    memory = MemoryService(factory)
    project, items = _seed(memory, "Partial", "set-confirm-partial")

    with pytest.raises(LookupError):
        memory.confirm_knowledge_set(
            project.id,
            [items[0].id, KnowledgeItemId("00000000-0000-0000-0000-000000000000")],
        )

    still_proposed = memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)
    assert len(still_proposed) == len(items), "the first item must not have been confirmed alone"


def test_an_item_from_another_project_is_refused_not_skipped(
    factory: sessionmaker[Session],
) -> None:
    """A set assembled against the wrong project is a caller defect.

    Silently confirming the subset that happens to match would hide it, and the
    caller would carry on building sets the same wrong way.
    """

    memory = MemoryService(factory)
    mine, my_items = _seed(memory, "Mine", "set-confirm-mine")
    _theirs, their_items = _seed(memory, "Theirs", "set-confirm-theirs")

    with pytest.raises(LookupError, match="another project"):
        memory.confirm_knowledge_set(mine.id, [my_items[0].id, their_items[0].id])


def test_reconfirming_an_overlapping_set_is_ordinary(factory: sessionmaker[Session]) -> None:
    """Two syntheses can legitimately share a statement.

    A caller forced to diff the sets first would be doing the work this exists
    to remove.
    """

    memory = MemoryService(factory)
    project, items = _seed(memory, "Overlap", "set-confirm-overlap")

    memory.confirm_knowledge_set(project.id, [items[0].id, items[1].id])
    again = memory.confirm_knowledge_set(project.id, [items[1].id, items[2].id])

    assert len(again) == 2
    assert all(item.lifecycle is LifecycleState.VALIDATED for item in again)


def test_a_repeated_id_confirms_one_item_not_two(factory: sessionmaker[Session]) -> None:
    memory = MemoryService(factory)
    project, items = _seed(memory, "Duplicates", "set-confirm-duplicates")

    confirmed = memory.confirm_knowledge_set(project.id, [items[0].id, items[0].id])

    assert len(confirmed) == 1


def test_an_empty_set_changes_nothing(factory: sessionmaker[Session]) -> None:
    """Not an error at the service, and not a revision bump either.

    The HTTP surface refuses it, because there an empty set means a caller lost
    track of what it was asking about. Here it is simply a no-op, so a caller
    that filtered its own list to nothing does not have to special-case it.
    """

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project, _items = _seed(memory, "Empty", "set-confirm-empty")

    before = readiness.knowledge_revision(project.id)
    assert memory.confirm_knowledge_set(project.id, []) == ()
    assert readiness.knowledge_revision(project.id) == before


def test_confirmation_moves_readiness_the_way_a_person_would_expect(
    factory: sessionmaker[Session],
) -> None:
    """The end the whole mechanism serves.

    Readiness counts confirmed knowledge per area, so this is the step between
    "the conversation went well" and the product saying so.
    """

    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    project, items = _seed(memory, "Moving", "set-confirm-readiness")
    for item in items:
        if item.kind == "actor":
            readiness.assign_area(project.id, item.id, "users_and_stakeholders")

    before = readiness.calculate(project.id)
    memory.confirm_knowledge_set(project.id, [item.id for item in items])
    after = readiness.calculate(project.id)

    assert after.score > before.score
