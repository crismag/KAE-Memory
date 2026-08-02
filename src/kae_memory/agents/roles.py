"""The Requirements, Architecture, and Review agents.

Both run through :class:`~kae_memory.application.MemoryService`, so every write
passes the domain invariants and lands in one transaction with the run status
change (ADR-0004, FR-010). Neither agent confirms knowledge — confirmation is a
human act (FR-005).
"""

from dataclasses import dataclass

from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole, AgentRun
from kae_memory.domain.identifiers import (
    KnowledgeItemId,
    MessageId,
    ProjectId,
    RelationshipId,
    SessionId,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE, ReadinessTemplate

from .extraction import ExtractionError, ExtractionPort, ExtractionRequest
from .review import ReviewedStatement, ReviewFindingKind, ReviewPort, ReviewRequest


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """What one agent execution produced."""

    run: AgentRun
    items: tuple[KnowledgeItem, ...]


class _Agent:
    """Shared execution shape: start a run, extract, write, or fail typed."""

    role: AgentRole

    def __init__(self, service: MemoryService, extractor: ExtractionPort) -> None:
        self._service = service
        self._extractor = extractor

    def _execute(
        self,
        project_id: ProjectId,
        idempotency_key: str,
        source_text: str,
        context: tuple[str, ...],
        session_id: SessionId | None,
        from_message_id: MessageId | None,
    ) -> AgentOutcome:
        run = self._service.start_run(
            project_id,
            self.role,
            idempotency_key,
            session_id=session_id,
            input_context={"source_chars": len(source_text), "context_items": len(context)},
        )

        if run.is_terminal:
            # The idempotency key matched a run that already finished. Return its
            # original output rather than extracting a second time — the
            # guarantee is one run and one result set per key.
            return AgentOutcome(run=run, items=self._service.knowledge_produced_by(run.id))

        try:
            result = self._extractor.extract(
                ExtractionRequest(role=self.role, source_text=source_text, context=context)
            )
        except ExtractionError as error:
            # The typed code travels with the exception, so the run records what
            # actually happened rather than a generic failure.
            self._service.fail_run(run.id, error.error_code, str(error))
            raise

        written = self._service.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=item.kind.value,
                    content=item.content,
                    source=item.source_quote,
                    from_message_id=from_message_id,
                )
                for item in result.items
            ],
            output_summary={
                "items_written": len(result.items),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
                "usage": result.usage,
            },
        )
        final = self._service.get_run(run.id)
        assert final is not None
        return AgentOutcome(run=final, items=written)


class RequirementsAgent(_Agent):
    """Turns a user's own words into candidate knowledge.

    Reads the submitted message. Writes candidates and gaps. Does not write
    architecture decisions, and does not confirm its own output.
    """

    role = AgentRole.REQUIREMENTS

    def run_on_message(
        self,
        project_id: ProjectId,
        session_id: SessionId,
        message_id: MessageId,
        text: str,
        idempotency_key: str,
    ) -> AgentOutcome:
        """Extract candidates from one message."""

        return self._execute(
            project_id=project_id,
            idempotency_key=idempotency_key,
            source_text=text,
            context=(),
            session_id=session_id,
            from_message_id=message_id,
        )


class ArchitectureAgent(_Agent):
    """Derives decisions from requirements a human has confirmed.

    Consumes **confirmed** knowledge only. Unconfirmed candidates and raw
    conversation are not authoritative input, so a project with nothing confirmed
    yields no decisions rather than speculative ones.
    """

    role = AgentRole.ARCHITECTURE

    def run_on_confirmed_knowledge(
        self,
        project_id: ProjectId,
        session_id: SessionId,
        idempotency_key: str,
    ) -> AgentOutcome:
        """Derive decisions from the project's confirmed knowledge.

        Retrieval records consumption, so "which run used this knowledge?" is
        answerable relationally afterwards.
        """

        run = self._service.start_run(
            project_id,
            self.role,
            idempotency_key,
            session_id=session_id,
            input_context={"consumes": LifecycleState.VALIDATED.value},
        )
        if run.is_terminal:
            return AgentOutcome(run=run, items=self._service.knowledge_produced_by(run.id))

        confirmed = self._service.retrieve_knowledge(
            project_id, lifecycle=LifecycleState.VALIDATED, used_by_run_id=run.id
        )
        if not confirmed:
            completed = self._service.complete_run(
                run.id, output_summary={"items_written": 0, "reason": "no_confirmed_knowledge"}
            )
            return AgentOutcome(run=completed, items=())

        source_text = "\n".join(item.current_version.content for item in confirmed)
        try:
            result = self._extractor.extract(
                ExtractionRequest(
                    role=self.role,
                    source_text=source_text,
                    context=tuple(item.current_version.content for item in confirmed),
                )
            )
        except ExtractionError as error:
            self._service.fail_run(run.id, error.error_code, str(error))
            raise

        written = self._service.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind=item.kind.value,
                    content=item.content,
                    source=item.source_quote,
                )
                for item in result.items
            ],
            output_summary={
                "items_written": len(result.items),
                "consumed_items": len(confirmed),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )
        final = self._service.get_run(run.id)
        assert final is not None
        return AgentOutcome(run=final, items=written)


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """What one review execution recorded.

    Separate from :class:`AgentOutcome` because a review produces no knowledge.
    Reporting it as ``items`` would suggest the reviewer added to the record,
    when its whole contract is that it does not.
    """

    run: AgentRun
    contradictions: tuple[RelationshipId, ...] = ()
    proposed_contradictions: tuple[tuple[KnowledgeItemId, KnowledgeItemId], ...] = ()
    area_assignments: tuple[tuple[KnowledgeItemId, str], ...] = ()
    unsupported: tuple[KnowledgeItemId, ...] = ()
    rejected_assignments: tuple[dict[str, str], ...] = ()

    @property
    def finding_count(self) -> int:
        return (
            len(self.contradictions)
            + len(self.proposed_contradictions)
            + len(self.area_assignments)
            + len(self.unsupported)
        )


