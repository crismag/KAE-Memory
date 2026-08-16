"""Where a project's material comes from, durably (`D-21`, `AUD-005`).

Studio configures sources — a repository, its include and exclude paths, a size
ceiling, a pinned revision — and held every one of them in a process dictionary.
A deploy erased them. `ADR-0004` ruled that KAE-Memory owns the source
reference; this is the service over that record.

## What this is not

**Not the content.** A source names material and never holds it. The ruling
exists to stop a repository being copied wholesale into this database, and a
service that stored file bodies here would defeat it while looking like
progress.

**Not analysis.** Nothing here reads a repository, resolves a revision, or
decides whether a source is reachable. Studio does that against the provider and
records the outcome; this records what it was told. Two systems with an opinion
about one lifecycle is how they come to disagree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.source_dispositions import ensure_source_disposition
from kae_memory.persistence.tables import ProjectSourceRow
from kae_memory.persistence.transactions import run_transaction


class SourceNotFoundError(LookupError):
    """No source with that identifier exists in this project."""


@dataclass(frozen=True, slots=True)
class ProjectSource:
    """One place a project's material comes from."""

    source_id: str
    project_id: str
    kind: str
    location: str
    state: str
    connection_id: str | None = None
    scope: Mapping[str, Any] = field(default_factory=dict)
    pinned_revision: str | None = None
    digest: str | None = None
    disposition: str | None = None
    """One of `ADR-0004`'s five, once somebody decides.

    `None` means **nobody has classified this source**, which is a different
    thing from classifying it as kept. The distinction is the reason there is no
    default.
    """
    detail: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_pinned(self) -> bool:
        """Whether this source names an immutable revision.

        A branch moves and a commit does not, so evidence drawn from an unpinned
        source cannot be rechecked against what it actually said.
        """

        return bool(self.pinned_revision)


