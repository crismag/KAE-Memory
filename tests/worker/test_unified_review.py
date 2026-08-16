"""One review path, two engines.

The worker owns the review run either way, so it keeps its lease, checkpoint,
and recovery. What changes is who proposes the classifications: an offline rule
that refuses ambiguous kinds, or a model that is asked precisely for them.

What does not change is the contradiction policy. Neither engine records one.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.extraction import ProviderTimeoutError
from kae_memory.agents.provider import ProviderConfigurationError
from kae_memory.agents.review import ReviewRequest, UnverifiableReviewError
from kae_memory.agents.review_adapter import DeterministicReviewAdapter
from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import ProjectId
from kae_memory.worker.execution import (
    AgentStepExecutor,
    default_reviewer,
    review_batch_size,
)
from kae_memory.worker.runner import Worker, WorkerConfig

SEED = [
    ("actor", "Ministry leaders submit monthly reports."),
    ("requirement", "Only an authorised approver may approve a report."),
    ("rule", "A submitter cannot approve their own report."),
]


def _seed(memory: MemoryService, project_id: ProjectId, key: str) -> None:
    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, key)
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in SEED
        ],
    )
    for item in items:
        memory.confirm_knowledge(item.id)


def _review(factory: sessionmaker[Session], project_id: ProjectId, reviewer: object) -> AgentRun:
    MemoryService(factory).enqueue_run(project_id, AgentRole.REVIEW, "review-1")
    executed = Worker(
        factory,
        AgentStepExecutor(factory, object(), reviewer),  # type: ignore[arg-type]
        WorkerConfig(worker_id="reviewer"),
    ).run_once()
    assert executed is not None, "a run was enqueued, so one must have been claimed"
    return executed


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, ReadinessService, ProjectId]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    readiness.install_template()
    proj = memory.create_project("Ministry Reporting", key="unified-review")
    _seed(memory, proj.id, "seed-1")
    return memory, readiness, proj.id


class TestWithoutAReviewer:
    def test_every_kind_that_can_reach_an_area_is_classified(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """`EPI-3b`. Refusing to guess left the guessing to a person.

        All three seeded statements are placed. Only the ``actor`` is one an
        area accepts uniquely, and before this it was the only one placed.
        """

        _, readiness, project_id = project

        executed = _review(factory, project_id, None)

        assert executed.status is RunStatus.SUCCEEDED
        assert (executed.output_summary or {})["classification"] == "offline_by_content"
        assert len(readiness.area_links(project_id)) == len(SEED)
        assert "users_and_stakeholders" in {
            link.area_key for link in readiness.area_links(project_id)
        }

    def test_the_run_says_how_much_of_the_placement_the_statements_chose(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """No column on an area link carries confidence, so the run reports it.

        Without this the summary is an assigned count, and a run that read
        every statement is indistinguishable from one that defaulted them all.
        """

        _, _readiness, project_id = project

        summary = _review(factory, project_id, None).output_summary or {}

        assert sum(summary["offline_confidence"].values()) == len(SEED)
        # The `actor` is placed because one area accepts it; the other two say
        # nothing that chooses between the areas their kinds reach.
        assert summary["offline_confidence"] == {"high": 1, "low": 2}


class TestWithAReviewer:
    def test_the_run_reports_which_engine_classified(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """A reader must be able to tell a model's judgement from a rule.

        **This test used to assert the opposite of its own docstring.** It ran
        the fixture adapter and asserted `reviewed_by_model`, so the one check
        standing between a recorded payload and a claim about a model was
        agreeing with the claim (`AUD-039`).
        """

        _, _, project_id = project

        executed = _review(factory, project_id, DeterministicReviewAdapter())

        assert (executed.output_summary or {})["classification"] == "reviewed_by_fixture"
        assert (executed.output_summary or {})["prompt_version"] == "review.v1"
        # The provenance was always honest — `model` names the fixture. What was
        # missing is that nothing above the run read it, and `classification` is
        # the field readiness carries out to a person.
        assert (executed.output_summary or {})["model"] == "deterministic-review-fixture"

    def test_only_an_adapter_that_claims_judgement_gets_the_word_model(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """The marker is a claim, and the default is not to make it.

        A new adapter that forgets `judges` reports `reviewed_by_fixture` about
        a model's work — an understatement, which is recoverable. The other
        default gave a fixture a model's authority, which is not.
        """

        _, _, project_id = project

        class Judging:
            judges = True

            def review(self, request: ReviewRequest) -> Any:
                return DeterministicReviewAdapter().review(request)

        executed = _review(factory, project_id, Judging())

        assert (executed.output_summary or {})["classification"] == "reviewed_by_model"

    def test_classification_is_still_attributable(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        _, readiness, project_id = project

        executed = _review(factory, project_id, DeterministicReviewAdapter())

        links = readiness.area_links(project_id)
        assert links
        assert all(link.assigned_by_agent_run_id == executed.id for link in links)

    def test_a_contradiction_is_proposed_never_recorded(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The policy both engines share (ADR-0015)."""

        memory = MemoryService(factory)
        readiness = ReadinessService(factory)
        readiness.install_template()
        proj = memory.create_project("Conflicts", key="unified-conflict")
        run = memory.start_run(proj.id, AgentRole.REQUIREMENTS, "seed-conflict")
        items = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="rule", content="A submitter can approve their own report.", source="s"
                ),
                WriteKnowledgeRequest(
                    kind="rule", content="A submitter cannot approve their own report.", source="s"
                ),
            ],
        )
        for item in items:
            memory.confirm_knowledge(item.id)

        executed = _review(factory, proj.id, DeterministicReviewAdapter())

        assert (executed.output_summary or {})["proposed_contradictions"] == 1
        assert readiness.calculate(proj.id).unresolved_contradiction_count == 0


