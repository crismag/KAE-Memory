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
from kae_memory.agents.extraction import ExtractionPort, ExtractionRequest
from kae_memory.application.memory_service import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole, AgentRun
from kae_memory.domain.identifiers import MessageId
from kae_memory.domain.lifecycle import LifecycleState

from .runner import StepResult


class UnsupportedRoleError(RuntimeError):
    """The run names a role this worker cannot execute.

    ``review`` is authorised by FR-009 and not implemented. Failing loudly is the
    honest outcome: silently succeeding an empty review run would report a
    project as reviewed when nothing looked at it.
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
        raise UnsupportedRoleError(
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