class SourceService:
    """Register sources, record what happened to them, and read them back."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    def register(
        self,
        project_id: ProjectId,
        kind: str,
        location: str,
        state: str,
        connection_id: str | None = None,
        scope: Mapping[str, Any] | None = None,
        disposition: str | None = None,
    ) -> ProjectSource:
        """Record where material comes from, or return the source already there.

        Idempotent by `(kind, location)`, like project and module creation and
        for the same reason: a caller that loses its response can retry without
        first asking whether it succeeded. Registering the same repository twice
        is one source registered twice.

        A re-registration **does not** reset the pin. Somebody who re-adds a
        repository they already pinned has said nothing about the revision, and
        silently unpinning it would discard the one field that makes the
        evidence recheckable.
        """

        kind = kind.strip()
        location = location.strip()
        if not kind:
            raise DomainInvariantError("a source needs a kind")
        if not location:
            raise DomainInvariantError("a source needs a location")
        if not state.strip():
            raise DomainInvariantError("a source needs a state")
        # The same set as `classify`. A registration that could name a
        # disposition the classify path refuses would be the free-text column
        # again, reachable by the other door.
        recorded = None if disposition is None else ensure_source_disposition(disposition).value

        def operation(session: DbSession) -> ProjectSource:
            existing = session.scalars(
                select(ProjectSourceRow).where(
                    ProjectSourceRow.project_id == str(project_id),
                    ProjectSourceRow.kind == kind,
                    ProjectSourceRow.location == location,
                )
            ).first()
            now = datetime.now(UTC)
            if existing is not None:
                # Scope and connection are re-stated by the caller and may have
                # changed; the pin is not, and is left alone.
                existing.scope = dict(scope or existing.scope or {})
                existing.connection_id = connection_id or existing.connection_id
                existing.state = state.strip()
                if recorded is not None:
                    existing.disposition = recorded
                existing.updated_at = now
                session.flush()
                return _as_source(existing)

            row = ProjectSourceRow(
                source_id=str(uuid4()),
                project_id=str(project_id),
                kind=kind,
                location=location,
                connection_id=connection_id,
                scope=dict(scope or {}),
                state=state.strip(),
                pinned_revision=None,
                digest=None,
                disposition=recorded,
                detail="",
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            return _as_source(row)

        return run_transaction(self._session_factory, operation)

    def sources(self, project_id: ProjectId) -> tuple[ProjectSource, ...]:
        """Every source this project has, oldest first."""

        def operation(session: DbSession) -> tuple[ProjectSource, ...]:
            rows = session.scalars(
                select(ProjectSourceRow)
                .where(ProjectSourceRow.project_id == str(project_id))
                .order_by(ProjectSourceRow.created_at, ProjectSourceRow.source_id)
            ).all()
            return tuple(_as_source(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def get(self, project_id: ProjectId, source_id: str) -> ProjectSource:
        def operation(session: DbSession) -> ProjectSource:
            return _as_source(_require(session, project_id, source_id))

        return run_transaction(self._session_factory, operation)

    def record_state(
        self,
        project_id: ProjectId,
        source_id: str,
        state: str,
        detail: str = "",
    ) -> ProjectSource:
        """Record what Studio observed against the provider.

        `detail` carries the provider's own words for a refusal or an
        unreachable host. Paraphrasing it here would produce a reason nobody can
        act on, and the caller is the only party that saw the original.
        """

        if not state.strip():
            raise DomainInvariantError("a source needs a state")

        def operation(session: DbSession) -> ProjectSource:
            row = _require(session, project_id, source_id)
            row.state = state.strip()
            row.detail = detail
            row.updated_at = datetime.now(UTC)
            session.flush()
            return _as_source(row)

        return run_transaction(self._session_factory, operation)

    def pin(
        self,
        project_id: ProjectId,
        source_id: str,
        revision: str,
        digest: str | None = None,
        state: str = "pinned",
    ) -> ProjectSource:
        """Fix this source to an immutable revision.

        The point of the whole record. A branch moves; a commit does not, and a
        claim drawn from *"the main branch"* cannot be rechecked against what
        the branch actually said at the time.
        """

        if not revision.strip():
            raise DomainInvariantError("a pin needs a revision")

        def operation(session: DbSession) -> ProjectSource:
            row = _require(session, project_id, source_id)
            row.pinned_revision = revision.strip()
            row.digest = digest
            row.state = state.strip()
            row.updated_at = datetime.now(UTC)
            session.flush()
            return _as_source(row)

        return run_transaction(self._session_factory, operation)

    def classify(self, project_id: ProjectId, source_id: str, disposition: str) -> ProjectSource:
        """Record where this source's material is to live (`ADR-0004`).

        **Stored, and acted on by nothing yet.** The five dispositions gate
        ingestion at volume, and making `EPHEMERAL` actually discard content is
        behaviour this does not implement. Recording the decision is worth doing
        first — reclassifying real data afterwards is the expensive order — but
        it must not be mistaken for the rule being enforced.

        `D-162`: the set is closed even though nothing reads it. A free-text
        column hands its first reader every value ever written to it, and the
        cheap moment to refuse a misspelt `EPHEMERAL` is before one exists.
        """

        recorded = ensure_source_disposition(disposition)

        def operation(session: DbSession) -> ProjectSource:
            row = _require(session, project_id, source_id)
            row.disposition = recorded.value
            row.updated_at = datetime.now(UTC)
            session.flush()
            return _as_source(row)

        return run_transaction(self._session_factory, operation)


def _require(session: DbSession, project_id: ProjectId, source_id: str) -> ProjectSourceRow:
    row = session.scalars(
        select(ProjectSourceRow).where(
            ProjectSourceRow.project_id == str(project_id),
            ProjectSourceRow.source_id == source_id,
        )
    ).first()
    if row is None:
        # Scoped by project, not looked up by id alone: a source id that
        # resolved across projects would let a caller naming their own project
        # read somebody else's configuration.
        raise SourceNotFoundError(source_id)
    return row


def _as_source(row: ProjectSourceRow) -> ProjectSource:
    return ProjectSource(
        source_id=row.source_id,
        project_id=row.project_id,
        kind=row.kind,
        location=row.location,
        state=row.state,
        connection_id=row.connection_id,
        scope=dict(row.scope or {}),
        pinned_revision=row.pinned_revision,
        digest=row.digest,
        disposition=row.disposition,
        detail=row.detail,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
