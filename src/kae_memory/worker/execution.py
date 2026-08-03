"""The step executor that turns a claimed run into agent work.

The agents in :mod:`kae_memory.agents.roles` start their own runs, because M6
drove them directly. A worker claims a run that already exists, so this executor
performs the same work *against an existing run* instead: read the source the run
names, extract, write knowledge, and let the worker complete it.

That split is deliberate rather than duplication for its own sake. Ownership of
the run lifecycle belongs to whoever created it — the agent when invoked
directly, the worker when the API enqueued it — and having both try to succeed
the same run is how a run reaches an illegal transition.
"""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.agents.deterministic import DeterministicExtractionAdapter
from kae_memory.agents.extraction import ExtractionError, ExtractionPort, ExtractionRequest
from kae_memory.agents.review import (
    ReviewedStatement,
    ReviewFindingKind,
    ReviewPort,
    ReviewRequest,
)
from kae_memory.agents.review_adapter import DeterministicReviewAdapter
from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService, Severity, classify_offline
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole, AgentRun
from kae_memory.domain.identifiers import KnowledgeItemId, MessageId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

from .runner import StepResult


class UnsupportedRoleError(RuntimeError):
    """The run names a role this worker cannot execute.

    Unreachable through :class:`AgentRole` today — all three authorised roles
    have an execution path. It stays as the guard for a fourth appearing without
    one, because failing loudly beats succeeding a run that did nothing.
    """

    error_code = "role_not_implemented"


class MissingRunInputError(RuntimeError):
    """The run does not name what to work on."""

    error_code = "missing_run_input"


