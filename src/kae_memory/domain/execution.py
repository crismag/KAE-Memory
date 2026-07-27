"""Agent execution contracts.

An :class:`AgentRun` is the durable record of one agent execution. It records that
work happened and how far it got; it never owns knowledge. Knowledge remains owned
by the project through the knowledge item and version contracts.

See ``specifications/AGENT_EXECUTION_MODEL.md``.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import DomainInvariantError, InvalidRunTransitionError
from .identifiers import AgentRunId, ProjectId, SessionId


class AgentRole(StrEnum):
    """The three authorised agent roles.

    Adding a role requires a new approved requirement. The database column is a
    plain string, so extending this enum does not require a migration.
    """

    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    REVIEW = "review"


class RunStatus(StrEnum):
    """Durable status of one agent execution."""

    PENDING = "pending"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.CANCELLED, RunStatus.ABANDONED}
)
"""Statuses that are never reopened.

``FAILED`` and ``INTERRUPTED`` are deliberately absent: a failed run may be
retried and an interrupted run may be resumed, both by moving back to
``RUNNING``. A new attempt is a new run in the same continuation chain, never a
mutation of a finished one.
"""

_ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.INTERRUPTED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.INTERRUPTED: frozenset({RunStatus.RUNNING, RunStatus.ABANDONED}),
    RunStatus.FAILED: frozenset({RunStatus.RUNNING, RunStatus.ABANDONED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.ABANDONED: frozenset(),
}


def ensure_run_transition(current: RunStatus, target: RunStatus) -> None:
    """Validate a requested run status transition."""

    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidRunTransitionError(
            f"cannot transition agent run from {current.value} to {target.value}"
        )


@dataclass(frozen=True, slots=True)
class AgentRun:
    """Durable record of one agent execution.

    ``input_context``, ``output_summary``, and ``continuation_state`` hold bounded
    structured state only. Model prompts, credentials, and raw provider responses
    must never be stored here.
    """

    id: AgentRunId
    project_id: ProjectId
    role: AgentRole
    idempotency_key: str
    status: RunStatus = RunStatus.PENDING
    session_id: SessionId | None = None
    attempt_number: int = 1
    input_context: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None
    continuation_state: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip():
            raise DomainInvariantError("agent run requires a non-empty idempotency key")
        if self.attempt_number < 1:
            raise DomainInvariantError("agent run attempt number must be positive")
        for label, moment in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
            ("failed_at", self.failed_at),
        ):
            if moment is not None and moment.tzinfo is None:
                raise DomainInvariantError(f"agent run {label} must be timezone-aware")

    @property
    def is_terminal(self) -> bool:
        """Return whether the run has reached a status that is never reopened."""

        return self.status in TERMINAL_STATUSES

    @property
    def is_resumable(self) -> bool:
        """Return whether another worker may continue this run."""

        return self.status in {RunStatus.INTERRUPTED, RunStatus.FAILED}

    def start(self, moment: datetime) -> "AgentRun":
        """Return a running copy of this run.

        Resuming an interrupted or failed run increments the attempt number so the
        continuation chain stays visible.
        """

        ensure_run_transition(self.status, RunStatus.RUNNING)
        attempt = self.attempt_number + 1 if self.is_resumable else self.attempt_number
        return replace(self, status=RunStatus.RUNNING, started_at=moment, attempt_number=attempt)

    def succeed(self, moment: datetime, output_summary: dict[str, Any] | None = None) -> "AgentRun":
        """Return a successfully completed copy of this run."""

        ensure_run_transition(self.status, RunStatus.SUCCEEDED)
        return replace(
            self,
            status=RunStatus.SUCCEEDED,
            completed_at=moment,
            output_summary=output_summary if output_summary is not None else self.output_summary,
        )

    def fail(self, moment: datetime, error_code: str, error_message: str) -> "AgentRun":
        """Return a failed copy of this run carrying typed failure information."""

        ensure_run_transition(self.status, RunStatus.FAILED)
        return replace(
            self,
            status=RunStatus.FAILED,
            failed_at=moment,
            error_code=error_code,
            error_message=error_message,
        )

    def interrupt(self, continuation_state: dict[str, Any] | None = None) -> "AgentRun":
        """Return an interrupted copy of this run, eligible for resumption.

        A worker that stops without reporting an outcome leaves the run here. Any
        continuation state passed in has already been committed durably.
        """

        ensure_run_transition(self.status, RunStatus.INTERRUPTED)
        return replace(
            self,
            status=RunStatus.INTERRUPTED,
            continuation_state=(
                continuation_state if continuation_state is not None else self.continuation_state
            ),
        )

    def abandon(self, moment: datetime, reason: str) -> "AgentRun":
        """Return an abandoned copy of this run after the retry budget is spent."""

        ensure_run_transition(self.status, RunStatus.ABANDONED)
        return replace(
            self,
            status=RunStatus.ABANDONED,
            failed_at=moment,
            error_code="retry_budget_exhausted",
            error_message=reason,
        )

    def cancel(self) -> "AgentRun":
        """Return a cancelled copy of this run.

        Cancellation is a human act and is distinct from abandonment, which is
        retry-budget exhaustion.
        """

        ensure_run_transition(self.status, RunStatus.CANCELLED)
        return replace(self, status=RunStatus.CANCELLED)
