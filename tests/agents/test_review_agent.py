"""The Review Agent — the role that reports and never corrects.

Two guarantees carry the whole design. It writes no knowledge, so nothing it
says can become a project fact without a human confirming it. And every finding
must quote a statement in the reviewed set, so a reviewer cannot comment on a
statement it never read.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import (
    DeterministicReviewAdapter,
    ReviewAgent,
    ReviewedStatement,
    ReviewRequest,
    UnverifiableReviewError,
)
from kae_memory.agents.review import (
    InvalidReviewOutputError,
    ReviewFindingKind,
    resolve,
)
from kae_memory.agents.review_adapter import offline_review_fixture
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, Project

CONFLICTING = [
    ("rule", "A submitter can approve their own report."),
    ("rule", "A submitter cannot approve their own report."),
]

CLASSIFIABLE = [
    ("goal", "Every published report has an identifiable approver."),
    ("actor", "Ministry leaders submit monthly reports."),
    ("requirement", "Only an authorised approver may approve a report."),
]


@pytest.fixture
def services(factory: sessionmaker[Session]) -> tuple[MemoryService, ReadinessService]:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return MemoryService(factory), readiness


def _seed(
    memory: MemoryService, texts: list[tuple[str, str]], key: str, confirm: bool = True
) -> tuple[Project, tuple[KnowledgeItem, ...]]:
    project = memory.create_project("Ministry Reporting", key=key)
    run = memory.start_run(project.id, AgentRole.REQUIREMENTS, f"seed-{key}")
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in texts
        ],
    )
    if confirm:
        for item in items:
            memory.confirm_knowledge(item.id)
    return project, items


def _agent(
    services: tuple[MemoryService, ReadinessService], fixtures: object = None
) -> ReviewAgent:
    memory, readiness = services
    reviewer = DeterministicReviewAdapter(fixtures)  # type: ignore[arg-type]
    return ReviewAgent(memory, readiness, reviewer)


class TestItWritesNoKnowledge:
    def test_review_adds_no_statements(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """The reviewer reports. Anything else would make it an author."""

        memory, _ = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-nowrite")
        before = len(memory.retrieve_knowledge(project.id, lifecycle=None))

        _agent(services).run_on_confirmed_knowledge(project.id, None, "review-1")

        assert len(memory.retrieve_knowledge(project.id, lifecycle=None)) == before

    def test_review_confirms_nothing(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Confirmation is a human act, and a reviewer is not one."""

        memory, _ = services
        project, items = _seed(memory, CLASSIFIABLE, "rev-noconfirm", confirm=False)
        for item in items[:1]:
            memory.confirm_knowledge(item.id)

        _agent(services).run_on_confirmed_knowledge(project.id, None, "review-2")

        proposed = memory.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)
        assert len(proposed) == len(items) - 1

    def test_unconfirmed_knowledge_is_not_reviewed(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """A conflict between two unconfirmed guesses is not a project fact."""

        memory, _ = services
        project, _ = _seed(memory, CONFLICTING, "rev-unconfirmed", confirm=False)

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-3")

        assert outcome.contradictions == ()
        assert outcome.run.output_summary["reason"] == "no_confirmed_knowledge"


class TestContradictionDetection:
    def test_an_opposed_pair_is_recorded(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """The capability that did not exist: detection, not just recording."""

        memory, readiness = services
        project, _ = _seed(memory, CONFLICTING, "rev-contra")

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-4")

        assert len(outcome.contradictions) == 1
        findings = {f.kind.value for f in readiness_findings(readiness, project.id)}
        assert "unresolved_contradiction" in findings

    def test_agreeing_statements_are_left_alone(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """A reviewer that finds conflict everywhere reports nothing useful."""

        memory, _ = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-nocontra")

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-5")

        assert outcome.contradictions == ()

    def test_readiness_sees_the_contradiction(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Detection is worthless if the calculation never learns of it."""

        memory, readiness = services
        project, _ = _seed(memory, CONFLICTING, "rev-contra-readiness")

        _agent(services).run_on_confirmed_knowledge(project.id, None, "review-6")
        snapshot = readiness.calculate(project.id)

        assert any(area.contradicted for area in snapshot.areas) or any(
            f.kind.value == "unresolved_contradiction"
            for f in readiness_findings(readiness, project.id)
        )


class TestAreaClassification:
    def test_statements_are_assigned_to_areas(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        memory, readiness = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-areas")

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-7")

        assert len(outcome.area_assignments) == len(CLASSIFIABLE)
        assert len(readiness.area_links(project.id)) == len(CLASSIFIABLE)

    def test_assignment_records_the_run_that_made_it(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """An agent's classification must be attributable and reversible."""

        memory, readiness = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-attrib")

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-8")

        links = readiness.area_links(project.id)
        assert all(link.assigned_by_agent_run_id == outcome.run.id for link in links)

    def test_classification_raises_readiness_it_did_not_decide(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Classification proposes; calculation decides.

        The agent never writes a percentage. Coverage moves only because the
        deterministic calculator re-reads the links it created.
        """

        memory, readiness = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-readiness")
        before = readiness.calculate(project.id).percentage

        _agent(services).run_on_confirmed_knowledge(project.id, None, "review-9")

        assert readiness.calculate(project.id).percentage > before

    def test_an_existing_assignment_is_never_overruled(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """A later review must not silently reclassify a human's decision."""

        memory, readiness = services
        project, items = _seed(memory, CLASSIFIABLE, "rev-nooverrule")
        readiness.assign_area(project.id, items[2].id, "quality_attributes")

        _agent(services).run_on_confirmed_knowledge(project.id, None, "review-10")

        links = {link.knowledge_item_id: link.area_key for link in readiness.area_links(project.id)}
        assert links[items[2].id] == "quality_attributes"

    def test_an_impossible_pairing_is_dropped_not_fatal(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """An area only counts kinds it declares.

        A reviewer proposing an impossible pairing has made one bad call, not an
        invalid review. Failing the run would discard the findings that were
        fine — including contradictions already recorded.
        """

        memory, _ = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-impossible")

        def misfiles(request: ReviewRequest) -> object:
            goal = next(s for s in request.statements if s.kind == "goal")
            requirement = next(s for s in request.statements if s.kind == "requirement")
            return {
                "findings": [
                    {
                        "kind": "area_classification",
                        "statement_quote": goal.text,
                        "area_key": "quality_attributes",
                    },
                    {
                        "kind": "area_classification",
                        "statement_quote": requirement.text,
                        "area_key": "functional_requirements",
                    },
                ]
            }

        outcome = _agent(services, misfiles).run_on_confirmed_knowledge(
            project.id, None, "review-14"
        )

        assert outcome.run.status is RunStatus.SUCCEEDED
        assert len(outcome.area_assignments) == 1
        assert len(outcome.rejected_assignments) == 1
        assert "does not accept" in outcome.rejected_assignments[0]["reason"]

    def test_open_questions_are_left_unclassified(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """An unanswered question belongs to no area until it is answered."""

        memory, _ = services
        project, _ = _seed(
            memory, [("unknown", "Which role holds approval authority?")], "rev-unknown"
        )

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-11")

        assert outcome.area_assignments == ()


class TestRunDiscipline:
    def test_the_run_records_what_it_found(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        memory, _ = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-summary")

        outcome = _agent(services).run_on_confirmed_knowledge(project.id, None, "review-12")

        summary = outcome.run.output_summary
        assert outcome.run.status is RunStatus.SUCCEEDED
        assert summary["reviewed_items"] == len(CLASSIFIABLE)
        assert summary["prompt_version"] == "review.v1"
        assert summary["schema_version"] == "review.v1"

    def test_a_replayed_key_does_not_duplicate_edges(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Contradiction edges carry no natural key, so a replay would double them."""

        memory, readiness = services
        project, _ = _seed(memory, CONFLICTING, "rev-replay")
        agent = _agent(services)

        agent.run_on_confirmed_knowledge(project.id, None, "review-same")
        agent.run_on_confirmed_knowledge(project.id, None, "review-same")

        contradictions = [
            f
            for f in readiness_findings(readiness, project.id)
            if f.kind.value == "unresolved_contradiction"
        ]
        assert len(contradictions) == 1

    def test_a_provider_failure_fails_the_run_typed(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        memory, _ = services
        project, _ = _seed(memory, CLASSIFIABLE, "rev-failure")

        def fabricating(request: ReviewRequest) -> object:
            return {
                "findings": [
                    {
                        "kind": "contradiction",
                        "statement_quote": "A statement nobody ever recorded.",
                        "counterpart_quote": request.statements[0].text,
                    }
                ]
            }

        with pytest.raises(UnverifiableReviewError):
            _agent(services, fabricating).run_on_confirmed_knowledge(project.id, None, "review-13")

        runs = [r for r in memory.runs_for_project(project.id) if r.role is AgentRole.REVIEW]
        assert runs[0].status is RunStatus.FAILED
        assert runs[0].error_code == "unverifiable_review"


class TestGrounding:
    def _request(self) -> ReviewRequest:
        return ReviewRequest(
            statements=(
                ReviewedStatement(
                    knowledge_id=KnowledgeItemId("11111111-1111-1111-1111-111111111111"),
                    kind="rule",
                    text="A submitter cannot approve their own report.",
                ),
            ),
            area_keys=("acceptance_criteria",),
        )

    def test_a_quote_outside_the_reviewed_set_is_rejected(self) -> None:
        """The load-bearing guarantee, mirroring extraction's verify_quotes."""

        with pytest.raises(UnverifiableReviewError):
            resolve(
                {"findings": [{"kind": "unsupported_claim", "statement_quote": "Invented."}]},
                self._request(),
            )

    def test_rewrapped_whitespace_still_matches(self) -> None:
        """Re-wrapping a line is not paraphrasing, and must not fail."""

        findings = resolve(
            {
                "findings": [
                    {
                        "kind": "unsupported_claim",
                        "statement_quote": "A submitter cannot\n  approve their own report.",
                    }
                ]
            },
            self._request(),
        )

        assert findings[0].kind is ReviewFindingKind.UNSUPPORTED_CLAIM

    def test_a_finding_must_quote_something(self) -> None:
        with pytest.raises(InvalidReviewOutputError):
            resolve({"findings": [{"kind": "unsupported_claim"}]}, self._request())

    def test_an_unknown_area_is_rejected(self) -> None:
        """A reviewer may not invent a discovery area to file a statement under."""

        with pytest.raises(InvalidReviewOutputError):
            resolve(
                {
                    "findings": [
                        {
                            "kind": "area_classification",
                            "statement_quote": "A submitter cannot approve their own report.",
                            "area_key": "made_up_area",
                        }
                    ]
                },
                self._request(),
            )

    def test_a_statement_cannot_contradict_itself(self) -> None:
        text = "A submitter cannot approve their own report."
        with pytest.raises(InvalidReviewOutputError):
            resolve(
                {
                    "findings": [
                        {
                            "kind": "contradiction",
                            "statement_quote": text,
                            "counterpart_quote": text,
                        }
                    ]
                },
                self._request(),
            )

    def test_the_offline_fixture_is_honest_about_itself(self) -> None:
        """A demo leaning on rules must not read as model judgement."""

        payload = offline_review_fixture(self._request())

        assert isinstance(payload, dict)
        rationales = " ".join(str(f.get("rationale", "")) for f in payload["findings"])
        assert "offline fixture" in rationales


def readiness_findings(readiness: ReadinessService, project_id: ProjectId) -> tuple:
    """Findings via the review service, which reads the same recorded state."""

    from kae_memory.application.review_service import ReviewService

    return ReviewService(readiness._session_factory).findings(project_id)
