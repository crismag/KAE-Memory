"""Run requirement synthesis: extracted `requirement v1` rows to a requirement model.

`06-REQUIREMENTS.md`, and `D-129`/`D-131`. The extracted rows stay where they are
and keep their lifecycle. What this adds is a `synthesized_objects` row per
requirement, the acceptance criteria a **person** wrote against them, and one
idempotent change event.

## Two storage questions, answered opposite ways (`D-131`)

The requirement needs no table. Its kind, its verifiability, its capability
areas and whether it is implementation-ready are all derived from the statement
and the criteria, so a column beside the object would be `D-125`'s second copy
of a state, free to disagree after a rerun.

The **criterion** needs one, because nothing else in the estate holds it. It is
not derived — refusing to derive it is `D-129`'s content — and no
``KnowledgeKind`` names one. It is a sentence somebody wrote against a
requirement, doc 06's *Add acceptance criteria* action, so it lands in
``acceptance_criteria``.

## The run writes no criteria at all

Not one, ever. A criterion KAE generated would make its requirement
implementation-ready by the act of synthesising it, which is `ADR-0008`'s
objection in one line. So ``synthesize`` reads criteria and never writes them,
and ``record_criterion`` is only reached by a person's request.

## Nothing here becomes attention

An unready requirement is a state of the model, not an interruption — one
interrupt per unready requirement is the review queue `ADR-0007` exists to
remove, under a new name (`D-125`).

## Rerunning changes nothing

Identity is the statement, normalised, for the objects and
``(requirement, wording)`` for the criteria. Unchanged evidence produces the
same keys and therefore the same rows, and the run's event replays instead of
being recorded again.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.goal_synthesis_service import identity_key_for
from kae_memory.application.synthesis_service import SynthesisService
from kae_memory.domain.errors import KnowledgeNotFoundError
from kae_memory.domain.identifiers import (
    AcceptanceCriterionId,
    KnowledgeItemId,
    ProjectId,
    SynthesizedObjectId,
)
from kae_memory.domain.lifecycle import RETRIEVABLE, LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesis import (
    AcceptanceCriterionRecord,
    ChangeTrigger,
    EvidenceBindingKind,
)
from kae_memory.domain.synthesizers.requirements import (
    AcceptanceCriterion,
    RequirementCandidate,
    StatementKind,
    Verifiability,
    plan_requirement_model,
)
from kae_memory.persistence.readiness_repositories import bump_knowledge_revision
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.synthesis_repository import SynthesisRepository
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class SynthesizedRequirement:
    """One requirement as the run wrote it, with the reading behind it."""

    object_id: SynthesizedObjectId
    statement: str
    verifiability: Verifiability
    capability_areas: tuple[str, ...]
    accepted: bool
    criteria: tuple[str, ...]
    implementation_ready: bool


@dataclass(frozen=True, slots=True)
class ReclassifiedStatement:
    """A statement separated out of the requirement list, and named."""

    statement: str
    kind: StatementKind


@dataclass(frozen=True, slots=True)
class RequirementSplit:
    """A compound requirement named in halves, applied to nothing."""

    statement: str
    first: str
    second: str
    basis: str


@dataclass(frozen=True, slots=True)
class RequirementSynthesisReport:
    """What one run concluded, including what it separated out and did not apply."""

    project_id: ProjectId
    replayed: bool
    considered: int
    requirements: tuple[SynthesizedRequirement, ...]

    reclassified: tuple[ReclassifiedStatement, ...]
    """Doc 06's mixed list, separated rather than filtered and reported by name."""

    splits: tuple[RequirementSplit, ...]
    """Compound requirements, named in halves. Nothing is applied (`D-129`)."""

    @property
    def by_verifiability(self) -> dict[Verifiability, int]:
        """How the run read each requirement's testability. Derived, never stored."""

        return dict(Counter(one.verifiability for one in self.requirements))

    @property
    def implementation_ready(self) -> int:
        """How many are ready. Zero until somebody writes criteria, and that is the point."""

        return sum(1 for one in self.requirements if one.implementation_ready)