class TestResilience:
    def test_a_reviewer_failure_falls_back_rather_than_failing_the_run(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """A reviewer that cannot be trusted costs judgement, not placement.

        Losing the run would cost the lease and the checkpoint with it. The
        fallback is the offline content rule, so the batch still lands
        somewhere — the run says so in its engine name rather than by leaving
        the statements unplaced.
        """

        _, readiness, project_id = project

        def fabricating(request: ReviewRequest) -> object:
            return {
                "findings": [
                    {
                        "kind": "area_classification",
                        "statement_quote": "A statement nobody recorded.",
                        "area_key": "functional_requirements",
                    }
                ]
            }

        executed = _review(factory, project_id, DeterministicReviewAdapter(fabricating))

        assert executed.status is RunStatus.SUCCEEDED
        assert (executed.output_summary or {})[
            "classification"
        ] == "offline_by_content_after_reviewer_error"
        # Plural, and a list. Requests are batched now, so a run can degrade on
        # some batches and not others, and "which failure" needs an answer that
        # a single code cannot give once there can be more than one.
        assert (executed.output_summary or {})["reviewer_errors"] == [
            UnverifiableReviewError.error_code
        ]
        assert (executed.output_summary or {})["batches_degraded"] == 1
        assert len(readiness.area_links(project_id)) == len(SEED)
        assert (executed.output_summary or {})["offline_confidence"] == {"high": 1, "low": 2}

    def test_an_impossible_pairing_is_dropped_not_fatal(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        _, readiness, project_id = project

        def misfiles(request: ReviewRequest) -> object:
            goal = next(s for s in request.statements if s.kind == "actor")
            return {
                "findings": [
                    {
                        "kind": "area_classification",
                        "statement_quote": goal.text,
                        "area_key": "quality_attributes",
                    }
                ]
            }

        executed = _review(factory, project_id, DeterministicReviewAdapter(misfiles))

        assert executed.status is RunStatus.SUCCEEDED
        assert len((executed.output_summary or {})["rejected_assignments"]) == 1
        assert readiness.area_links(project_id) == ()


class TestConfiguration:
    def test_the_engine_is_selected_by_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KAE_REVIEW", "off")
        assert default_reviewer() is None

        monkeypatch.setenv("KAE_REVIEW", "deterministic")
        assert isinstance(default_reviewer(), DeterministicReviewAdapter)

    def test_an_unrecognised_engine_raises_rather_than_falling_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AUD-006. A typo used to select the fixture, silently.

        The check was `if setting != "bedrock": return DeterministicReviewAdapter()`,
        so `bedrok`, `claude` or `titan` all landed on the offline fixture — and
        the run reported `reviewed_by_model`, because the fixture is a
        `ReviewPort` like any other. An operator who believed they had
        configured a model reviewer got the 16% ceiling with nothing saying so.

        `build_embedder` and `build_classifier` have always raised here. The
        reviewer was the one that fell through, and it is the one whose silent
        fallback changes a number a person reads off a screen.
        """

        # `"Bedrock "` is deliberately absent: `.strip().lower()` normalises it
        # to a valid name, and accepting that spelling is correct behaviour.
        for typo in ("bedrok", "claude", "titan", "gpt-4"):
            monkeypatch.setenv("KAE_REVIEW", typo)
            with pytest.raises(ProviderConfigurationError) as raised:
                default_reviewer()
            assert "bedrock" in str(raised.value), "the message must name what is valid"

    def test_review_is_on_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A cloned repository walks the whole chain with no configuration."""

        monkeypatch.delenv("KAE_REVIEW", raising=False)
        assert default_reviewer() is not None


class TestBatching:
    """One request per project does not survive a real one.

    A live deployment sent all 178 of a project's statements in a single call
    and got `provider_timeout`. That was not bad luck: it is what an unbatched
    request does on any project past a certain size, with the likelihood rising
    as the project grows — so the project that most needed classification was
    the least able to get it.
    """

    def test_statements_are_split_across_requests(
        self,
        factory: sessionmaker[Session],
        project: tuple[Any, ...],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, _readiness, project_id = project
        monkeypatch.setenv("KAE_REVIEW_BATCH", "1")

        sizes: list[int] = []

        class Counting:
            # Stands in for a reviewer that judges, which is what makes
            # `partially_reviewed_by_model` the right word below.
            judges = True

            def review(self, request: ReviewRequest) -> Any:
                sizes.append(len(request.statements))
                return DeterministicReviewAdapter().review(request)

        executed = _review(factory, project_id, Counting())

        assert executed.status is RunStatus.SUCCEEDED
        assert sizes == [1, 1, 1], "three seeded statements, one per request"
        assert (executed.output_summary or {})["batches"] == 3

    def test_one_failed_batch_does_not_discard_the_others(
        self,
        factory: sessionmaker[Session],
        project: tuple[Any, ...],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The gain that batching buys, beyond surviving the call.

        Unbatched, a single failure sent the entire project through the offline
        classifier — every statement losing the judgement a model had been paid
        to give. Now it costs one batch.
        """

        _, readiness, project_id = project
        monkeypatch.setenv("KAE_REVIEW_BATCH", "1")
        seen = 0

        class FailingOnce:
            judges = True

            def review(self, request: ReviewRequest) -> Any:
                nonlocal seen
                seen += 1
                if seen == 1:
                    raise ProviderTimeoutError("the provider did not answer")
                return DeterministicReviewAdapter().review(request)

        executed = _review(factory, project_id, FailingOnce())
        summary = executed.output_summary or {}

        assert executed.status is RunStatus.SUCCEEDED
        assert summary["batches"] == 3
        assert summary["batches_degraded"] == 1
        assert summary["reviewer_errors"] == ["provider_timeout"]
        # Not "offline_by_content_after_reviewer_error": two batches really were
        # reviewed by the model, and saying otherwise understates the run.
        assert summary["classification"] == "partially_reviewed_by_model"
        assert readiness.area_links(project_id), "the surviving batches still classified"

    def test_a_run_that_degraded_everywhere_says_so(
        self, factory: sessionmaker[Session], project: tuple[Any, ...]
    ) -> None:
        """The failure mode the deployment hit, now legible.

        It reported `succeeded` with a fixture's coverage, and readiness then
        published a number derived from it. Nothing above the run record said
        the model had never answered.
        """

        _, _readiness, project_id = project

        class AlwaysFailing:
            def review(self, request: ReviewRequest) -> Any:
                raise ProviderTimeoutError("the provider did not answer")

        summary = _review(factory, project_id, AlwaysFailing()).output_summary or {}

        assert summary["classification"] == "offline_by_content_after_reviewer_error"
        assert summary["batches_degraded"] == summary["batches"]
        assert summary["reviewer_errors"] == ["provider_timeout"]

    def test_a_nonsensical_batch_size_is_refused_not_clamped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deployment that set 0 meant something.

        Silently substituting the default would leave it believing its setting
        applied — the same quiet substitution `default_reviewer` refuses.
        """

        monkeypatch.setenv("KAE_REVIEW_BATCH", "0")
        with pytest.raises(ValueError, match="at least 1"):
            review_batch_size()

        monkeypatch.setenv("KAE_REVIEW_BATCH", "lots")
        with pytest.raises(ValueError, match="whole number"):
            review_batch_size()