class ReviewAgent:
    """Reads confirmed knowledge and records how its statements relate.

    The third authorised role, and the only one that writes no knowledge. It
    reports; it does not correct. Confirmed statements stay exactly as the human
    confirmed them, and an unsupported claim is flagged rather than removed —
    deleting what a person approved is not a reviewer's decision to make.

    It writes discovery area links, which carry the run that assigned them and
    which a human can change. It does **not** record contradictions by default.
    An unresolved contradiction on a mandatory area blocks readiness, so a false
    positive would stall a project on a model's say-so: flagging costs a reader
    a moment, recording costs the project its gate (ADR-0015). Detected pairs
    are returned as proposals for a person to act on.

    ``record_contradictions=True`` is available for a caller who has accepted
    that trade deliberately. It is not the default, and no automated path should
    turn it on without a human in the loop.
    """

    role = AgentRole.REVIEW

    def __init__(
        self,
        service: MemoryService,
        readiness: ReadinessService,
        reviewer: ReviewPort,
        template: ReadinessTemplate = SOFTWARE_TEMPLATE,
        record_contradictions: bool = False,
    ) -> None:
        self._service = service
        self._readiness = readiness
        self._reviewer = reviewer
        self._template = template
        self._record_contradictions = record_contradictions

    def run_on_confirmed_knowledge(
        self,
        project_id: ProjectId,
        session_id: SessionId | None,
        idempotency_key: str,
    ) -> ReviewOutcome:
        """Review a project's confirmed knowledge and record what it finds.

        Consumes confirmed knowledge only. Reviewing candidates would let the
        reviewer's findings depend on statements a human has not accepted, and
        a contradiction between two unconfirmed guesses is not a project fact.
        """

        run = self._service.start_run(
            project_id,
            self.role,
            idempotency_key,
            session_id=session_id,
            input_context={"consumes": LifecycleState.VALIDATED.value},
        )
        if run.is_terminal:
            # The key matched a finished run. Its findings are already recorded;
            # replaying them would duplicate edges that carry no natural key.
            return ReviewOutcome(run=run)

        confirmed = self._service.retrieve_knowledge(
            project_id, lifecycle=LifecycleState.VALIDATED, used_by_run_id=run.id
        )
        if not confirmed:
            completed = self._service.complete_run(
                run.id, output_summary={"findings": 0, "reason": "no_confirmed_knowledge"}
            )
            return ReviewOutcome(run=completed)

        assigned = {link.knowledge_item_id for link in self._readiness.area_links(project_id)}
        request = ReviewRequest(
            statements=tuple(
                ReviewedStatement(
                    knowledge_id=item.id,
                    kind=item.kind,
                    text=item.current_version.content,
                )
                for item in confirmed
            ),
            area_keys=tuple(area.key for area in self._template.areas),
        )

        try:
            result = self._reviewer.review(request)
        except ExtractionError as error:
            self._service.fail_run(run.id, error.error_code, str(error))
            raise

        contradictions: list[RelationshipId] = []
        proposed: list[tuple[KnowledgeItemId, KnowledgeItemId]] = []
        assignments: list[tuple[KnowledgeItemId, str]] = []
        unsupported: list[KnowledgeItemId] = []
        rejected: list[dict[str, str]] = []

        for finding in result.findings:
            if finding.kind is ReviewFindingKind.CONTRADICTION:
                assert finding.counterpart_id is not None
                if not self._record_contradictions:
                    proposed.append((finding.subject_id, finding.counterpart_id))
                    continue
                edge = self._readiness.record_contradiction(
                    project_id,
                    finding.subject_id,
                    finding.counterpart_id,
                    created_by_agent_run_id=run.id,
                )
                contradictions.append(edge.id)
            elif finding.kind is ReviewFindingKind.AREA_CLASSIFICATION:
                assert finding.area_key is not None
                # An existing link is a human's or an earlier run's decision.
                # Re-assigning would let a later review silently overrule it.
                if finding.subject_id in assigned:
                    continue
                try:
                    self._readiness.assign_area(
                        project_id,
                        finding.subject_id,
                        finding.area_key,
                        assigned_by_agent_run_id=run.id,
                    )
                except (DomainInvariantError, LookupError) as error:
                    # An area only counts kinds it declares. A reviewer that
                    # proposes an impossible pairing has made one bad call, not
                    # an invalid review — dropping the whole run would discard
                    # the findings that were fine.
                    rejected.append(
                        {
                            "knowledge_id": str(finding.subject_id),
                            "area_key": finding.area_key,
                            "reason": str(error),
                        }
                    )
                    continue
                assigned.add(finding.subject_id)
                assignments.append((finding.subject_id, finding.area_key))
            else:
                unsupported.append(finding.subject_id)

        completed = self._service.complete_run(
            run.id,
            output_summary={
                "findings": len(result.findings),
                "contradictions": len(contradictions),
                "proposed_contradictions": len(proposed),
                "area_assignments": len(assignments),
                "unsupported_claims": len(unsupported),
                "rejected_assignments": rejected,
                "reviewed_items": len(confirmed),
                "prompt_version": result.prompt_version,
                "schema_version": result.schema_version,
                "model": result.model,
            },
        )
        return ReviewOutcome(
            run=completed,
            contradictions=tuple(contradictions),
            proposed_contradictions=tuple(proposed),
            area_assignments=tuple(assignments),
            unsupported=tuple(unsupported),
            rejected_assignments=tuple(rejected),
        )
