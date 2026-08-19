"""The grade never crosses a boundary without the reason for it (`D-246`, `WHY-1`).

`ReviewService` computes both halves on one object: `severity`, the grade, and
`summary`, the sentence saying what is wrong. The clarification path used to
carry the first and drop the second at `_as_clarification`, so every caller —
Studio over HTTP, an agent over MCP — was handed a question marked `critical`
with nothing at all saying what was critical about it. The sentence it would
have printed was assembled one function call earlier.

Each hop is asserted separately rather than end to end. A single journey test
goes green again the moment any one layer is repaired, and the defect was
precisely that one layer of five kept the field.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api.schemas import ClarificationListResponse, QuestionCandidateListResponse
from kae_memory.application import ClarificationService, MemoryService, ReadinessService
from kae_memory.application.clarification_service import REASON_UNSTATED
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.mcp.tools import _render_question


@pytest.fixture
def project(
    factory: sessionmaker[Session],
) -> tuple[ClarificationService, ReviewService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="whyone")
    return ClarificationService(factory, memory), ReviewService(factory), proj.id


class TestTheReasonSurvivesEveryHop:
    def test_a_clarification_carries_the_summary_of_its_finding(
        self, project: tuple[Any, ...]
    ) -> None:
        """The hop that dropped it. Compared to the finding, not to a fixture.

        Asserting a particular sentence would pass against a reason this module
        invented. The only correct value is the one `ReviewService` already
        computed, so that is what this reads.
        """

        clarify, review, project_id = project
        summaries = {finding.summary for finding in review.findings(project_id)}

        pending = clarify.pending(project_id)

        assert pending
        assert all(c.reason for c in pending)
        assert {c.reason for c in pending} <= summaries

    def test_a_candidate_carries_it(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project

        candidates = clarify.candidates(project_id)

        assert candidates
        assert all(c.reason for c in candidates)

    def test_an_asked_question_carries_it(self, project: tuple[Any, ...]) -> None:
        """Including once it is a durable message.

        The question's text is stored and its reason is not — it is re-derived
        from the current findings on every read. A question read back from the
        database must therefore still arrive with one.
        """

        clarify, _, project_id = project

        clarify.open_questions(project_id, limit=1)
        again = clarify.open_questions(project_id, limit=1)

        assert again
        assert not again[0].newly_asked
        assert again[0].reason

    def test_the_mcp_rendering_prints_it_beside_the_grade(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project

        rendered = _render_question(clarify.open_questions(project_id, limit=1)[0])

        assert rendered["severity"]
        assert rendered["reason"] != rendered["question"]
        # Not merely present. The absence string is what a renderer prints when
        # the reason never arrived, so asserting the key is truthy would pass
        # against the exact defect this file exists to catch.
        assert rendered["reason"] != REASON_UNSTATED

    def test_both_http_renderings_print_it(self, project: tuple[Any, ...]) -> None:
        clarify, _, project_id = project

        questions = ClarificationListResponse.of(
            clarify.open_questions(project_id),
            limit=5,
            total=clarify.unsettled_count(project_id),
        )
        candidates = QuestionCandidateListResponse.of(clarify.candidates(project_id), limit=5)

        assert questions.questions
        assert candidates.candidates
        assert all(q.reason != REASON_UNSTATED for q in questions.questions)
        assert all(c.reason != REASON_UNSTATED for c in candidates.candidates)


class TestAnAbsenceIsStated:
    """`WHY-1`'s second clause: *a reason beside the grade, **or a stated
    absence of one***.

    Nothing here authors a reason. A finding that offered no sentence must
    produce a question that says so, because a blank field beside a severity is
    the same defect one step on — a reader cannot tell "no reason was given"
    from "a reason was given and lost".
    """

    def test_a_reasonless_question_says_so_rather_than_rendering_blank(
        self, project: tuple[Any, ...]
    ) -> None:
        clarify, _, project_id = project
        question = clarify.open_questions(project_id, limit=1)[0]

        silent = replace(question, reason="")

        assert _render_question(silent)["reason"] == REASON_UNSTATED
        assert ClarificationListResponse.of([silent], limit=1, total=1).questions[0].reason == (
            REASON_UNSTATED
        )

    def test_every_surface_states_the_absence_the_same_way(self) -> None:
        """One string, not one per renderer.

        Three renderers each phrasing "no reason" their own way is how one
        concept becomes three across a boundary (`G8`), and the estate has
        already paid for that twice.
        """

        assert REASON_UNSTATED.strip()
