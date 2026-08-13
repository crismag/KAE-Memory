"""Preliminary setup: questions, configuration, targets, connections (N24-N28).

One service over four records, because they are one workflow. A setup question
answered becomes a configured value; a configured value names a target; a target
publishes through a connection. Splitting them into four services would put the
seams in the wrong places — every caller would have to know the order.

Three rules the whole file exists to hold:

**Setup readiness is reported apart from knowledge readiness.** They answer
different questions and neither can stand in for the other. A project with a
clear brief and no authorisation is fully understood and cannot publish.

**Only setup can block, and never because knowledge is thin.** Every blocking
gap names a capability unavailable for one of the reasons N34 allows: an unmade
choice, missing authorisation, an integrity failure, an unavailable provider, or
an unsupported feature. A gap reading "not enough is known" would be the
rejected readiness gate wearing a new name.

**Answering a setup question configures the project and touches no knowledge.**
The two queues never mix, in either direction.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.dispositions import Disposition, ensure_disposition, settles
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.project_configuration import (
    KNOWN_FIELDS,
    ConfigurationError,
    ConfiguredValue,
    ProjectConfiguration,
    ensure_not_secret,
)
from kae_memory.domain.publication_targets import (
    AuthorizationState,
    ConnectionId,
    Provider,
    ProviderConnection,
    PublicationTarget,
    TargetError,
    TargetId,
    TargetPurpose,
)
from kae_memory.domain.setup import (
    InferencePolicy,
    SetupGap,
    SetupReadiness,
    SetupState,
    ValueState,
)
from kae_memory.domain.setup_questions import (
    SetupPurpose,
    SetupQuestion,
    SetupQuestionError,
    SetupQuestionId,
)
from kae_memory.persistence.tables import (
    ProjectConfigurationRow,
    ProviderConnectionRow,
    PublicationTargetRow,
    SetupQuestionRow,
)
from kae_memory.persistence.transactions import run_transaction


class SetupNotFoundError(LookupError):
    """No such setup question, target, or connection in this project."""


class DefaultConflictError(RuntimeError):
    """A second default for one purpose. At most one is the whole point."""


class SetupService:
    """Read and change how a project is configured, never what it knows."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    # -- questions ---------------------------------------------------------

    def ask(
        self,
        project_id: ProjectId,
        purpose: SetupPurpose,
        question: str,
        field_name: str,
        blocking: bool = False,
        suggested_answer: str | None = None,
        suggestion_evidence: str | None = None,
        policy: InferencePolicy = InferencePolicy.ASK,
        becomes_default: bool = True,
    ) -> SetupQuestion:
        """Record a setup question, or return the one already asked.

        Idempotent by field. Asking twice about the same field is asking a
        person the same thing twice, which is the failure the clarification
        queue already learned to avoid — and here the unique index enforces it
        rather than a lookup, because two concurrent callers would both find
        nothing.
        """

        asked = SetupQuestion(
            id=SetupQuestionId(str(uuid4())),
            project_id=project_id,
            purpose=purpose,
            question=question,
            field_name=field_name,
            blocking=blocking,
            suggested_answer=suggested_answer,
            suggestion_evidence=suggestion_evidence,
            policy=policy,
            becomes_default=becomes_default,
            asked_at=self._clock(),
        )

        def operation(session: DbSession) -> SetupQuestion:
            row = SetupQuestionRow(
                setup_question_id=str(asked.id),
                project_id=str(project_id),
                purpose=purpose.value,
                question=question,
                field_name=field_name,
                blocking=asked.blocking,
                suggested_answer=suggested_answer,
                suggestion_evidence=suggestion_evidence,
                policy=policy.value,
                disposition=Disposition.OPEN.value,
                becomes_default=becomes_default,
                revisitable=True,
                asked_at=asked.asked_at,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = session.scalars(
                    select(SetupQuestionRow).where(
                        SetupQuestionRow.project_id == str(project_id),
                        SetupQuestionRow.field_name == field_name,
                    )
                ).first()
                if existing is None:  # pragma: no cover - only if the index changed
                    raise
                return _as_question(existing)
            return _as_question(row)

        return run_transaction(self._session_factory, operation)

    def answer(
        self,
        project_id: ProjectId,
        question_id: str,
        answer: str,
        actor: str,
        disposition: Disposition = Disposition.ANSWERED,
        assumption_id: str | None = None,
    ) -> SetupQuestion:
        """Record an answer and, if it settles, configure the project.

        **Configuration only.** Nothing here writes knowledge, and that is the
        boundary N25 exists to hold: "publish to crismag/KAE-Studio" is a
        configuration decision, and recording it as a knowledge statement would
        put it in front of a reviewer as something to confirm about the product.

        A non-settling disposition records the answer and configures nothing
        (N36). "Pick something reasonable for now" is a real answer and it is
        not a default anyone set.
        """

        ensure_disposition(disposition, answer=answer, assumption_id=assumption_id)

        def operation(session: DbSession) -> SetupQuestion:
            row = session.get(SetupQuestionRow, question_id)
            if row is None or row.project_id != str(project_id):
                raise SetupNotFoundError(f"unknown setup question in this project: {question_id}")
            row.answer = answer
            row.answered_by = actor
            row.disposition = disposition.value
            row.answered_at = self._clock()
            session.flush()

            # **The guard `set_value` has and this path did not.**
            #
            # `ask` does not check `field_name` against `KNOWN_FIELDS` —
            # deliberately, because an authorisation question is not a
            # configuration field. But this branch writes one, so a question
            # asked about `primry_repository` used to produce a
            # `project_configuration` row that `ProjectConfiguration`
            # refuses to construct — permanently failing `GET /setup` for
            # that project, with no way to remove the row through this
            # service.
            #
            # Skipping rather than raising: the answer is recorded either
            # way, and a settled question is not made unsettled by having
            # nowhere to write. The disposition is the durable part.
            if settles(disposition) and row.becomes_default and row.field_name in KNOWN_FIELDS:
                _write_value(
                    session,
                    project_id,
                    ConfiguredValue(
                        field_name=row.field_name,
                        value=answer,
                        state=ValueState.CONFIRMED,
                        evidence=f"answered setup question {question_id}",
                        confirmed_by=actor,
                        updated_at=self._clock(),
                    ),
                )
            return _as_question(row)

        return run_transaction(self._session_factory, operation)

    def open_questions(
        self, project_id: ProjectId, blocking_only: bool = False
    ) -> tuple[SetupQuestion, ...]:
        """Setup questions nobody has settled.

        Never returns a clarification, and `ClarificationService` never returns
        one of these. "What should this product do?" and "where should this
        publish?" are different conversations, and interleaving them makes both
        worse.
        """

        def operation(session: DbSession) -> tuple[SetupQuestion, ...]:
            rows = session.scalars(
                select(SetupQuestionRow)
                .where(SetupQuestionRow.project_id == str(project_id))
                .order_by(SetupQuestionRow.asked_at)
            ).all()
            questions = tuple(_as_question(row) for row in rows if not _as_question(row).settled)
            return tuple(q for q in questions if q.blocking) if blocking_only else questions

        return run_transaction(self._session_factory, operation)

    # -- configuration -----------------------------------------------------

    def configuration(self, project_id: ProjectId) -> ProjectConfiguration:
        """Return a project's typed configuration, mostly unknown at first.

        An empty configuration is the ordinary state of a new project, not a
        degenerate one — an idea described in a sentence has no repository, no
        branch, and no publication target.
        """

        def operation(session: DbSession) -> ProjectConfiguration:
            rows = session.scalars(
                select(ProjectConfigurationRow).where(
                    ProjectConfigurationRow.project_id == str(project_id)
                )
            ).all()
            return ProjectConfiguration(
                project_id=project_id,
                values={row.field_name: _as_value(row) for row in rows},
            )

        return run_transaction(self._session_factory, operation)

    def set_value(
        self,
        project_id: ProjectId,
        field_name: str,
        value: str,
        state: ValueState,
        evidence: str = "",
        confirmed_by: str | None = None,
        derived_from_knowledge_id: str | None = None,
    ) -> ConfiguredValue:
        """Set one configuration field, refusing what may not be configured.

        `derived_from_knowledge_id` is how a value legitimately comes from
        knowledge: **once, deliberately, recorded**. That is the opposite of
        publication searching prose at runtime to decide where to write, which
        is what N26 exists to prevent.
        """

        ensure_not_secret(field_name)
        if field_name not in KNOWN_FIELDS:
            raise ConfigurationError(
                f"unknown configuration field {field_name!r}. Known: "
                f"{', '.join(sorted(KNOWN_FIELDS))}"
            )
        configured = ConfiguredValue(
            field_name=field_name,
            value=value,
            state=state,
            evidence=evidence,
            confirmed_by=confirmed_by,
            derived_from_knowledge_id=derived_from_knowledge_id,
            updated_at=self._clock(),
        )

        def operation(session: DbSession) -> ConfiguredValue:
            _write_value(session, project_id, configured)
            return configured

        return run_transaction(self._session_factory, operation)

    # -- connections -------------------------------------------------------

    def record_connection(
        self,
        project_id: ProjectId,
        provider: Provider,
        credential_reference: str | None = None,
        state: AuthorizationState = AuthorizationState.NEVER_GRANTED,
        authorized_by: str | None = None,
        detail: str = "",
    ) -> ProviderConnection:
        """Record permission to reach a provider, never the means.

        `credential_reference` names where a credential lives. The domain
        refuses one that looks like a credential itself, because this record is
        returned to callers and a secret in it is a secret disclosed.
        """

        connection = ProviderConnection(
            id=ConnectionId(str(uuid4())),
            project_id=project_id,
            provider=provider,
            state=state,
            credential_reference=credential_reference,
            authorized_by=authorized_by,
            detail=detail,
        )

        def operation(session: DbSession) -> ProviderConnection:
            session.add(
                ProviderConnectionRow(
                    connection_id=str(connection.id),
                    project_id=str(project_id),
                    provider=provider.value,
                    state=state.value,
                    credential_reference=credential_reference,
                    authorized_by=authorized_by,
                    detail=detail,
                )
            )
            session.flush()
            return connection

        return run_transaction(self._session_factory, operation)

    def connections(self, project_id: ProjectId) -> tuple[ProviderConnection, ...]:
        """Every connection this project has recorded.

        There was no way to list them. `authorization_for` answers about one
        connection whose id you already hold, which is enough for publication
        and useless for a person deciding whether to add another — so a setup
        surface could create connections and never show them.
        """

        def operation(session: DbSession) -> tuple[ProviderConnection, ...]:
            rows = session.scalars(
                select(ProviderConnectionRow)
                .where(ProviderConnectionRow.project_id == str(project_id))
                .order_by(ProviderConnectionRow.connection_id)
            ).all()
            return tuple(_as_connection(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def authorize_connection(
        self,
        project_id: ProjectId,
        connection_id: str,
        state: AuthorizationState,
        authorized_by: str | None = None,
        detail: str = "",
        verified_at: datetime | None = None,
    ) -> ProviderConnection:
        """Move a connection's authorisation state after checking it.

        **`record_connection` only inserts**, so a connection created
        `never_granted` could never become `granted` — and a *Connect GitHub*
        flow that re-recorded instead would leave a second row behind on every
        attempt, since nothing makes `(project_id, provider)` unique.

        The uniqueness is deliberately still absent: two credentials for two
        accounts of the same provider is a real case. What was missing is the
        transition, and this is it.

        `verified_at` is set here because it is the only place that knows a
        check actually happened. `record_connection` always left it null, so
        `last_verified_at` existed on the row, the dataclass and nowhere else.
        """

        def operation(session: DbSession) -> ProviderConnection:
            row = session.get(ProviderConnectionRow, connection_id)
            if row is None or row.project_id != str(project_id):
                raise SetupNotFoundError(f"unknown connection: {connection_id}")
            # Validated by constructing the domain object first: `granted`
            # without an authorising person is refused there, and refusing
            # before the write is what keeps an invalid row from existing.
            updated = ProviderConnection(
                id=ConnectionId(connection_id),
                project_id=project_id,
                provider=Provider(row.provider),
                state=state,
                credential_reference=row.credential_reference,
                authorized_by=authorized_by if authorized_by is not None else row.authorized_by,
                detail=detail or row.detail or "",
                last_verified_at=verified_at,
            )
            row.state = state.value
            row.authorized_by = updated.authorized_by
            row.detail = updated.detail
            row.last_verified_at = verified_at
            session.flush()
            return updated

        return run_transaction(self._session_factory, operation)

    def authorization_for(
        self, project_id: ProjectId, connection_id: str | None
    ) -> AuthorizationState:
        """Return a connection's state, or `never_granted` if there is none.

        A missing connection is `never_granted` rather than an error: "you have
        not set this up" is the honest answer and it is actionable, where a
        lookup failure is neither.
        """

        if not connection_id:
            return AuthorizationState.NEVER_GRANTED

        def operation(session: DbSession) -> AuthorizationState:
            row = session.get(ProviderConnectionRow, connection_id)
            if row is None or row.project_id != str(project_id):
                return AuthorizationState.NEVER_GRANTED
            return AuthorizationState(row.state)

        return run_transaction(self._session_factory, operation)

    # -- targets -----------------------------------------------------------

    def register_target(
        self,
        project_id: ProjectId,
        provider: Provider,
        name: str,
        purpose: TargetPurpose = TargetPurpose.DELIVERABLE,
        configuration: dict[str, str] | None = None,
        connection_id: str | None = None,
        make_default: bool = False,
    ) -> PublicationTarget:
        """Register where a project may publish.

        `make_default` is explicit and defaults to `False`. A target that
        silently became the default would route the next publication somewhere
        nobody chose — the same failure as an override becoming permanent, one
        step earlier.
        """

        target = PublicationTarget(
            id=TargetId(str(uuid4())),
            project_id=project_id,
            provider=provider,
            name=name,
            purpose=purpose,
            is_default=make_default,
            configuration=configuration,
            connection_id=connection_id,
            created_at=self._clock(),
        )

        def operation(session: DbSession) -> PublicationTarget:
            session.add(
                PublicationTargetRow(
                    target_id=str(target.id),
                    project_id=str(project_id),
                    provider=provider.value,
                    name=name,
                    purpose=purpose.value,
                    is_default=make_default,
                    configuration=dict(configuration or {}),
                    connection_id=connection_id,
                    enabled=True,
                    created_at=target.created_at,
                )
            )
            try:
                session.flush()
            except IntegrityError as error:
                session.rollback()
                raise DefaultConflictError(
                    f"this project already has a default {purpose.value} target, or a "
                    f"target named {name!r}. At most one default per purpose is the "
                    f"point: two would make 'the default' ambiguous at the moment "
                    f"bytes are written."
                ) from error
            return target

        return run_transaction(self._session_factory, operation)

    def set_default(
        self,
        project_id: ProjectId,
        target_id: str,
        purpose: TargetPurpose = TargetPurpose.DELIVERABLE,
    ) -> PublicationTarget:
        """Point a purpose at a different target.

        **There was no way to do this.** `register_target(make_default=True)`
        raises once a default exists, so a project's output destination could be
        chosen once and never changed — which is not a destination, it is a
        commitment.

        Clearing and setting happen in **one transaction**, and the clear comes
        first, because `uq_publication_targets_default` is a partial unique
        index over `is_default`: setting before clearing collides with the row
        being replaced.

        The index still does the real work. Two concurrent calls both clear,
        both set, and one loses at flush — which is the behaviour
        `register_target` chose an index for in the first place, rather than a
        read-then-write that finds no default and races.
        """

        def operation(session: DbSession) -> PublicationTarget:
            row = session.get(PublicationTargetRow, target_id)
            if row is None or row.project_id != str(project_id):
                raise SetupNotFoundError(f"unknown publication target: {target_id}")
            if row.purpose != purpose.value:
                raise TargetError(
                    f"target {row.name!r} has purpose {row.purpose!r} and cannot become "
                    f"the default for {purpose.value!r}. A default routes one kind of "
                    f"output; making a snapshot target the deliverable default would "
                    f"send a package where a snapshot was expected."
                )
            current = session.scalars(
                select(PublicationTargetRow).where(
                    PublicationTargetRow.project_id == str(project_id),
                    PublicationTargetRow.purpose == purpose.value,
                    PublicationTargetRow.is_default.is_(True),
                )
            ).all()
            for existing in current:
                existing.is_default = False
            session.flush()

            row.is_default = True
            try:
                session.flush()
            except IntegrityError as error:  # pragma: no cover - concurrent callers
                session.rollback()
                raise DefaultConflictError(
                    f"another call set the default {purpose.value} target for this "
                    f"project while this one was running. Read the current default "
                    f"and decide again rather than retrying blind."
                ) from error
            return _as_target(row)

        return run_transaction(self._session_factory, operation)

    def targets(self, project_id: ProjectId) -> tuple[PublicationTarget, ...]:
        """Every registered target, available or not.

        Unavailable ones are included deliberately. A target that vanished when
        its authorisation expired would take the decision with it, and the
        person would be asked to choose a destination they already chose.
        """

        def operation(session: DbSession) -> tuple[PublicationTarget, ...]:
            rows = session.scalars(
                select(PublicationTargetRow)
                .where(PublicationTargetRow.project_id == str(project_id))
                .order_by(PublicationTargetRow.created_at)
            ).all()
            return tuple(_as_target(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def resolve_target(
        self,
        project_id: ProjectId,
        target_id: str | None = None,
        purpose: TargetPurpose = TargetPurpose.DELIVERABLE,
    ) -> PublicationTarget:
        """Return the named target, or the project's default for this purpose.

        No third option. A request that could name a destination inline would
        make every authorisation check advisory, so the only ways to say where
        something goes are a registered id and a registered default.
        """

        def operation(session: DbSession) -> PublicationTarget:
            if target_id:
                row = session.get(PublicationTargetRow, target_id)
                if row is None or row.project_id != str(project_id):
                    raise SetupNotFoundError(f"unknown publication target: {target_id}")
                return _as_target(row)
            row = session.scalars(
                select(PublicationTargetRow).where(
                    PublicationTargetRow.project_id == str(project_id),
                    PublicationTargetRow.purpose == purpose.value,
                    PublicationTargetRow.is_default.is_(True),
                )
            ).first()
            if row is None:
                raise SetupNotFoundError(
                    f"this project has no default {purpose.value} target and the "
                    f"request named none. Register one, or name a target_id."
                )
            return _as_target(row)

        return run_transaction(self._session_factory, operation)

    # -- readiness ---------------------------------------------------------

    def readiness(self, project_id: ProjectId) -> SetupReadiness:
        """What this project's configuration supports, apart from its knowledge.

        The gaps are derived from what is actually missing, and **none of them
        can be about knowledge**. A blocking gap here names an unmade choice or
        a missing authorisation; a project that knows very little and has a
        working local target blocks nothing.
        """

        configuration = self.configuration(project_id)
        questions = self.open_questions(project_id)
        registered = self.targets(project_id)

        gaps: list[SetupGap] = []
        for question in questions:
            if not question.blocks:
                continue
            gaps.append(
                SetupGap(
                    field_name=question.field_name,
                    capability=_capability_for(question.purpose),
                    blocking=True,
                    reason=question.question,
                    next_action=f"answer the setup question for {question.field_name}",
                )
            )

        if not registered:
            gaps.append(
                SetupGap(
                    field_name="default_publication_target",
                    capability="publication",
                    blocking=True,
                    reason="no publication target is registered for this project",
                    next_action="register a target, or publish locally by registering a local one",
                )
            )
        usable: list[PublicationTarget] = []
        if registered:
            for target in registered:
                authorization = self.authorization_for(project_id, target.connection_id)
                reason = target.unavailable_reason(authorization)
                if reason is None:
                    # Collected for `_state_for`, which must not call a project
                    # ready to publish on the strength of a target this same
                    # loop is about to report as unauthorised (`D-59`).
                    usable.append(target)
                    continue
                gaps.append(
                    SetupGap(
                        field_name=f"target:{target.name}",
                        capability="publication",
                        # Not blocking on its own: another target may work, and
                        # a per-target problem must not stop the project.
                        blocking=False,
                        reason=reason,
                        next_action=f"authorise or disable the target {target.name!r}",
                    )
                )

        return SetupReadiness(
            project_id=str(project_id),
            state=_state_for(configuration, questions, usable, gaps),
            gaps=tuple(gaps),
        )


def _capability_for(purpose: SetupPurpose) -> str:
    return {
        SetupPurpose.ACQUISITION: "acquisition",
        SetupPurpose.GENERATION: "generation",
        SetupPurpose.PUBLICATION: "publication",
        SetupPurpose.AUTHORIZATION: "publication",
    }[purpose]


def _state_for(
    configuration: ProjectConfiguration,
    questions: Sequence[SetupQuestion],
    usable_targets: Sequence[PublicationTarget],
    gaps: Sequence[SetupGap],
) -> SetupState:
    """Name where setup has got to.

    `sufficient_to_begin` is the answer for almost every new project, and it is
    not a deficiency — everything KAE does for a sparse project works from
    there.

    The absent publication target is deliberately **not** `needs_input`. Nobody
    has asked to publish, and reporting a project as needing input because of a
    decision it has not reached would make every new project look stuck. It is
    a gap against the publication capability, which is where a caller who
    actually wants to publish will read it.

    `gaps` is unused here and stays in the signature: the state is about what
    was established, and deriving it from the gaps would let one unreachable
    S3 target rename the whole project's condition.
    """

    if any(question.blocks for question in questions):
        return SetupState.NEEDS_INPUT
    # **Usable**, not merely registered. `ready_for_publication` documents three
    # conditions — a target exists, is authorised, and its provider is reachable
    # — and testing only the first told a project it could publish through a
    # connection nobody had granted, while the same response listed that target
    # as a gap (`D-59`). The verdict is the caller's, already computed for the
    # gaps, so nothing is decided twice.
    if usable_targets:
        return SetupState.READY_FOR_PUBLICATION
    if configuration.values:
        return SetupState.READY_FOR_GENERATION
    if questions:
        return SetupState.SUFFICIENT_TO_BEGIN
    return SetupState.NOT_STARTED


def _write_value(session: DbSession, project_id: ProjectId, configured: ConfiguredValue) -> None:
    row = session.get(ProjectConfigurationRow, (str(project_id), configured.field_name))
    if row is None:
        session.add(
            ProjectConfigurationRow(
                project_id=str(project_id),
                field_name=configured.field_name,
                value=configured.value,
                state=configured.state.value,
                evidence=configured.evidence,
                derived_from_knowledge_id=configured.derived_from_knowledge_id,
                confirmed_by=configured.confirmed_by,
                updated_at=configured.updated_at or datetime.now(UTC),
            )
        )
    else:
        row.value = configured.value
        row.state = configured.state.value
        row.evidence = configured.evidence
        row.derived_from_knowledge_id = configured.derived_from_knowledge_id
        row.confirmed_by = configured.confirmed_by
        row.updated_at = configured.updated_at or datetime.now(UTC)
    session.flush()


def _as_question(row: SetupQuestionRow) -> SetupQuestion:
    return SetupQuestion(
        id=SetupQuestionId(str(row.setup_question_id)),
        project_id=ProjectId(str(row.project_id)),
        purpose=SetupPurpose(row.purpose),
        question=row.question,
        field_name=row.field_name,
        blocking=row.blocking,
        suggested_answer=row.suggested_answer,
        suggestion_evidence=row.suggestion_evidence,
        policy=InferencePolicy(row.policy),
        disposition=Disposition(row.disposition),
        answer=row.answer,
        answered_by=row.answered_by,
        becomes_default=row.becomes_default,
        revisitable=row.revisitable,
        asked_at=row.asked_at,
        answered_at=row.answered_at,
    )


def _as_value(row: ProjectConfigurationRow) -> ConfiguredValue:
    return ConfiguredValue(
        field_name=row.field_name,
        value=row.value,
        state=ValueState(row.state),
        evidence=row.evidence,
        derived_from_knowledge_id=row.derived_from_knowledge_id,
        confirmed_by=row.confirmed_by,
        updated_at=row.updated_at,
    )


def _as_connection(row: ProviderConnectionRow) -> ProviderConnection:
    return ProviderConnection(
        id=ConnectionId(str(row.connection_id)),
        project_id=ProjectId(str(row.project_id)),
        provider=Provider(row.provider),
        state=AuthorizationState(row.state),
        credential_reference=row.credential_reference,
        authorized_by=row.authorized_by,
        last_verified_at=row.last_verified_at,
        detail=row.detail or "",
    )


def _as_target(row: PublicationTargetRow) -> PublicationTarget:
    configuration: dict[str, Any] = dict(row.configuration or {})
    return PublicationTarget(
        id=TargetId(str(row.target_id)),
        project_id=ProjectId(str(row.project_id)),
        provider=Provider(row.provider),
        name=row.name,
        purpose=TargetPurpose(row.purpose),
        is_default=row.is_default,
        configuration={str(k): str(v) for k, v in configuration.items()},
        connection_id=row.connection_id,
        enabled=row.enabled,
        created_at=row.created_at,
    )


__all__ = [
    "DefaultConflictError",
    "SetupNotFoundError",
    "SetupQuestionError",
    "SetupService",
    "TargetError",
]
