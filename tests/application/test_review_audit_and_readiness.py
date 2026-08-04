"""Phase C verification: the audit trail and readiness under review (T15).

Verification rather than new behaviour. T12 to T14 built the review surface;
these check that the record it leaves is trustworthy and that readiness follows
the lifecycle rules the repository already had, rather than assuming either.

The failure worth catching here is a system that looks correct in each part and
lies in aggregate: an audit trail missing the decision that mattered, a
readiness figure counting knowledge nobody accepted, or a retry that moves a
number twice.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService, evaluate_area
from kae_memory.domain.errors import StaleVersionError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.knowledge_review import RejectionReason, ReviewAction
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind
from kae_memory.domain.readiness import AreaState
from kae_memory.domain.workspace import ActorType

VALID = "Only an authorised approver may approve a report."
INVALID = "The service publishes reports over SNS."
INACCURATE = "Reports are filed quarterly."
CORRECTED = "Reports are filed monthly."

AREA = "problem_and_value"
"""Chosen because it needs one confirmed item, not three.

`functional_requirements` requires three, which would make these tests measure
the counting rule rather than the lifecycle rule. The count is real behaviour
and covered elsewhere; here it would only obscure what is being checked.
"""


def _write(
    memory: MemoryService,
    project_id: ProjectId,
    key: str,
    content: str,
    kind: str = "goal",
) -> KnowledgeItem:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    return memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind=kind, content=content, source="interview")]
    )[0]


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, ReadinessService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    return memory, readiness, memory.create_project("Ministry Reporting", key="t15").id


class TestAuditCoverage:
    """Every decision leaves exactly one attributable record."""

    def test_each_action_is_recorded_under_its_own_name(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        """A generic "updated" event would lose the distinction that matters."""

        memory, _, project_id = project
        confirmed = _write(memory, project_id, "a1", VALID)
        rejected = _write(memory, project_id, "a2", INVALID)
        corrected = _write(memory, project_id, "a3", INACCURATE)

        memory.review_confirm(project_id, confirmed.id, expected_version=1, actor_id="cris")
        memory.review_reject(
            project_id,
            rejected.id,
            expected_version=1,
            reason_code=RejectionReason.INCORRECT,
            actor_id="cris",
        )
        memory.review_correct(
            project_id, corrected.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )

        actions = {
            str(item.id): memory.review_history(project_id, item.id)[-1].action
            for item in (confirmed, rejected, corrected)
        }
        assert actions[str(confirmed.id)] is ReviewAction.VALIDATED
        assert actions[str(rejected.id)] is ReviewAction.REJECTED
        assert actions[str(corrected.id)] is ReviewAction.CORRECTED

    def test_every_event_is_fully_attributable(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "a4", VALID)

        memory.review_confirm(project_id, item.id, expected_version=1, actor_id="cris")

        event = memory.review_history(project_id, item.id)[0]
        assert event.project_id == project_id
        assert event.knowledge_item_id == item.id
        assert event.version_number == 1
        assert event.actor_type is ActorType.USER
        assert event.actor_id == "cris"
        assert event.created_at.tzinfo is not None
        assert event.from_lifecycle is LifecycleState.PROPOSED
        assert event.to_lifecycle is LifecycleState.VALIDATED

    def test_a_correction_names_the_version_it_replaced(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "a5", INACCURATE)

        memory.review_correct(
            project_id, item.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )

        event = memory.review_history(project_id, item.id)[-1]
        assert event.from_version_number == 1
        assert event.version_number == 2

    def test_history_is_ordered_and_accumulates(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        """Two decisions on one item: the correction, then the confirmation of it."""

        memory, _, project_id = project
        item = _write(memory, project_id, "a6", INACCURATE)
        memory.confirm_knowledge(item.id)

        memory.review_correct(
            project_id, item.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )
        memory.review_confirm(project_id, item.id, expected_version=2, actor_id="cris")

        history = memory.review_history(project_id, item.id)
        assert [event.action for event in history] == [
            ReviewAction.CORRECTED,
            ReviewAction.VALIDATED,
        ]

    def test_a_stale_decision_writes_nothing(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "a7", INACCURATE)
        memory.review_correct(
            project_id, item.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )
        before = len(memory.review_history(project_id, item.id))

        with pytest.raises(StaleVersionError):
            memory.review_confirm(project_id, item.id, expected_version=1)

        assert len(memory.review_history(project_id, item.id)) == before

    def test_a_replay_does_not_add_a_second_event(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "a8", VALID)

        memory.review_confirm(project_id, item.id, expected_version=1, idempotency_key="k")
        memory.review_confirm(project_id, item.id, expected_version=1, idempotency_key="k")

        assert len(memory.review_history(project_id, item.id)) == 1

    def test_the_log_is_project_scoped(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        mine = _write(memory, project_id, "a9", VALID)
        other = memory.create_project("Other", key="t15-other")
        theirs = _write(memory, other.id, "a10", INVALID)
        memory.review_confirm(project_id, mine.id, expected_version=1)
        memory.review_confirm(other.id, theirs.id, expected_version=1)

        assert len(memory.review_history(project_id, mine.id)) == 1
        assert len(memory.review_history(other.id, theirs.id)) == 1


class TestReadinessFollowsLifecycle:
    """The rules already in `evaluate_area`, verified rather than assumed."""

    def _area_state(
        self, memory: MemoryService, project_id: ProjectId, items: list[KnowledgeItem]
    ) -> AreaState:
        """Evaluate the area over the current state of ``items``.

        Re-read rather than reusing the objects the test holds: those are
        snapshots from before the decision, and asserting against them would
        pass whatever the review did.
        """

        wanted = {str(item.id) for item in items}
        current = [
            held
            for held in memory.retrieve_knowledge(project_id, lifecycle=None)
            if str(held.id) in wanted
        ]
        definition = next(area for area in _template().areas if area.key == AREA)
        return evaluate_area(definition, current, frozenset()).state

    def test_confirmation_makes_an_area_sufficient(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "r1", VALID)
        assert self._area_state(memory, project_id, [item]) is AreaState.PARTIAL

        memory.review_confirm(project_id, item.id, expected_version=1)

        assert self._area_state(memory, project_id, [item]) is AreaState.SUFFICIENT

    def test_rejected_knowledge_contributes_nothing(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "r2", INVALID)

        memory.review_reject(
            project_id, item.id, expected_version=1, reason_code=RejectionReason.INCORRECT
        )

        assert self._area_state(memory, project_id, [item]) is AreaState.MISSING

    def test_correcting_a_proposal_earns_full_coverage(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        """The reviewer wrote the wording, so the corrected form is confirmed."""

        memory, _, project_id = project
        item = _write(memory, project_id, "r3", INACCURATE)

        memory.review_correct(
            project_id, item.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )

        assert self._area_state(memory, project_id, [item]) is AreaState.SUFFICIENT

    def test_correcting_confirmed_knowledge_reduces_coverage(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        """The confirmation covered the previous wording, so the area falls back."""

        memory, _, project_id = project
        item = _write(memory, project_id, "r4", INACCURATE)
        memory.review_confirm(project_id, item.id, expected_version=1)
        assert self._area_state(memory, project_id, [item]) is AreaState.SUFFICIENT

        memory.review_correct(
            project_id, item.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )

        assert self._area_state(memory, project_id, [item]) is AreaState.PARTIAL

    def test_a_superseded_item_stops_counting(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        old = _write(memory, project_id, "r5", INACCURATE)
        memory.confirm_knowledge(old.id)
        new = _write(memory, project_id, "r6", CORRECTED)
        memory.supersede_knowledge(old.id, new.id)

        assert self._area_state(memory, project_id, [old]) is AreaState.MISSING


class TestRevisionInvalidation:
    """Readiness is invalidated by revision, not recalculated in the mutation."""

    def test_each_decision_advances_the_revision(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, readiness, project_id = project
        item = _write(memory, project_id, "v1", VALID)
        before = readiness.knowledge_revision(project_id)

        memory.review_confirm(project_id, item.id, expected_version=1)

        assert readiness.knowledge_revision(project_id) > before

    def test_a_replay_does_not_advance_it_twice(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        """Otherwise a retried confirmation would look like a second change."""

        memory, readiness, project_id = project
        item = _write(memory, project_id, "v2", VALID)
        memory.review_confirm(project_id, item.id, expected_version=1, idempotency_key="k")
        after_first = readiness.knowledge_revision(project_id)

        memory.review_confirm(project_id, item.id, expected_version=1, idempotency_key="k")

        assert readiness.knowledge_revision(project_id) == after_first

    def test_a_refused_decision_does_not_advance_it(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, readiness, project_id = project
        item = _write(memory, project_id, "v3", VALID)
        memory.review_correct(
            project_id, item.id, expected_version=1, content=CORRECTED, actor_id="cris"
        )
        before = readiness.knowledge_revision(project_id)

        with pytest.raises(StaleVersionError):
            memory.review_confirm(project_id, item.id, expected_version=1)

        assert readiness.knowledge_revision(project_id) == before

    def test_another_project_is_unaffected(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, readiness, project_id = project
        item = _write(memory, project_id, "v4", VALID)
        other = memory.create_project("Other", key="t15-other-rev")
        before = readiness.knowledge_revision(other.id)

        memory.review_confirm(project_id, item.id, expected_version=1)

        assert readiness.knowledge_revision(other.id) == before


class TestClassificationIsNotCorrectable:
    """A documented limitation, asserted so it cannot be assumed away.

    The Phase C direction expected a correction to be able to move knowledge
    between readiness areas. It cannot: readiness resolves an item through its
    area link and its ``kind``, and correction changes only content. Recording
    this as a test keeps the report honest and gives a later reclassification
    feature something to overturn deliberately.
    """

    def test_correction_does_not_change_the_knowledge_kind(
        self, project: tuple[MemoryService, ReadinessService, ProjectId]
    ) -> None:
        memory, _, project_id = project
        item = _write(memory, project_id, "c1", INACCURATE, kind=KnowledgeKind.REQUIREMENT.value)

        outcome = memory.review_correct(
            project_id,
            item.id,
            expected_version=1,
            content="The deployment runs on ECS.",
            actor_id="cris",
        )

        assert outcome.item.kind == KnowledgeKind.REQUIREMENT.value


def _template():
    from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

    return SOFTWARE_TEMPLATE