class RequirementSynthesisService:
    """Turn requirement evidence into the project's requirement model."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> RequirementSynthesisReport:
        """Plan and persist the requirement model for one project."""

        started = datetime.now(UTC)
        candidates, members_of = self._read(project_id)
        criteria = self._criteria_by_statement(project_id)
        plan = plan_requirement_model(
            candidates,
            tuple(
                AcceptanceCriterion(requirement_key=key, statement=statement)
                for key, statements in sorted(criteria.items())
                for statement in statements
            ),
        )

        summary = (
            f"requirements: {len(plan.requirements)} requirements, "
            f"{len(plan.reclassified)} reclassified, {len(plan.splits)} split, "
            f"{len(plan.ready)} implementation-ready"
        )
        key = (
            idempotency_key or f"requirement-synthesis:{len(candidates)}:{len(plan.requirements)}"
        ).strip()

        requirements: list[SynthesizedRequirement] = []
        for planned in plan.requirements:
            statement = planned.candidate.statement
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.REQUIREMENT.value,
                identity_key=identity_key_for(statement),
                title=statement,
                statement=statement,
            )
            requirements.append(
                SynthesizedRequirement(
                    object_id=obj.id,
                    statement=statement,
                    verifiability=planned.verifiability,
                    capability_areas=planned.capability_areas,
                    accepted=planned.candidate.accepted,
                    criteria=planned.criteria,
                    implementation_ready=planned.implementation_ready,
                )
            )
            for member in members_of[planned.candidate.canonical_key]:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )

        event = self._synthesis.record_change(
            project_id,
            idempotency_key=key,
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )

        return RequirementSynthesisReport(
            project_id=project_id,
            replayed=event.created_at is not None and event.created_at < started,
            considered=len(candidates),
            requirements=tuple(requirements),
            reclassified=tuple(
                ReclassifiedStatement(statement=one.statement, kind=one.kind)
                for one in plan.reclassified
            ),
            splits=tuple(
                RequirementSplit(
                    statement=next(
                        requirement.candidate.statement
                        for requirement in plan.requirements
                        if requirement.candidate.canonical_key == split.requirement_key
                    ),
                    first=split.first,
                    second=split.second,
                    basis=split.basis,
                )
                for split in plan.splits
            ),
        )

    def record_criterion(
        self, project_id: ProjectId, requirement_object_id: SynthesizedObjectId, statement: str
    ) -> AcceptanceCriterionRecord:
        """Record what one person says *done* looks like for one requirement.

        **Only a person reaches this.** No synthesis path calls it, because a
        criterion KAE wrote would make its requirement implementation-ready by
        the act of synthesising it (`D-131`).

        Idempotent by ``(requirement, wording)``, normalised the way every other
        identity in synthesis is normalised, so re-adding the same criterion
        updates its wording rather than stacking a second row.
        """

        statement = statement.strip()
        identity = identity_key_for(statement)

        def operation(session: DbSession) -> AcceptanceCriterionRecord:
            repo = SynthesisRepository(session)
            requirement = repo.get_object(requirement_object_id)
            if requirement is None or requirement.project_id != project_id:
                raise KnowledgeNotFoundError(f"unknown synthesized object: {requirement_object_id}")
            if requirement.domain != KnowledgeKind.REQUIREMENT.value:
                raise KnowledgeNotFoundError(
                    f"not a requirement: {requirement_object_id} is a {requirement.domain}"
                )
            now = datetime.now(UTC)
            existing = repo.get_criterion(requirement_object_id, identity)
            if existing is not None:
                if existing.statement == statement:
                    return existing
                updated = AcceptanceCriterionRecord(
                    id=existing.id,
                    project_id=existing.project_id,
                    requirement_object_id=existing.requirement_object_id,
                    identity_key=existing.identity_key,
                    statement=statement,
                    created_at=existing.created_at,
                    updated_at=now,
                )
                repo.save_criterion(updated)
                bump_knowledge_revision(session, project_id)
                return updated
            record = AcceptanceCriterionRecord(
                id=AcceptanceCriterionId(str(uuid4())),
                project_id=project_id,
                requirement_object_id=requirement_object_id,
                identity_key=identity,
                statement=statement,
                created_at=now,
                updated_at=now,
            )
            repo.save_criterion(record)
            bump_knowledge_revision(session, project_id)
            return record

        return run_transaction(self._session_factory, operation)

    def list_criteria(
        self, project_id: ProjectId, requirement_object_id: SynthesizedObjectId | None = None
    ) -> tuple[AcceptanceCriterionRecord, ...]:
        """The project's acceptance criteria, optionally for one requirement.

        Empty is the ordinary answer and doc 06's finding: a requirement nobody
        has said *done* for is a candidate, not something to build to.
        """

        def operation(session: DbSession) -> tuple[AcceptanceCriterionRecord, ...]:
            return SynthesisRepository(session).list_criteria(project_id, requirement_object_id)

        return run_transaction(self._session_factory, operation)

    def _criteria_by_statement(self, project_id: ProjectId) -> dict[str, list[str]]:
        """Stored criteria, keyed by the identity of the requirement they belong to.

        The domain layer keys criteria by the candidate's canonical key, which is
        the normalised statement — the same key ``put_object`` stored the
        requirement under. So the join is by identity key and needs no second
        mapping to drift.
        """

        by_key: dict[str, list[str]] = {}

        def operation(session: DbSession) -> dict[str, list[str]]:
            repo = SynthesisRepository(session)
            objects = {obj.id: obj for obj in repo.list_objects(project_id)}
            for record in repo.list_criteria(project_id):
                requirement = objects.get(record.requirement_object_id)
                if requirement is None:
                    continue
                by_key.setdefault(requirement.identity_key, []).append(record.statement)
            return by_key

        return run_transaction(self._session_factory, operation)

    def _read(
        self, project_id: ProjectId
    ) -> tuple[tuple[RequirementCandidate, ...], dict[str, tuple[KnowledgeItemId, ...]]]:
        """Read requirement evidence, grouping identical wordings.

        A candidate counts as accepted when **any** of its rows was validated: a
        person who confirmed one wording of a requirement confirmed the
        requirement. Wording confers nothing — *must* and *shall* are the grammar
        of the sentence somebody wrote down (`D-129`).
        """

        def operation(
            session: DbSession,
        ) -> tuple[tuple[RequirementCandidate, ...], dict[str, tuple[KnowledgeItemId, ...]]]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            items = knowledge.list_for_project(project_id, None)

            grouped: dict[str, list[KnowledgeItemId]] = {}
            statement_of: dict[str, str] = {}
            accepted: set[str] = set()
            for item in items:
                if item.lifecycle not in RETRIEVABLE:
                    continue
                if item.kind != KnowledgeKind.REQUIREMENT.value:
                    continue
                content = item.current_version.content
                key = identity_key_for(content)
                if not key:
                    continue
                grouped.setdefault(key, []).append(item.id)
                statement_of.setdefault(key, content)
                if item.lifecycle is LifecycleState.VALIDATED:
                    accepted.add(key)

            candidates = tuple(
                RequirementCandidate(
                    members=tuple(str(member) for member in members),
                    canonical_key=key,
                    statement=statement_of[key],
                    accepted=key in accepted,
                )
                for key, members in sorted(grouped.items())
            )
            members_of = {key: tuple(members) for key, members in grouped.items()}
            return candidates, members_of

        return run_transaction(self._session_factory, operation)
