"""Publishing a deliverable: render, verify, write, record (N29, N30).

The order is the contract, and every step can refuse:

1. **resolve** the target from a registered id or the project default — never
   from anything the request carried;
2. **check authorisation** for that target's connection;
3. **render and verify** — bytes that do not match the deliverable's record stop
   here, before a provider is reached;
4. **write** through the provider;
5. **record** what happened, whichever way it went.

The recording happens on every path including the failures, because an attempt
nobody wrote down is an operational fact that exists only in someone's memory.

**A failed attempt never touches the deliverable.** Not its state, not its
hashes, not its eligibility. Something between a document and a bucket did not
work, and the document is exactly as good as it was.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.publication import (
    AttemptId,
    AttemptState,
    ErrorCategory,
    PublicationAttempt,
)
from kae_memory.domain.publication_targets import Provider, TargetPurpose
from kae_memory.persistence.tables import PublicationAttemptRow
from kae_memory.persistence.transactions import run_transaction

from .providers.local import LocalFilesystemProvider, LocalPublicationError
from .render_service import RenderError, RenderService, UnreproducibleError, package_hash
from .setup_service import SetupNotFoundError, SetupService


class PublicationRefused(RuntimeError):
    """The publication did not happen, and the attempt says why.

    Carries the recorded attempt so a caller has the history entry without a
    second lookup — and so that "it was refused" and "nothing was recorded" can
    never be the same outcome.
    """

    def __init__(self, message: str, attempt: PublicationAttempt) -> None:
        super().__init__(message)
        self.attempt = attempt


class PublicationService:
    """Publish a recorded deliverable to a registered target."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        render: RenderService | None = None,
        setup: SetupService | None = None,
        local: LocalFilesystemProvider | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._render = render or RenderService(session_factory)
        self._setup = setup or SetupService(session_factory)
        # `None` means local publication is not configured for this deployment,
        # which is a different thing from a provider that failed — and the
        # difference reaches the caller as `configuration` rather than
        # `provider`.
        self._local = local
        self._clock = clock

    def publish(
        self,
        project_id: ProjectId,
        deliverable_id: str,
        target_id: str | None = None,
        purpose: TargetPurpose = TargetPurpose.DELIVERABLE,
        actor: str | None = None,
        overwrite: bool = False,
    ) -> PublicationAttempt:
        """Render, verify, write, and record. Refuse at the first step that cannot.

        `target_id` is optional and resolves to the project default. There is no
        third option: a request cannot name a bucket, a repository, or a path,
        because a request that could would make the authorisation check
        advisory (N27).
        """

        attempt_id = AttemptId(str(uuid4()))
        requested_at = self._clock()

        try:
            target = self._setup.resolve_target(project_id, target_id, purpose)
        except SetupNotFoundError as error:
            return self._record(
                _failed(
                    attempt_id,
                    project_id,
                    deliverable_id,
                    target_id or "<default>",
                    "unresolved",
                    AttemptState.FAILED,
                    ErrorCategory.CONFIGURATION,
                    str(error),
                    actor,
                    requested_at,
                    self._clock(),
                )
            )

        authorization = self._setup.authorization_for(project_id, target.connection_id)
        unavailable = target.unavailable_reason(authorization)
        if unavailable:
            raise PublicationRefused(
                unavailable,
                self._record(
                    _failed(
                        attempt_id,
                        project_id,
                        deliverable_id,
                        str(target.id),
                        target.provider.value,
                        AttemptState.FAILED,
                        ErrorCategory.AUTHORIZATION,
                        unavailable,
                        actor,
                        requested_at,
                        self._clock(),
                    )
                ),
            )

        try:
            package = self._render.verify(project_id, deliverable_id)
        except (RenderError, UnreproducibleError) as error:
            # `verification_failed`, not `failed`. The bytes did not match the
            # record and nothing was written — a correctness problem, and one
            # that a retry cannot fix.
            raise PublicationRefused(
                str(error),
                self._record(
                    _failed(
                        attempt_id,
                        project_id,
                        deliverable_id,
                        str(target.id),
                        target.provider.value,
                        AttemptState.VERIFICATION_FAILED,
                        ErrorCategory.INTEGRITY,
                        str(error),
                        actor,
                        requested_at,
                        self._clock(),
                        verification_passed=False,
                    )
                ),
            ) from None

        if target.provider is not Provider.LOCAL:
            detail = (
                f"the {target.provider.value} provider is not implemented in this "
                f"version. The target, its authorisation, and this attempt are all "
                f"recorded; nothing was written."
            )
            raise PublicationRefused(
                detail,
                self._record(
                    _failed(
                        attempt_id,
                        project_id,
                        deliverable_id,
                        str(target.id),
                        target.provider.value,
                        AttemptState.FAILED,
                        ErrorCategory.PROVIDER,
                        detail,
                        actor,
                        requested_at,
                        self._clock(),
                        verification_passed=True,
                    )
                ),
            )

        if self._local is None:
            detail = "local publication is not configured for this deployment"
            raise PublicationRefused(
                detail,
                self._record(
                    _failed(
                        attempt_id,
                        project_id,
                        deliverable_id,
                        str(target.id),
                        target.provider.value,
                        AttemptState.FAILED,
                        ErrorCategory.CONFIGURATION,
                        detail,
                        actor,
                        requested_at,
                        self._clock(),
                        verification_passed=True,
                    )
                ),
            )

        prefix = (target.configuration or {}).get("prefix") or f"deliverables/{deliverable_id}"
        try:
            written = self._local.publish(package, prefix, overwrite=overwrite)
        except LocalPublicationError as error:
            raise PublicationRefused(
                str(error),
                self._record(
                    _failed(
                        attempt_id,
                        project_id,
                        deliverable_id,
                        str(target.id),
                        target.provider.value,
                        AttemptState.FAILED,
                        ErrorCategory.PROVIDER,
                        str(error),
                        actor,
                        requested_at,
                        self._clock(),
                        verification_passed=True,
                    )
                ),
            ) from None

        return self._record(
            PublicationAttempt(
                id=attempt_id,
                project_id=project_id,
                deliverable_id=deliverable_id,
                target_id=str(target.id),
                provider=target.provider.value,
                state=AttemptState.PUBLISHED,
                package_hash=package_hash(package.artifacts),
                package_size=package.total_size,
                # What was written, relative to the root. An absolute path in a
                # durable record is a fact about one machine, read on another.
                external_reference=written.reference,
                verification_passed=True,
                requested_by=actor,
                requested_at=requested_at,
                completed_at=self._clock(),
            )
        )

    def history(
        self, project_id: ProjectId, deliverable_id: str | None = None
    ) -> tuple[PublicationAttempt, ...]:
        """Every attempt, newest last.

        Failures included, and that is most of the value. A history showing only
        successes cannot answer "has this been flaky", which is the question
        somebody asks on the third failure.
        """

        def operation(session: DbSession) -> tuple[PublicationAttempt, ...]:
            statement = select(PublicationAttemptRow).where(
                PublicationAttemptRow.project_id == str(project_id)
            )
            if deliverable_id:
                statement = statement.where(PublicationAttemptRow.deliverable_id == deliverable_id)
            rows = session.scalars(statement.order_by(PublicationAttemptRow.requested_at)).all()
            return tuple(_as_attempt(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def _record(self, attempt: PublicationAttempt) -> PublicationAttempt:
        """Write the attempt, whichever way it went.

        Every path through `publish` ends here, including the refusals. An
        attempt nobody wrote down is an operational fact that exists only in
        someone's memory.
        """

        def operation(session: DbSession) -> PublicationAttempt:
            session.add(
                PublicationAttemptRow(
                    attempt_id=str(attempt.id),
                    project_id=str(attempt.project_id),
                    deliverable_id=attempt.deliverable_id,
                    target_id=attempt.target_id,
                    provider=attempt.provider,
                    state=attempt.state.value,
                    package_hash=attempt.package_hash,
                    package_size=attempt.package_size,
                    external_reference=attempt.external_reference,
                    verification_passed=attempt.verification_passed,
                    error_category=attempt.error_category.value,
                    error_detail=attempt.error_detail,
                    requested_by=attempt.requested_by,
                    requested_at=attempt.requested_at or datetime.now(UTC),
                    completed_at=attempt.completed_at,
                )
            )
            session.flush()
            return attempt

        return run_transaction(self._session_factory, operation)


def _failed(
    attempt_id: AttemptId,
    project_id: ProjectId,
    deliverable_id: str,
    target_id: str,
    provider: str,
    state: AttemptState,
    category: ErrorCategory,
    detail: str,
    actor: str | None,
    requested_at: datetime,
    completed_at: datetime,
    verification_passed: bool | None = None,
) -> PublicationAttempt:
    return PublicationAttempt(
        id=attempt_id,
        project_id=project_id,
        deliverable_id=deliverable_id,
        target_id=target_id,
        provider=provider,
        state=state,
        verification_passed=verification_passed,
        error_category=category,
        error_detail=detail,
        requested_by=actor,
        requested_at=requested_at,
        completed_at=completed_at,
    )


def _as_attempt(row: PublicationAttemptRow) -> PublicationAttempt:
    return PublicationAttempt(
        id=AttemptId(str(row.attempt_id)),
        project_id=ProjectId(str(row.project_id)),
        deliverable_id=row.deliverable_id,
        target_id=row.target_id,
        provider=row.provider,
        state=AttemptState(row.state),
        package_hash=row.package_hash,
        package_size=row.package_size,
        external_reference=row.external_reference,
        verification_passed=row.verification_passed,
        error_category=ErrorCategory(row.error_category),
        error_detail=row.error_detail,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        completed_at=row.completed_at,
    )
