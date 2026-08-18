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

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.source_dispositions import ensure_source_disposition
from kae_memory.persistence.tables import AgentRunRow, ProjectSourceRow
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
    retired_at: datetime | None = None
    """When somebody stopped KAE reading this source. `None` means nobody has.

    `D-254`: retirement is orthogonal to `state`, not further along it. A source
    can be retired and pinned at once, and a reader that wants *what was this
    fixed to* still gets an answer after somebody stopped reading it.
    """
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_retired(self) -> bool:
        """Whether KAE has been told to stop reading this source."""

        return self.retired_at is not None

    @property
    def is_pinned(self) -> bool:
        """Whether this source names an immutable revision.

        A branch moves and a commit does not, so evidence drawn from an unpinned
        source cannot be rechecked against what it actually said.
        """

        return bool(self.pinned_revision)


@dataclass(frozen=True, slots=True)
class SourceMaterial:
    """One source, its disposition, and how much stored text stands under it."""

    source_id: str
    kind: str
    location: str
    disposition: str | None
    documents: int
    """Distinct documents ingested naming this source — what a person chose."""
    stored_bodies: int
    """Copies of text those choices produced, one per ingestion run.

    The number `ADR-0004` step 3 is about. A report giving only `documents`
    would understate a large file by however many chunks it split into, and the
    chunk is the unit a body is stored in.
    """


@dataclass(frozen=True, slots=True)
class MaterialReport:
    """What material a retention decision would apply to, before any is removed.

    Shaped after `ProjectDeletionService.plan` and for its reason: the counts
    exist so somebody can sanity-check the scale of a decision rather than trust
    that it lands where they meant it to.
    """

    sources: tuple[SourceMaterial, ...]
    unattributed_documents: int
    """Documents ingested naming no source, and therefore governed by nothing.

    Every document ingested before the link existed (`D-164`) is here, as is
    every pasted one — which correctly has no source. Kept as its own number
    rather than folded into a total or dropped, because material no disposition
    can reach is the part a person most needs told.
    """
    unattributed_bodies: int


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
                # **Registering a retired source brings it back** (`D-254`).
                # Identity is `(project, kind, location)`, so a retired row would
                # otherwise make adding that repository again impossible — the
                # unique constraint refuses a second row and the first is one
                # nobody reads. Retiring a source must not permanently forbid it.
                existing.retired_at = None
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

    def material(self, project_id: ProjectId) -> MaterialReport:
        """How much stored text stands behind each source, and what it was classified as.

        The one lookup `ADR-0004` step 3 needs and nothing provided: a run named
        its source in `input_context` (`D-164`) and the disposition lives on
        `project_sources`, with no code joining the two — so no reader could
        answer *what would a decision about this repository apply to*.

        **This reports and does nothing.** No body is discarded, no disposition
        is enforced, and a source classified `ephemeral` here is counted exactly
        like one classified `memory`. What to do about the numbers is `D-169`,
        which is the owner's.

        Registered sources with no material are listed with zeroes rather than
        omitted: a repository somebody connected and never ingested is a real
        answer, and reads differently from one this query failed to see.
        """

        source_key = AgentRunRow.input_context["source_id"].astext
        # The key `IngestionService.ingest_document` writes on every run it
        # creates. Its presence is what distinguishes an ingestion run from a
        # conversation one, which has no body to retain.
        document_key = AgentRunRow.input_context["document"].astext

        def operation(session: DbSession) -> MaterialReport:
            counted = session.execute(
                select(
                    source_key.label("source_id"),
                    func.count(func.distinct(document_key)).label("documents"),
                    func.count().label("bodies"),
                )
                .where(
                    AgentRunRow.project_id == str(project_id),
                    document_key.isnot(None),
                )
                .group_by(source_key)
            ).all()
            # A run naming no source groups under NULL, which is the
            # unattributed bucket rather than a row to drop.
            by_source = {row.source_id: (row.documents, row.bodies) for row in counted}
            unattributed = by_source.get(None, (0, 0))

            rows = session.scalars(
                select(ProjectSourceRow)
                .where(ProjectSourceRow.project_id == str(project_id))
                .order_by(ProjectSourceRow.created_at, ProjectSourceRow.source_id)
            ).all()
            materials = []
            for row in rows:
                documents, bodies = by_source.get(row.source_id, (0, 0))
                materials.append(
                    SourceMaterial(
                        source_id=row.source_id,
                        kind=row.kind,
                        location=row.location,
                        disposition=row.disposition,
                        documents=documents,
                        stored_bodies=bodies,
                    )
                )
            return MaterialReport(
                sources=tuple(materials),
                unattributed_documents=unattributed[0],
                unattributed_bodies=unattributed[1],
            )

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

    def stop_reading(self, project_id: ProjectId, source_id: str) -> ProjectSource:
        """Stop KAE reading this source, without erasing what it taught KAE.

        Named for what the control says rather than for the column it sets.
        `retire` was the first name and collided: `test_no_unreachable_capability`
        resolves reachability by bare method name, so a second `retire` anywhere
        in the application layer made `AssumptionService.retire` — genuinely
        unreachable — read as called. The collision is recorded as a finding; the
        rename is not a workaround for it, since *stop reading* is the sentence
        the surface shows and `retire` was the database's word, not a person's.

        `D-230` is the owner's ruling and `D-254` is why this is not a row
        deletion. What the source already produced stays, and stays attributed:
        `D-164` carries `source_id` on every ingestion run and `material`
        (`D-170`) groups documents by it, so deleting the row would leave the
        knowledge and destroy the answer to where it came from.

        **Idempotent, and the first retirement is the one that counts.** Retiring
        an already-retired source keeps the original timestamp rather than
        moving it — *when did we stop reading this* has one true answer, and a
        repeated call is a caller that lost its response, not a second decision.
        """

        def operation(session: DbSession) -> ProjectSource:
            row = _require(session, project_id, source_id)
            if row.retired_at is None:
                row.retired_at = datetime.now(UTC)
                row.updated_at = datetime.now(UTC)
                session.flush()
            return _as_source(row)

        return run_transaction(self._session_factory, operation)

    def resume_reading(self, project_id: ProjectId, source_id: str) -> ProjectSource:
        """Read this source again.

        Retirement is reversible on purpose (`D-254`). The alternative is not,
        and an irreversible control is how a mistake on a page becomes permanent.

        Nothing about the source's progression is touched: it comes back at the
        `state` it was left at, because stopping reading a pinned repository
        never unpinned it.
        """

        def operation(session: DbSession) -> ProjectSource:
            row = _require(session, project_id, source_id)
            if row.retired_at is not None:
                row.retired_at = None
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
        retired_at=row.retired_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
