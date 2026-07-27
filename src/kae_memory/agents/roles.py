"""The Requirements and Architecture agents.

Both run through :class:`~kae_memory.application.MemoryService`, so every write
passes the domain invariants and lands in one transaction with the run status
change (ADR-0004, FR-010). Neither agent confirms knowledge — confirmation is a
human act (FR-005).
"""

from dataclasses import dataclass

from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, AgentRun
from kae_memory.domain.identifiers import MessageId, ProjectId, SessionId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem

from .extraction import ExtractionError, ExtractionPort, ExtractionRequest


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