@dataclass(frozen=True, slots=True)
class AgentStepExecutor:
    """Executes one claimed run to completion in a single step.

    One step, not many: extraction is a single provider call and the write is one
    transaction, so there is no useful place to checkpoint in between. Multi-step
    runs remain supported by the worker — this executor simply does not need
    them, and inventing intermediate checkpoints would add recovery states with
    nothing to recover.
    """

    session_factory: sessionmaker[DbSession]
    extractor: ExtractionPort
    reviewer: ReviewPort | None = None
    """The review engine, or ``None`` for offline unambiguous-only classification.

    Optional on purpose. A deployment without a review provider still runs
    review runs; it simply classifies less, which is the honest outcome rather
    than a failed run.
    """

    def __call__(self, run: AgentRun, checkpoint: dict[str, Any]) -> StepResult:
        memory = MemoryService(self.session_factory)

        # At-least-once means this step can run twice. If the previous attempt
        # committed its knowledge but died before the run was marked succeeded,
        # re-extracting would double the output — so replay returns what exists.
        existing = memory.knowledge_produced_by(run.id)
        if existing:
            return StepResult(
                checkpoint={"phase": "written", "items_written": len(existing)},
                done=True,
                output_summary={"items_written": len(existing), "replayed": True},
            )

        if run.role is AgentRole.REQUIREMENTS:
            return self._requirements(memory, run)
        if run.role is AgentRole.ARCHITECTURE:
            return self._architecture(memory, run)
        if run.role is AgentRole.REVIEW:
            return self._review(run)
        raise UnsupportedRoleError(  # pragma: no cover - the enum has three members
            f"the {run.role.value} agent is not implemented; run {run.id} cannot be executed"
        )

    def _requirements(self, memory: MemoryService, run: AgentRun) -> StepResult:
        """Extract candidates from the message the run names.

        Prefers ``message_id`` over inline text: the stored message is the
        verbatim source evidence, and extracting from a copy passed through the
        API would break the provenance chain the product exists to show.
        """

        context = run.input_context or {}
        message_id = context.get("message_id")
        source_text = context.get("source_text")
        from_message: MessageId | None = None

        if message_id:
            message = memory.get_message(MessageId(str(message_id)))
            if message is None:
                raise MissingRunInputError(f"unknown message: {message_id}")
            source_text = message.content
            from_message = message.id
        if not source_text:
            raise MissingRunInputError(
                "a requirements run needs input_context.message_id or input_context.source_text"
            )

        result = self.extractor.extract(
            ExtractionRequest(role=AgentRole.REQUIREMENTS, source_text=str(source_text))
        )
        return self._write(
            memory,
            run,
            [
                WriteKnowledgeRequest(
                    kind=item.kind.value,
                    content=item.content,
                    source=item.source_quote,
                    from_message_id=from_message,
                )
                for item in result.items
            ],
            {
                "items_written": len(result.items),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )

    def _architecture(self, memory: MemoryService, run: AgentRun) -> StepResult:
        """Derive decisions from confirmed knowledge only.

        A project with nothing confirmed yields no decisions rather than
        speculative ones. Retrieval records consumption, so "which run used this
        knowledge?" stays answerable relationally afterwards.
        """

        confirmed = memory.retrieve_knowledge(
            run.project_id, lifecycle=LifecycleState.VALIDATED, used_by_run_id=run.id
        )
        if not confirmed:
            return StepResult(
                checkpoint={"phase": "written", "items_written": 0},
                done=True,
                output_summary={"items_written": 0, "reason": "no_confirmed_knowledge"},
            )

        bodies = tuple(item.current_version.content for item in confirmed)
        result = self.extractor.extract(
            ExtractionRequest(
                role=AgentRole.ARCHITECTURE,
                source_text="\n".join(bodies),
                context=bodies,
            )
        )
        return self._write(
            memory,
            run,
            [
                WriteKnowledgeRequest(
                    kind=item.kind.value, content=item.content, source=item.source_quote
                )
                for item in result.items
            ],
            {
                "items_written": len(result.items),
                "consumed_items": len(confirmed),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )

    def _review(self, run: AgentRun) -> StepResult:
        """Classify what can be classified, and report what is wrong.

        One review path, two engines. Without a review adapter the run
        classifies only kinds accepted by exactly one area — no judgement, no
        invented coverage. With one configured, the same step asks a model for
        the ambiguous cases, which is the discrimination a model is actually
        for. The worker owns the run either way, so a review keeps its lease,
        its checkpoint, and its recovery.

        The one authoritative write a review run performs is an area link,
        stamped with the run that proposed it — reversible, attributable, and
        unable to invent coverage, because an area still needs *confirmed*
        knowledge of an accepted kind to become sufficient.

        Neither engine records contradictions. They report candidates and a
        human records one, because an unresolved contradiction on a mandatory
        area blocks readiness: a false positive would stall a project on a
        model's say-so. Flagging costs a reader a moment; recording costs the
        project its gate (ADR-0015).
        """

        readiness = ReadinessService(self.session_factory)
        review = ReviewService(self.session_factory)
        memory = MemoryService(self.session_factory)

        existing = {str(link.knowledge_item_id) for link in readiness.area_links(run.project_id)}
        candidates = [
            item
            for item in memory.retrieve_knowledge(run.project_id, lifecycle=None)
            if str(item.id) not in existing
        ]

        proposals, engine, provenance = self._classify(candidates)

        assigned = 0
        rejected: list[dict[str, str]] = []
        for item_id, area_key in proposals:
            try:
                readiness.assign_area(run.project_id, item_id, area_key, run.id)
            except (DomainInvariantError, LookupError) as error:
                # An area only counts kinds it declares. One impossible pairing
                # is a bad call, not an invalid review, and failing here would
                # discard every sound assignment made before it.
                rejected.append(
                    {"knowledge_id": str(item_id), "area_key": area_key, "reason": str(error)}
                )
                continue
            assigned += 1

        found = review.findings(run.project_id)
        summary: dict[str, Any] = {
            "areas_assigned": assigned,
            "rejected_assignments": rejected,
            "findings": len(found),
            "critical_findings": sum(1 for f in found if f.severity is Severity.CRITICAL),
            # Findings are derived, so the run records how many it saw rather
            # than a copy that could disagree with the state later.
            "classification": engine,
        }
        summary.update(provenance)
        return StepResult(
            checkpoint={"phase": "reviewed", "assigned": assigned},
            done=True,
            output_summary=summary,
        )

    def _classify(
        self, candidates: Sequence[KnowledgeItem]
    ) -> tuple[tuple[tuple[KnowledgeItemId, str], ...], str, dict[str, Any]]:
        """Return area proposals, which engine produced them, and its provenance.

        A reviewer failure falls back to the offline classifier rather than
        failing the run. Losing the ambiguous cases costs coverage a human can
        still supply; losing the run costs the unambiguous ones too.
        """

        if self.reviewer is None or not candidates:
            return classify_offline(candidates), "offline_by_kind", {}

        request = ReviewRequest(
            statements=tuple(
                ReviewedStatement(
                    knowledge_id=item.id, kind=item.kind, text=item.current_version.content
                )
                for item in candidates
            ),
            area_keys=tuple(area.key for area in SOFTWARE_TEMPLATE.areas),
        )
        try:
            result = self.reviewer.review(request)
        except ExtractionError as error:
            return (
                classify_offline(candidates),
                "offline_by_kind_after_reviewer_error",
                {"reviewer_error": error.error_code},
            )

        proposals = tuple(
            (finding.subject_id, finding.area_key)
            for finding in result.findings
            if finding.kind is ReviewFindingKind.AREA_CLASSIFICATION and finding.area_key
        )
        contradictions = [
            finding
            for finding in result.findings
            if finding.kind is ReviewFindingKind.CONTRADICTION
        ]
        return (
            proposals,
            "reviewed_by_model",
            {
                # Reported, never recorded. A human decides whether a proposed
                # conflict becomes a gate (ADR-0015).
                "proposed_contradictions": len(contradictions),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )

    def _write(
        self,
        memory: MemoryService,
        run: AgentRun,
        requests: Sequence[WriteKnowledgeRequest],
        summary: dict[str, Any],
    ) -> StepResult:
        """Write knowledge without completing the run.

        ``complete_run=False`` matters: the worker completes the run when the
        step reports done, and two callers succeeding the same run is an illegal
        transition, not a redundant one.
        """

        memory.write_knowledge(run.id, requests, complete_run=False)
        return StepResult(
            checkpoint={"phase": "written", "items_written": len(requests)},
            done=True,
            output_summary=summary,
        )


def default_reviewer() -> ReviewPort | None:
    """Return the review engine named by the environment.

    ``KAE_REVIEW=deterministic`` gives the offline fixture, which classifies
    only where a kind leaves no choice. ``KAE_REVIEW=off`` disables the engine
    entirely and falls back to the same unambiguous classifier without a review
    call. Anything else is reserved for a live adapter.
    """

    setting = os.environ.get("KAE_REVIEW", "deterministic").strip().lower()
    if setting in {"off", "none", ""}:
        return None
    return DeterministicReviewAdapter()


def default_extractor(build_bedrock: Callable[[], ExtractionPort] | None = None) -> ExtractionPort:
    """Return the extractor named by the environment.

    **Deterministic by default.** The demonstrable path must not depend on a
    provider being reachable, on credentials, or on a bill — and a fixture
    adapter makes the workflow reproducible for anyone who clones the repository.
    Set ``KAE_EXTRACTION=bedrock`` for the live adapter.
    """

    if os.environ.get("KAE_EXTRACTION", "deterministic").lower() != "bedrock":
        return DeterministicExtractionAdapter()

    if build_bedrock is not None:  # pragma: no cover - injected only by tests
        return build_bedrock()

    from kae_memory.agents.bedrock import BedrockExtractionAdapter

    region = os.environ.get("AWS_REGION", "").strip()
    if not region:
        raise RuntimeError("KAE_EXTRACTION=bedrock requires AWS_REGION.")
    return BedrockExtractionAdapter(region=region)
