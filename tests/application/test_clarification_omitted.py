"""What a bounded page of questions says about the questions it did not show.

Two doors carry this number and both were wrong, in opposite directions.

`POST /clarifications` computed `total` from the page it was handed, so
`omitted` was `max(0, len(page) - len(page))` — **zero on every call ever
made** — under a docstring saying the field means *"work you have not seen"*
(`D-281`).

`kae_get_open_clarifications` counted `pending()`, every derived clarification
unfiltered by disposition, while the list beside it drops settled questions and
holds deferred ones back. A project whose questions had all been answered
reported a queue still full of work.

Counting by materialising is what neither may do: `open_questions` breaks out
of its loop at the limit for a recorded reason — *"a caller asking for one
question put ten to the person and displayed the first"* — so counting that way
would ask people questions in order to count them. `unsettled_count` delegates
to `candidates`, which walks the same clarifications and writes nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api.schemas import ClarificationListResponse
from kae_memory.application import ClarificationService, MemoryService, ReadinessService
from kae_memory.domain.identifiers import ProjectId


@pytest.fixture
def project(
    factory: sessionmaker[Session],
) -> tuple[ClarificationService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="omitted")
    return ClarificationService(factory, memory), proj.id


class TestABoundedPageSaysWhatItLeftOut:
    def test_a_page_smaller_than_the_queue_reports_the_rest(self, project: tuple[Any, ...]) -> None:
        """The HTTP direction. `omitted` was zero here on every call ever made.

        The limit is derived from the queue rather than hardcoded, so this
        cannot pass by the fixture happening to produce the right number of
        findings.
        """

        clarify, project_id = project
        owed = clarify.unsettled_count(project_id)
        assert owed > 1, "the fixture must produce a queue worth truncating"

        limit = owed - 1
        page = clarify.open_questions(project_id, limit=limit)
        response = ClarificationListResponse.of(
            page, limit=limit, total=clarify.unsettled_count(project_id)
        )

        assert len(response.questions) == limit
        assert response.total == owed
        assert response.omitted == owed - limit

    def test_a_queue_that_fits_reports_nothing_omitted(self, project: tuple[Any, ...]) -> None:
        """The control. A field that always reports work left over is as
        useless as one that never does, and would pass the assertion above."""

        clarify, project_id = project
        owed = clarify.unsettled_count(project_id)

        page = clarify.open_questions(project_id, limit=owed + 5)
        response = ClarificationListResponse.of(
            page, limit=owed + 5, total=clarify.unsettled_count(project_id)
        )

        assert response.total == owed
        assert response.omitted == 0


class TestWhatIsOwedIsNotWhatIsDerived:
    def test_an_answered_question_stops_being_owed(self, project: tuple[Any, ...]) -> None:
        """The MCP direction, which reported a full queue on a settled project.

        `pending()` is asserted to stay put in the same test, because the
        distinction is the whole finding: the clarifications are still derived,
        and what changed is that they are no longer owed.
        """

        clarify, project_id = project
        questions = clarify.open_questions(project_id)
        derived = len(clarify.pending(project_id))
        assert questions and derived

        for question in questions:
            clarify.answer(project_id, question.id, "settled", actor_id="tester")

        assert clarify.unsettled_count(project_id) == 0
        assert len(clarify.pending(project_id)) == derived


class TestCountingAsksNobodyAnything:
    def test_the_count_does_not_move_when_questions_are_materialised(
        self, project: tuple[Any, ...]
    ) -> None:
        """The claim the route's ordering rests on, asserted rather than argued.

        A clarification nobody has asked reads as open because there is no
        message; after materialising it reads as open because the new message
        carries no answer. So the total is the same computed either side of the
        call, and the route is free to compute it after.
        """

        clarify, project_id = project

        before = clarify.unsettled_count(project_id)
        clarify.open_questions(project_id)
        after = clarify.unsettled_count(project_id)

        assert before == after

    def test_counting_materialises_nothing(self, project: tuple[Any, ...]) -> None:
        """The reason this is not `len(open_questions(...))`.

        Counting through the materialising path would put every question in the
        queue to a person as a side effect of asking how many there are.
        """

        clarify, project_id = project

        assert clarify.unsettled_count(project_id) > 0

        # `asked_id` is the id of the message that put the question to somebody,
        # read back rather than created. `None` on every candidate is the only
        # available statement that nobody has been asked anything.
        assert all(c.asked_id is None for c in clarify.candidates(project_id))
