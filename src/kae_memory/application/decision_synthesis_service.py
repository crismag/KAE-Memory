"""Run decision synthesis: extracted `decision v1` rows to the project's choices.

`08-DECISIONS.md`, and `D-123`/`D-125`. The extracted rows stay where they are
and keep their lifecycle. What this adds is a `synthesized_objects` row per
decision, carrying the state doc 08 asks for, plus one idempotent change event.

## There is no decision table (`D-125`)

`D-123` ruled that doc 08's five stages are `SynthesizedLifecycle` rather than a
second enum. Stored, that ruling means the object already holds the answer: a
decision is a synthesized object whose `(lifecycle, authority)` pair *is* its
state. A table beside it would be the same pathology one layer down — two places
holding one state, free to disagree after a rerun.

The class and the scope are not stored either. Both are pure functions of the
statement, so a column would be a copy that drifts the moment the statement is
corrected. The run reports them; `GET /model?domain=decision` reads the objects.

## Only a person's confirmation promotes

`put_object` writes a working object and cannot mint an authoritative one, which
is the guard working correctly. A settled decision is promoted through
`correct_object` — the existing human path — with the wording passed back
unchanged. That is honest only because a decision object's statement is the
sentence the person confirmed, verbatim: identity here is the normalised
statement, so nothing was reworded between the confirmation and the promotion.

## An unsettled decision interrupts nobody

`awaiting` is every decision nobody has accepted. It is reported and written
nowhere, because one attention item per unaccepted decision would rebuild the
review queue `ADR-0007` exists to remove. Doc 08's **conflict** — an accepted
decision the project's own state contradicts — is what becomes attention.

## Rerunning changes nothing

Identity is the statement, normalised. Unchanged evidence produces the same
identity keys and therefore the same rows: `put_object` returns the existing
object, `correct_object` returns the already-authoritative one, and the run's
event replays instead of being recorded again.
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
from kae_memory.domain.synthesis import (
    AttentionKind,
    Authority,
    ChangeTrigger,
    EvidenceBindingKind,
)
from kae_memory.domain.synthesizers.decisions import (
    DecisionCandidate,
    DecisionClass,
    EffectiveScope,
    plan_decision_model,
)
from kae_memory.persistence.readiness_repositories import KnowledgeAreaLinkRepository
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class SynthesizedDecision:
    """One decision as the run wrote it, with the reading behind its state."""

    object_id: SynthesizedObjectId
    statement: str
    decision_class: DecisionClass
    scope: EffectiveScope
    settled: bool
    basis: str


@dataclass(frozen=True, slots=True)
class DecisionSynthesisReport:
    """What one run concluded, including what it refused to promote."""

    project_id: ProjectId
    replayed: bool
    """Whether this run's change event was already on record before it started.

    Read from the event's own timestamp rather than inferred from an empty
    result, because a run that legitimately settled nothing is not a replay.
    """

    considered: int
    decisions: tuple[SynthesizedDecision, ...]

    awaiting: tuple[tuple[str, str], ...]
    """Decisions nobody has accepted, each with what is being asked.

    Reported and **not** written to the attention queue (`D-125`). One interrupt
    per unaccepted decision is the 174-row review queue with a new name on it.
    """

    conflicts: tuple[tuple[str, str], ...]
    """Accepted decisions the project's own state contradicts.

    These do become attention items: doc 08 says new evidence conflicting with
    an accepted decision must *"trigger conflict analysis, not silently create
    parallel contradictory records"*.
    """

    session_scoped: tuple[tuple[str, str], ...]
    """Decisions refused permanence, each with the reason.

    Reported rather than dropped, and deliberately not attention: the refusal is
    a rule that fired correctly, not something somebody must resolve.
    """

    @property
    def settled(self) -> tuple[str, ...]:
        """The decisions a person actually settled — doc 08's *authoritative*."""

        return tuple(decision.statement for decision in self.decisions if decision.settled)

    @property
    def by_class(self) -> dict[DecisionClass, int]:
        """How the run read each decision's subject. Derived, never stored."""

        return dict(Counter(decision.decision_class for decision in self.decisions))


