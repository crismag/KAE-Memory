"""The durable worker.

A dedicated process, separate from any HTTP application. It claims one run at a
time, executes one step at a time, checkpoints after every step, and renews its
lease while work is in progress (ADR-0007).

Compute is disposable. Killing this process at any point leaves the database in a
state another worker can continue from, because the claim is committed state and
every checkpoint is durable.

The guarantee is **at-least-once step execution with fenced ownership, durable
checkpoints, and idempotent effects**. It is never exactly-once: a worker can
complete an external call and die before recording the result.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.execution import (
    DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_LEASE_SECONDS,
    AgentRole,
    AgentRun,
    RunStatus,
)
from kae_memory.domain.identifiers import AgentRunId
from kae_memory.persistence.transactions import RetryPolicy, run_transaction
from kae_memory.persistence.workspace_repositories import AgentRunRepository


class LeaseLostError(RuntimeError):
    """Raised when a worker discovers another worker has reclaimed its run.

    Not a failure of the run — a failure of *this worker's* claim on it. The
    worker stops immediately rather than finishing the step, because anything it
    wrote afterwards would be rejected by fencing anyway.
    """


@dataclass(frozen=True, slots=True)
class FollowUp:
    """A run to enqueue when the run that asked for it succeeds.

    The run-dependency mechanism whose absence made review a manual step.

    `IngestionService.enqueue_review` says it plainly: review is cross-chunk, so
    it is meaningful only once extraction has drained, and *"there is no
    run-dependency mechanism here, so enqueuing it alongside them would let a
    worker claim it first and review an empty project."* The conclusion drawn
    was that the caller decides when — and no caller ever did. A deployment
    accumulated twenty-five knowledge revisions and zero review runs, so every
    discovery area stayed empty and readiness reported 0% over accurate
    knowledge.

    This is that mechanism, in the one place that knows a run has finished.
    """

    role: AgentRole
    #: Deduplicates. Several runs finishing together each propose the follow-up;
    #: an identical key means one run, not one per proposer.
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class StepResult:
    """What one workflow step produced."""

    checkpoint: dict[str, Any]
    done: bool = False
    output_summary: dict[str, Any] | None = None
    #: Enqueued **in the same transaction that marks this run succeeded**, so a
    #: crash cannot leave a project whose extraction is complete and whose
    #: review was never asked for. Ignored unless `done`.
    follow_up: tuple[FollowUp, ...] = ()


class StepExecutor(Protocol):
    """Executes one durable step of a run.

    Implementations must be **idempotent for a given checkpoint**: the same run
    replayed from the same checkpoint must converge on the same result, because
    at-least-once means a step can run twice.
    """

    def __call__(self, run: AgentRun, checkpoint: dict[str, Any]) -> StepResult: ...


@dataclass(slots=True)
class WorkerConfig:
    """Timing and retry policy, defaulted to the values ADR-0007 approved."""

    worker_id: str
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    idle_poll_seconds: float = 2.0
    max_attempts: int = 3
    backoff_base_seconds: float = 5.0
    graceful_shutdown_seconds: float = 25.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)


class Worker:
    """Claim, execute, checkpoint, renew, recover."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        executor: StepExecutor,
        config: WorkerConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._executor = executor
        self._config = config
        self._clock = clock
        self._stopping = False

    @property
    def worker_id(self) -> str:
        """The identifier recorded as the lease owner."""

        return self._config.worker_id

    def request_stop(self) -> None:
        """Ask the worker to finish its current step and stop.

        Graceful shutdown: no new run is claimed, the current step completes, its
        checkpoint commits, and the lease is released so the run is immediately
        claimable rather than waiting out its expiry.
        """

        self._stopping = True

    def _run[ResultT](self, operation: Callable[[DbSession], ResultT]) -> ResultT:
        return run_transaction(self._session_factory, operation, self._config.retry_policy)

    def claim(self) -> AgentRun | None:
        """Claim one runnable or reclaimable run.

        The claim transaction commits immediately and does no external work, so it
        is never held open across a model call.
        """

        moment = self._clock()

        def operation(session: DbSession) -> AgentRun | None:
            return AgentRunRepository(session).claim_next(
                self._config.worker_id, moment, self._config.lease_seconds
            )

        return self._run(operation)

    def heartbeat(self, run: AgentRun) -> bool:
        """Renew the lease. ``False`` means the run has been reclaimed."""

        moment = self._clock()

        def operation(session: DbSession) -> bool:
            return AgentRunRepository(session).heartbeat(run, moment, self._config.lease_seconds)

        return self._run(operation)

    def execute(self, run: AgentRun) -> AgentRun:
        """Drive one claimed run to a terminal state, or until the lease is lost.

        Each step commits its checkpoint before the next begins, so a kill between
        steps loses at most the step in flight.
        """

        current = run
        while True:
            if not self.heartbeat(current):
                raise LeaseLostError(f"run {current.id} was reclaimed by another worker")

            checkpoint = dict(current.continuation_state or {})
            try:
                result = self._executor(current, checkpoint)
            except Exception as error:
                return self._fail(current, error)

            current = self._checkpoint(current, result)
            if result.done:
                return current
            if self._stopping:
                self._release(current)
                return current

    def _checkpoint(self, run: AgentRun, result: StepResult) -> AgentRun:
        moment = self._clock()
        updated = (
            run.succeed(moment, result.output_summary)
            if result.done
            else _with_checkpoint(run, result.checkpoint)
        )
        follow_up = result.follow_up if result.done else ()
        if not self._save(updated, moment, follow_up):
            raise LeaseLostError(f"run {run.id} was reclaimed before its checkpoint committed")
        return updated

    def _fail(self, run: AgentRun, error: Exception) -> AgentRun:
        """Record a failure, scheduling a retry or abandoning the run.

        Exhausting the budget moves the run to ``abandoned`` rather than looping,
        so a permanently failing run surfaces instead of consuming the worker.
        """

        moment = self._clock()
        code = getattr(error, "error_code", type(error).__name__)
        failed = run.fail(moment, str(code), str(error))

        if failed.attempt_number >= self._config.max_attempts:
            updated = failed.abandon(moment, f"{failed.attempt_number} attempts exhausted: {error}")
        else:
            delay = self._config.backoff_base_seconds * (2 ** (failed.attempt_number - 1))
            updated = _with_next_attempt(failed, moment + timedelta(seconds=delay))

        if not self._save(updated, moment):
            raise LeaseLostError(f"run {run.id} was reclaimed before its failure was recorded")
        return updated

    def _save(
        self, run: AgentRun, moment: datetime, follow_up: tuple[FollowUp, ...] = ()
    ) -> bool:
        """Persist the run, and any work its completion entitles.

        One transaction, deliberately. Enqueuing afterwards would leave a window
        where a project's extraction is complete and its review was never asked
        for — recoverable only by someone noticing, which is exactly how the
        manual version failed. Fencing still decides: a run reclaimed by another
        worker saves nothing and enqueues nothing.
        """

        def operation(session: DbSession) -> bool:
            repository = AgentRunRepository(session)
            if not repository.save_fenced(run, moment):
                return False
            for entry in follow_up:
                # Idempotent by key. Several runs finishing together each
                # propose the same follow-up; the first wins and the rest find
                # it, so a project gets one review rather than one per chunk.
                if repository.find_by_idempotency_key(run.project_id, entry.idempotency_key):
                    continue
                repository.add(
                    AgentRun(
                        id=AgentRunId(str(uuid4())),
                        project_id=run.project_id,
                        session_id=run.session_id,
                        role=entry.role,
                        status=RunStatus.PENDING,
                        idempotency_key=entry.idempotency_key,
                    ),
                    moment,
                )
            return True

        return self._run(operation)

    def _release(self, run: AgentRun) -> None:
        moment = self._clock()

        def operation(session: DbSession) -> bool:
            return AgentRunRepository(session).release(run, moment)

        self._run(operation)

    def run_once(self) -> AgentRun | None:
        """Claim and execute a single run, if one is available."""

        claimed = self.claim()
        if claimed is None:
            return None
        try:
            return self.execute(claimed)
        except LeaseLostError:
            # Another worker owns it now. Nothing to clean up: fencing already
            # rejected anything this worker tried to write.
            return None

    def stop_requested(self) -> bool:
        """Whether a stop has been asked for."""

        return self._stopping

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> int:
        """Claim and execute runs until asked to stop. Returns how many completed.

        The whole daemon loop. It polls rather than subscribing because
        CockroachDB is authoritative for what is runnable (ADR-0007) — a queue
        would be a second source of truth about work that already has one.

        ``idle_poll_seconds`` is honoured here, which is the first time it has
        been: it was declared with the rest of :class:`WorkerConfig` and unused
        until the worker became a process.
        """

        processed = 0
        while not self._stopping:
            if self.run_once() is None:
                sleep(self._config.idle_poll_seconds)
                continue
            processed += 1
        return processed

    def run_until_idle(self, max_runs: int = 100) -> int:
        """Process runs until none are claimable. Returns how many completed."""

        processed = 0
        while processed < max_runs and not self._stopping:
            if self.run_once() is None:
                break
            processed += 1
        return processed


def _with_checkpoint(run: AgentRun, checkpoint: dict[str, Any]) -> AgentRun:
    return replace(run, continuation_state=checkpoint, status=RunStatus.RUNNING)


def _with_next_attempt(run: AgentRun, moment: datetime) -> AgentRun:
    """Schedule the retry.

    ``retry_wait`` is not a status. A run awaiting retry is ``failed`` with a
    future ``next_attempt_at`` — the existing vocabulary, per ADR-0007.
    """

    return replace(run, next_attempt_at=moment)
