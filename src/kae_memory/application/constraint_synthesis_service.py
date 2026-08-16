"""Run constraint synthesis: extracted `constraint v1` rows to the project's boundaries.

`07-CONSTRAINTS.md`, and `D-124`/`D-126`. The extracted rows stay where they are
and keep their lifecycle. What this adds is a `synthesized_objects` row per
boundary, a `constraint_effects` row per consequence an *accepted* boundary
imposes, and one idempotent change event.

## The effect is stored; the proposed effect is not (`D-126`)

A decision needed no table because the object it is stored as already carried
its state (`D-125`). An effect is not a property of its constraint: it relates
the boundary to a *different* row, an open unknown or assumption, so there is no
single object whose fields could hold it.

Only accepted boundaries are written. An unaccepted one's effects are computed
and reported as `proposed_effects` and stored nowhere, which is what makes the
table's contents mean something: a row exists because a person accepted the
constraint it comes from, so no reader has to remember to filter.

## Nothing here becomes attention

Doc 07 offers *Add exception* and *Change scope* beside *Accept*, so an effect
is an argument about an item rather than a verdict on it or a task for someone.
An unaccepted boundary is not an interruption either, for `D-125`'s reason. A
run raises no attention items at all.

## Rerunning changes nothing

Identity is the statement, normalised, for the objects and
`(constraint, item)` for the effects. Unchanged evidence produces the same keys
and therefore the same rows, and the run's event replays instead of being
recorded again.
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
from kae_memory.domain.synthesis import ChangeTrigger, EvidenceBindingKind
from kae_memory.domain.synthesizers.constraints import (
    ConstraintCandidate,
    ConstraintFamily,
    Effect,
    OpenItem,
    plan_constraint_model,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import run_transaction

_OPEN_KINDS = (KnowledgeKind.UNKNOWN.value, KnowledgeKind.ASSUMPTION.value)


@dataclass(frozen=True, slots=True)
class SynthesizedConstraint:
    """One boundary as the run wrote it, with the reading behind it."""

    object_id: SynthesizedObjectId
    statement: str
    family: ConstraintFamily
    restricts: bool
    accepted: bool


@dataclass(frozen=True, slots=True)
class AppliedEffect:
    """One consequence an accepted boundary imposes, as stored."""

    constraint_object_id: SynthesizedObjectId
    knowledge_item_id: KnowledgeItemId
    statement: str
    item_statement: str
    kind: str
    basis: str


@dataclass(frozen=True, slots=True)
class ConstraintSynthesisReport:
    """What one run concluded, including what it computed and did not apply."""

    project_id: ProjectId
    replayed: bool
    considered: int
    open_items: int
    constraints: tuple[SynthesizedConstraint, ...]

    effects: tuple[AppliedEffect, ...]
    """What accepted boundaries bear on, and the only thing written."""

    proposed_effects: tuple[tuple[str, str, str], ...]
    """What would follow if the unaccepted boundaries were accepted.

    Statement, item, and reason — reported and stored nowhere (`D-126`). The
    item travels with the constraint because *"it would narrow something"* names
    nothing a person could act on.
    """

    @property
    def by_family(self) -> dict[ConstraintFamily, int]:
        """How the run read each boundary's subject. Derived, never stored."""

        return dict(Counter(constraint.family for constraint in self.constraints))

    @property
    def reached(self) -> int:
        """How many open items an accepted boundary bears on at all."""

        return len({effect.knowledge_item_id for effect in self.effects})


