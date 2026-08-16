"""Run assumption synthesis: extracted `assumption v1` rows to the project's beliefs.

`05-ASSUMPTIONS.md`, and `D-135`/`D-136`. The extracted rows stay where they are
and keep their lifecycle. What this adds is a `synthesized_objects` row per
project assumption and one idempotent change event.

## There is no assumption table (`D-136`)

`D-135` ruled that doc 05's seven lifecycle states are five that already exist.
Stored, that ruling leaves nothing for a table to hold: the object's
`(lifecycle, authority)` pair *is* the assumption's state, its consequence
domain is a pure function of the statement, and *material-needs-validation* is
derived from those two. A column beside any of them would be a second copy free
to disagree after a rerun — `D-125`, for the fourth time.

## The run writes no evidence role (`D-136`)

`Separated` names the role each classified-out row plays — `noise` for
scaffolding, `resolved` for what the project already knows — and
`knowledge_evidence_roles` is exactly the store for it. It is deliberately not
written here. `_persist_roles` in reconciliation skips any row already marked
`noise`, so a `noise` write is a permanent opt-out from role maintenance decided
by one regex; and an `EvidenceRoleRecord` names no author, so a later run cannot
distinguish its own stale write from a person's judgement and therefore cannot
correct it. The separation is reported in full instead, and the role is applied
through `PUT .../knowledge/{id}/evidence-role` by whoever wants it applied.

## Nothing here becomes attention

Doc 05: *"Do not preserve stale assumptions as permanent review items."* One
interrupt per unvalidated assumption is the review queue `ADR-0007` exists to
remove, under a new name. Needing validation is a state a reader sorts by.

## Rerunning changes nothing

Identity is the statement, normalised. Unchanged evidence produces the same
identity keys and therefore the same rows, and the run's event replays instead
of being recorded again.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.goal_synthesis_service import identity_key_for
from kae_memory.application.synthesis_service import SynthesisService
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId, SynthesizedObjectId
from kae_memory.domain.lifecycle import RETRIEVABLE, LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesis import Authority, ChangeTrigger, EvidenceBindingKind
from kae_memory.domain.synthesizers.assumptions import (
    AssumptionCandidate,
    ConsequenceDomain,
    plan_assumption_model,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class SynthesizedAssumption:
    """One project assumption as the run wrote it, with what it costs if wrong."""

    object_id: SynthesizedObjectId
    statement: str
    consequence: ConsequenceDomain
    settled: bool
    needs_validation: bool
    basis: str


@dataclass(frozen=True, slots=True)
class AssumptionSynthesisReport:
    """What one run concluded, including everything it classified out."""

    project_id: ProjectId
    replayed: bool
    """Whether this run's change event was already on record before it started."""

    considered: int
    assumptions: tuple[SynthesizedAssumption, ...]

    scaffolding: tuple[tuple[str, str], ...]
    """Interpretation assumptions, each with why it is not a project belief.

    Reported rather than dropped: a silent filter is indistinguishable from an
    extractor that never produced them, and doc 05's complaint is precisely that
    nobody can see which rows are which.
    """

    resolved: tuple[tuple[str, str], ...]
    """Assumptions the project already established, each with the statement that did it."""

    needing_validation: tuple[tuple[str, str], ...]
    """Doc 05's *material-needs-validation*, derived and stored nowhere.

    A state a reader sorts by, and deliberately not the attention queue
    (`D-135`).
    """

    @property
    def by_consequence(self) -> dict[ConsequenceDomain, int]:
        """What the run said would change if each assumption were wrong."""

        return dict(Counter(assumption.consequence for assumption in self.assumptions))


class AssumptionSynthesisService:
    """Turn assumption evidence into project beliefs and the reading behind each."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> AssumptionSynthesisReport:
        """Plan and persist the assumption model for one project."""

        started = datetime.now(UTC)
        candidates, members_of, established = self._read(project_id)
        plan = plan_assumption_model(candidates, established)

        summary = (
            f"assumptions: {len(plan.assumptions)} assumptions, "
            f"{len(plan.needing_validation)} needing validation, "
            f"{len(plan.scaffolding)} scaffolding, {len(plan.resolved)} already established, "
            f"from {len(candidates)} observations"
        )
        key = (
            idempotency_key
            or f"assumption-synthesis:{len(candidates)}:{len(plan.needing_validation)}"
        ).strip()

        assumptions: list[SynthesizedAssumption] = []
        for planned in plan.assumptions:
            statement = planned.candidate.statement
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.ASSUMPTION.value,
                identity_key=identity_key_for(statement),
                title=statement,
                statement=statement,
            )
            settled = planned.authority is Authority.HUMAN
            if settled:
                obj = self._synthesis.correct_object(project_id, obj.id, statement, statement)
            assumptions.append(
                SynthesizedAssumption(
                    object_id=obj.id,
                    statement=statement,
                    consequence=planned.consequence,
                    settled=settled,
                    needs_validation=planned.needs_validation,
                    basis=planned.basis,
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

        return AssumptionSynthesisReport(
            project_id=project_id,
            replayed=event.created_at is not None and event.created_at < started,
            considered=len(candidates),
            assumptions=tuple(assumptions),
            scaffolding=tuple((item.statement, item.reason) for item in plan.scaffolding),
            resolved=tuple((item.statement, item.reason) for item in plan.resolved),
            needing_validation=plan.needing_validation,
        )

    def _read(
        self, project_id: ProjectId
    ) -> tuple[
        tuple[AssumptionCandidate, ...],
        dict[str, tuple[KnowledgeItemId, ...]],
        tuple[str, ...],
    ]:
        """Read assumption evidence and what the project already establishes.

        Statements identical after normalisation share a candidate, and a
        candidate counts as confirmed when **any** of its rows was validated: a
        person who confirmed one wording of a sentence confirmed the sentence.

        Established knowledge is every validated row of **another** kind. A
        validated assumption is its own candidate, and `_already_established` is
        containment — a statement contains itself — so including them would make
        each one retire itself instead of becoming authoritative.
        """

        def operation(
            session: DbSession,
        ) -> tuple[
            tuple[AssumptionCandidate, ...],
            dict[str, tuple[KnowledgeItemId, ...]],
            tuple[str, ...],
        ]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            items = knowledge.list_for_project(project_id, None)

            grouped: dict[str, list[KnowledgeItemId]] = {}
            statement_of: dict[str, str] = {}
            confirmed: set[str] = set()
            established: list[str] = []
            for item in items:
                content = item.current_version.content
                if item.kind != KnowledgeKind.ASSUMPTION.value:
                    if item.lifecycle is LifecycleState.VALIDATED:
                        established.append(content)
                    continue
                if item.lifecycle not in RETRIEVABLE:
                    continue
                key = identity_key_for(content)
                if not key:
                    continue
                grouped.setdefault(key, []).append(item.id)
                statement_of.setdefault(key, content)
                if item.lifecycle is LifecycleState.VALIDATED:
                    confirmed.add(key)

            candidates = tuple(
                AssumptionCandidate(
                    members=tuple(str(member) for member in members),
                    canonical_key=key,
                    statement=statement_of[key],
                    confirmed_by_person=key in confirmed,
                )
                for key, members in sorted(grouped.items())
            )
            members_of = {key: tuple(members) for key, members in grouped.items()}

            return candidates, members_of, tuple(established)

        return run_transaction(self._session_factory, operation)