class DecisionSynthesisService:
    """Turn decision evidence into the project's proposals and settled choices."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> DecisionSynthesisReport:
        """Plan and persist the decision model for one project."""

        started = datetime.now(UTC)
        candidates, members_of, open_proposals = self._read(project_id)
        plan = plan_decision_model(candidates, open_proposals)

        summary = (
            f"decisions: {len(plan.decisions)} decisions, {len(plan.awaiting)} awaiting, "
            f"{len(plan.conflicts)} conflicts, {len(plan.session_scoped)} session-scoped, "
            f"from {len(candidates)} observations"
        )
        key = (
            idempotency_key or f"decision-synthesis:{len(candidates)}:{len(plan.awaiting)}"
        ).strip()

        object_for: dict[str, SynthesizedObjectId] = {}
        decisions: list[SynthesizedDecision] = []
        for planned in plan.decisions:
            statement = planned.candidate.statement
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.DECISION.value,
                identity_key=identity_key_for(statement),
                title=statement,
                statement=statement,
            )
            settled = planned.authority is Authority.HUMAN
            if settled:
                obj = self._synthesis.correct_object(project_id, obj.id, statement, statement)
            object_for[statement] = obj.id
            decisions.append(
                SynthesizedDecision(
                    object_id=obj.id,
                    statement=statement,
                    decision_class=planned.decision_class,
                    scope=planned.scope,
                    settled=settled,
                    basis=planned.basis,
                )
            )
            for member in members_of[planned.candidate.canonical_key]:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )

        for statement, reason in plan.conflicts:
            self._synthesis.put_attention(
                project_id,
                AttentionKind.CONFLICT,
                title="An accepted decision is contradicted by the project's own state",
                explanation=reason,
                identity_key=f"decision-conflict:{identity_key_for(statement)}",
                recommendation=(
                    "Decide which stands: the area is not settled, or the candidates below it "
                    "are not part of it."
                ),
                synthesized_object_id=object_for.get(statement),
                actions=("Reopen the area", "Close the candidates"),
            )

        event = self._synthesis.record_change(
            project_id,
            idempotency_key=key,
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )

        return DecisionSynthesisReport(
            project_id=project_id,
            replayed=event.created_at is not None and event.created_at < started,
            considered=len(candidates),
            decisions=tuple(decisions),
            awaiting=plan.awaiting,
            conflicts=plan.conflicts,
            session_scoped=plan.session_scoped,
        )

    def _read(
        self, project_id: ProjectId
    ) -> tuple[
        tuple[DecisionCandidate, ...],
        dict[str, tuple[KnowledgeItemId, ...]],
        dict[str, int],
    ]:
        """Read decision evidence and the open candidates each area still holds.

        Statements identical after normalisation share a candidate, and a
        candidate counts as confirmed when **any** of its rows was validated: a
        person who confirmed one wording of a sentence confirmed the sentence.

        The area counts are every `proposed` item carrying an area link, of any
        kind. Doc 08's sufficiency conflict is about raw candidates presented as
        undecided, which is a fact about the area rather than about decisions.
        """

        def operation(
            session: DbSession,
        ) -> tuple[
            tuple[DecisionCandidate, ...],
            dict[str, tuple[KnowledgeItemId, ...]],
            dict[str, int],
        ]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            items = knowledge.list_for_project(project_id, None)

            grouped: dict[str, list[KnowledgeItemId]] = {}
            statement_of: dict[str, str] = {}
            confirmed: set[str] = set()
            for item in items:
                if item.kind != KnowledgeKind.DECISION.value or item.lifecycle not in RETRIEVABLE:
                    continue
                content = item.current_version.content
                key = identity_key_for(content)
                if not key:
                    continue
                grouped.setdefault(key, []).append(item.id)
                statement_of.setdefault(key, content)
                if item.lifecycle is LifecycleState.VALIDATED:
                    confirmed.add(key)

            candidates = tuple(
                DecisionCandidate(
                    members=tuple(str(member) for member in members),
                    canonical_key=key,
                    statement=statement_of[key],
                    confirmed_by_person=key in confirmed,
                )
                for key, members in sorted(grouped.items())
            )
            members_of = {key: tuple(members) for key, members in grouped.items()}

            proposed = {str(item.id) for item in items if item.lifecycle is LifecycleState.PROPOSED}
            open_proposals: Counter[str] = Counter()
            for link in KnowledgeAreaLinkRepository(session).list_for_project(project_id):
                if str(link.knowledge_item_id) in proposed:
                    open_proposals[link.area_key] += 1

            return candidates, members_of, dict(open_proposals)

        return run_transaction(self._session_factory, operation)
