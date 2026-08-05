"""Recording and reading deliverables (N20).

The boundary this service holds is the one that makes a deliverable worth
having as a separate concept:

* it **records** an assembly that already happened — it does not assemble, and
  it does not decide what an assembly contains;
* it stores identity, ownership, the manifest, hashes, lifecycle, and
  provenance, and **never artifact bytes**;
* it performs **no publication and no storage side effect**. Rendering and
  writing to a destination is N21, and belongs to whoever owns the destination.

Everything here is immutable once written except the lifecycle. A deliverable
that could be edited would let "what we shipped" be rewritten after the fact,
which is the one claim it exists to preserve.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.assembly_service import ContextAssembly, describe_package
from kae_memory.domain.deliverables import (
    ORDERING_CONTRACT,
    ArtifactRecord,
    Deliverable,
    DeliverableId,
    DeliverableState,
    RenderInputs,
    StatementPin,
    ensure_deliverable_transition,
    identity_hash,
)
from kae_memory.domain.generation import GenerationMode, InclusionClass, qualifications
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.maturity import (
    SUGGESTED_FOR,
    AcceptedSufficiency,
    DeliverableQualification,
    Maturity,
)
from kae_memory.persistence.tables import DeliverableRow
from kae_memory.persistence.transactions import run_transaction


class DeliverableNotFoundError(LookupError):
    """No deliverable with that id exists in this project."""


class DeliverableService:
    """Record assembled outputs durably, and read them back."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        project_id: ProjectId,
        assembly: ContextAssembly,
        recorded_by: str | None = None,
        module_key: str | None = None,
        structural_fingerprint: str | None = None,
        qualification: DeliverableQualification | None = None,
        mode: GenerationMode = GenerationMode.BUILD,
        maturity: Maturity | None = None,
        accepted: AcceptedSufficiency | None = None,
    ) -> tuple[Deliverable, bool]:
        """Record one assembled output, returning it and whether it is new.

        Idempotent by content. Recording the same output twice returns the same
        deliverable, because two identical outputs are one deliverable recorded
        twice — minting a second id would report a change the project did not
        make, and a consumer diffing ids would see churn that means nothing.

        The knowledge revision is part of that identity. The same content at a
        later revision is a genuinely different claim: it says the project moved
        and the output did not.

        Enforced by the unique index rather than by a lookup first, because a
        lookup before an insert races and two concurrent recordings of one
        output would both find nothing.
        """

        manifest = assembly.manifest
        description = describe_package(assembly)
        # Derived here rather than by each adapter. N38 shipped the model and
        # nothing constructed one, so every recorded deliverable carried
        # `qualification: null` — the same "exists with no caller" defect this
        # repository has now hit twice.
        qualification = qualification or _describe_qualification(assembly, mode, maturity, accepted)
        scope = "module" if module_key else manifest.scope
        inputs = RenderInputs(
            purpose=manifest.purpose,
            scope=scope,
            include_proposed=manifest.include_proposed,
            ordering_contract=ORDERING_CONTRACT,
            generator_version=manifest.generator_version,
            package_schema=manifest.package_schema,
            knowledge_revision=manifest.knowledge_revision,
            module_key=module_key,
            structural_fingerprint=structural_fingerprint,
        )
        fingerprint = identity_hash(
            project_id,
            manifest.purpose,
            scope,
            module_key,
            manifest.knowledge_revision,
            manifest.content_hash,
        )

        def operation(session: DbSession) -> tuple[Deliverable, bool]:
            row = DeliverableRow(
                deliverable_id=str(uuid4()),
                project_id=str(project_id),
                identity_hash=fingerprint,
                purpose=manifest.purpose,
                scope=scope,
                module_key=module_key,
                knowledge_revision=manifest.knowledge_revision,
                content_hash=manifest.content_hash,
                generator_version=manifest.generator_version,
                state=DeliverableState.RECORDED.value,
                artifacts=[
                    {
                        "path": entry.path,
                        "area_key": entry.area_key,
                        "title": entry.title,
                        "statement_count": entry.statement_count,
                        "confirmed_count": entry.confirmed_count,
                        "content_hash": entry.content_hash,
                    }
                    for entry in description.artifacts
                ],
                manifest={
                    "package_schema": manifest.package_schema,
                    "statement_count": manifest.statement_count,
                    "traced_statements": manifest.traced_statements,
                    "confirmation_state": {
                        "confirmed": manifest.confirmation_state.confirmed,
                        "proposed": manifest.confirmation_state.proposed,
                        "contested": manifest.confirmation_state.contested,
                    },
                    "unresolved_critical_gaps": [
                        {"area_key": gap.area_key, "summary": gap.summary}
                        for gap in manifest.unresolved_critical_gaps
                    ],
                    "warnings": list(manifest.warnings),
                },
                source_knowledge=list(manifest.source_knowledge),
                # The pins and the inputs travel together or not at all. One
                # without the other is not partially reproducible; it is
                # unreproducible with extra detail.
                statement_pins=[
                    {"knowledge_id": knowledge_id, "version": version}
                    for knowledge_id, version in manifest.statement_pins
                ],
                render_inputs=inputs.as_dict(),
                qualification=qualification.as_dict() if qualification else None,
                # Inputs are always captured on this path, and an empty package
                # has nothing to pin while remaining reproducible. Deriving it
                # from the pins alone marked every empty package unprovable.
                publication_eligible=True,
                recorded_by=recorded_by,
                recorded_at=datetime.now(UTC),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = session.scalars(
                    select(DeliverableRow).where(DeliverableRow.identity_hash == fingerprint)
                ).first()
                if existing is None:  # pragma: no cover - only if the index changed
                    raise
                return _as_deliverable(existing), False
            return _as_deliverable(row), True

        return run_transaction(self._session_factory, operation)

    def list_for_project(
        self, project_id: ProjectId, states: Sequence[str] | None = None
    ) -> tuple[Deliverable, ...]:
        """Return a project's deliverables, newest first."""

        def operation(session: DbSession) -> tuple[Deliverable, ...]:
            statement = select(DeliverableRow).where(DeliverableRow.project_id == str(project_id))
            if states:
                statement = statement.where(DeliverableRow.state.in_(list(states)))
            rows = session.scalars(statement.order_by(DeliverableRow.recorded_at.desc())).all()
            return tuple(_as_deliverable(row) for row in rows)

        return run_transaction(self._session_factory, operation)

    def get(self, project_id: ProjectId, deliverable_id: str) -> Deliverable:
        """Return one deliverable, scoped to its project.

        Scoped deliberately: an id alone would let a caller who guessed an
        identifier read another project's record, and the project is the
        boundary every other read respects.
        """

        def operation(session: DbSession) -> Deliverable:
            return _as_deliverable(_require(session, project_id, deliverable_id))

        return run_transaction(self._session_factory, operation)

    def supersede(
        self, project_id: ProjectId, deliverable_id: str, replacement_id: str
    ) -> Deliverable:
        """Mark a deliverable replaced by a later one.

        The record survives. What was shipped stays readable, because the
        question a deliverable answers is historical and a deleted answer
        answers nothing.
        """

        def operation(session: DbSession) -> Deliverable:
            row = _require(session, project_id, deliverable_id)
            replacement = _require(session, project_id, replacement_id)
            ensure_deliverable_transition(DeliverableState(row.state), DeliverableState.SUPERSEDED)
            row.state = DeliverableState.SUPERSEDED.value
            row.superseded_by = str(replacement.deliverable_id)
            session.flush()
            return _as_deliverable(row)

        return run_transaction(self._session_factory, operation)

    def withdraw(self, project_id: ProjectId, deliverable_id: str, reason: str) -> Deliverable:
        """Mark a deliverable as one the project no longer stands behind.

        Distinct from superseded, which names what replaced it. Withdrawn says
        there is no replacement, and collapsing the two would leave a reader
        unable to tell "there is a newer one" from "do not use this".
        """

        def operation(session: DbSession) -> Deliverable:
            row = _require(session, project_id, deliverable_id)
            ensure_deliverable_transition(DeliverableState(row.state), DeliverableState.WITHDRAWN)
            row.state = DeliverableState.WITHDRAWN.value
            manifest = dict(row.manifest or {})
            manifest["withdrawn_reason"] = reason
            row.manifest = manifest
            session.flush()
            return _as_deliverable(row)

        return run_transaction(self._session_factory, operation)


def _require(session: DbSession, project_id: ProjectId, deliverable_id: str) -> DeliverableRow:
    row = session.scalars(
        select(DeliverableRow).where(
            DeliverableRow.project_id == str(project_id),
            DeliverableRow.deliverable_id == deliverable_id,
        )
    ).first()
    if row is None:
        raise DeliverableNotFoundError(f"no deliverable {deliverable_id!r} in this project")
    return row


def _as_deliverable(row: DeliverableRow) -> Deliverable:
    artifacts: list[dict[str, Any]] = list(row.artifacts or [])
    return Deliverable(
        id=DeliverableId(str(row.deliverable_id)),
        project_id=ProjectId(str(row.project_id)),
        purpose=row.purpose,
        scope=row.scope,
        knowledge_revision=row.knowledge_revision,
        content_hash=row.content_hash,
        artifacts=tuple(
            ArtifactRecord(
                path=str(entry.get("path", "")),
                area_key=str(entry.get("area_key", "")),
                title=str(entry.get("title", "")),
                statement_count=int(entry.get("statement_count", 0)),
                confirmed_count=int(entry.get("confirmed_count", 0)),
                content_hash=str(entry.get("content_hash", "")),
            )
            for entry in artifacts
        ),
        state=DeliverableState(row.state),
        module_key=row.module_key,
        generator_version=row.generator_version or "",
        source_knowledge=tuple(row.source_knowledge or []),
        recorded_by=row.recorded_by,
        recorded_at=row.recorded_at,
        superseded_by=row.superseded_by,
        manifest=dict(row.manifest or {}),
        statement_pins=tuple(
            StatementPin(
                knowledge_id=str(pin.get("knowledge_id", "")),
                version=int(pin.get("version", 0)),
            )
            for pin in (row.statement_pins or [])
            if pin.get("knowledge_id") and int(pin.get("version", 0)) >= 1
        ),
        render_inputs=RenderInputs.from_dict(dict(row.render_inputs or {})),
        qualification=dict(row.qualification) if row.qualification else None,
    )


def _describe_qualification(
    assembly: ContextAssembly,
    mode: GenerationMode,
    maturity: Maturity | None,
    accepted: AcceptedSufficiency | None,
) -> DeliverableQualification:
    """Describe what this package is for, from what it actually contains.

    Counted from the assembly rather than asserted by a caller: a package that
    could claim its own confirmation split would be able to claim a better one
    than it has.
    """

    state = assembly.manifest.confirmation_state
    present: set[InclusionClass] = set()
    if state.confirmed:
        present.add(InclusionClass.CONFIRMED)
    if state.proposed:
        present.add(InclusionClass.PROPOSED)
    if state.contested:
        present.add(InclusionClass.DISPUTED)

    return DeliverableQualification(
        maturity=maturity or SUGGESTED_FOR[mode],
        mode=mode,
        confirmed_count=state.confirmed,
        unconfirmed_count=state.proposed,
        contradictions=tuple(gap.summary for gap in assembly.manifest.unresolved_critical_gaps),
        limitations=tuple(assembly.manifest.warnings),
        qualifications=qualifications(mode, frozenset(present)),
        accepted=accepted,
    )