class ConstraintSynthesisService:
    """Turn constraint evidence into the project's boundaries and their effects."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> ConstraintSynthesisReport:
        """Plan and persist the constraint model for one project."""

        started = datetime.now(UTC)
        candidates, members_of, items, item_statements = self._read(project_id)
        plan = plan_constraint_model(candidates, items)

        summary = (
            f"constraints: {len(plan.constraints)} boundaries, {len(plan.effects)} effects, "
            f"{len(plan.proposed_effects)} proposed, over {len(items)} open items"
        )
        key = (
            idempotency_key or f"constraint-synthesis:{len(candidates)}:{len(plan.effects)}"
        ).strip()

        object_for: dict[str, SynthesizedObjectId] = {}
        constraints: list[SynthesizedConstraint] = []
        for planned in plan.constraints:
            statement = planned.candidate.statement
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.CONSTRAINT.value,
                identity_key=identity_key_for(statement),
                title=statement,
                statement=statement,
            )
            object_for[planned.candidate.canonical_key] = obj.id
            constraints.append(
                SynthesizedConstraint(
                    object_id=obj.id,
                    statement=statement,
                    family=planned.family,
                    restricts=planned.restricts,
                    accepted=planned.candidate.accepted,
                )
            )
            for member in members_of[planned.candidate.canonical_key]:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )

        statement_of = {
            planned.candidate.canonical_key: planned.candidate.statement
            for planned in plan.constraints
        }
        applied: list[AppliedEffect] = []
        for effect in plan.effects:
            object_id = object_for[effect.constraint_key]
            item_id = KnowledgeItemId(effect.item_key)
            self._synthesis.record_constraint_effect(
                project_id, object_id, item_id, effect.kind.value, effect.basis
            )
            applied.append(
                AppliedEffect(
                    constraint_object_id=object_id,
                    knowledge_item_id=item_id,
                    statement=statement_of[effect.constraint_key],
                    item_statement=item_statements[effect.item_key],
                    kind=effect.kind.value,
                    basis=effect.basis,
                )
            )

        event = self._synthesis.record_change(
            project_id,
            idempotency_key=key,
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )

        return ConstraintSynthesisReport(
            project_id=project_id,
            replayed=event.created_at is not None and event.created_at < started,
            considered=len(candidates),
            open_items=len(items),
            constraints=tuple(constraints),
            effects=tuple(applied),
            proposed_effects=tuple(
                self._describe(effect, statement_of, item_statements)
                for effect in plan.proposed_effects
            ),
        )

    @staticmethod
    def _describe(
        effect: Effect, statement_of: dict[str, str], item_statements: dict[str, str]
    ) -> tuple[str, str, str]:
        return (
            statement_of[effect.constraint_key],
            item_statements[effect.item_key],
            effect.basis,
        )

    def _read(
        self, project_id: ProjectId
    ) -> tuple[
        tuple[ConstraintCandidate, ...],
        dict[str, tuple[KnowledgeItemId, ...]],
        tuple[OpenItem, ...],
        dict[str, str],
    ]:
        """Read constraint evidence and the open items a boundary might bear on.

        Statements identical after normalisation share a candidate, and a
        candidate counts as accepted when **any** of its rows was validated: a
        person who confirmed one wording of a boundary confirmed the boundary.

        The open items are every retrievable unknown and assumption. An
        item's own confirmation is not a filter here — doc 07's point is that a
        boundary narrows what is still open, and a confirmed assumption is still
        open in that sense.
        """

        def operation(
            session: DbSession,
        ) -> tuple[
            tuple[ConstraintCandidate, ...],
            dict[str, tuple[KnowledgeItemId, ...]],
            tuple[OpenItem, ...],
            dict[str, str],
        ]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            items = knowledge.list_for_project(project_id, None)

            grouped: dict[str, list[KnowledgeItemId]] = {}
            statement_of: dict[str, str] = {}
            accepted: set[str] = set()
            open_items: list[OpenItem] = []
            item_statements: dict[str, str] = {}
            for item in items:
                if item.lifecycle not in RETRIEVABLE:
                    continue
                content = item.current_version.content
                if item.kind in _OPEN_KINDS:
                    open_items.append(OpenItem(key=str(item.id), statement=content))
                    item_statements[str(item.id)] = content
                    continue
                if item.kind != KnowledgeKind.CONSTRAINT.value:
                    continue
                key = identity_key_for(content)
                if not key:
                    continue
                grouped.setdefault(key, []).append(item.id)
                statement_of.setdefault(key, content)
                if item.lifecycle is LifecycleState.VALIDATED:
                    accepted.add(key)

            candidates = tuple(
                ConstraintCandidate(
                    members=tuple(str(member) for member in members),
                    canonical_key=key,
                    statement=statement_of[key],
                    accepted=key in accepted,
                )
                for key, members in sorted(grouped.items())
            )
            members_of = {key: tuple(members) for key, members in grouped.items()}
            return candidates, members_of, tuple(open_items), item_statements

        return run_transaction(self._session_factory, operation)
