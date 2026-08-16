"""Run actor synthesis: 22 peer `actor v1` rows to a responsibility model.

`03-ACTORS-STAKEHOLDERS.md`, and `D-120`/`D-121`. The extracted rows stay where
they are and keep their lifecycle. What this adds is a `synthesized_objects` row
per role, a `responsibility_assignments` cell wherever the evidence names both a
role and a subject, and one idempotent change event for the run.

## Nothing here is clustered, and that was measured (`D-121`)

`GoalSynthesisService` groups evidence by complete linkage over statement
vectors. Actor descriptions were measured the same way before this reused it —
all 22 golden-corpus actors on `mxbai-embed-large`, complete linkage swept from
0.15 to 0.50 — and the answer refuses the approach. **The closest pair in the
whole corpus, at 0.170, is `A person using KAE` and `KAE`**: a human and the AI
product, nearer to each other than any two humans are. At the goal radius,
`GitHub MCP` joins `Reviewer of generated packages`.

No threshold rescues it, because the failure is not the threshold. An actor
description is a noun phrase in the project's own vocabulary, so the distance
between two of them measures shared subject matter — and every actor in a
project shares subject matter. So this service takes no ``EmbeddingPort``,
identity is the normalised statement, and the report says `clustered=False`.

## The compaction is on the subject axis

Twenty-two rows become twenty-two roles; the cast list does not shrink. What
shrinks is what a reader must hold: the ones holding no responsibility anywhere
are **personas**, the AI and system descriptions are their own models, and what
is left is the project's actual roles. That separation is the relation's output,
not a taxonomy applied beside it.

## Rerunning changes nothing

Identity is the statement, normalised. Unchanged evidence produces the same
identity keys and therefore the same rows: ``put_object`` returns the existing
object, ``assign_responsibility`` returns the existing cell, and the run's event
replays instead of being recorded again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.goal_synthesis_service import identity_key_for
from kae_memory.application.synthesis_service import SynthesisService
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId, SynthesizedObjectId
from kae_memory.domain.lifecycle import RETRIEVABLE
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesis import AttentionKind, ChangeTrigger, EvidenceBindingKind
from kae_memory.domain.synthesizers.actors import RoleCandidate, RoleKind, plan_role_model
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class ActorSynthesisReport:
    """What one run concluded, including what it refused."""

    project_id: ProjectId
    replayed: bool
    """Whether this run's change event was already on record before it started.

    Read from the event's own timestamp rather than inferred from an empty
    result, because an actor model that legitimately promoted nothing is not a
    replay and must not report as one.
    """

    considered: int
    clustered: bool
    """Always ``False``, and stated rather than omitted.

    `GoalSynthesisReport` carries this field so a caller can tell a model that
    was compacted from one that was not. Here it is a permanent property of the
    domain rather than a deployment condition (`D-121`), and leaving the field
    out would make an uncompacted actor model read like a compacted one.
    """

    roles: tuple[tuple[SynthesizedObjectId, str, RoleKind], ...]
    assignments: tuple[tuple[str, str, str], ...]
    """Role statement, subject key, RACI letter — the matrix this run wrote."""

    conflicts: tuple[tuple[str, str], ...]
    """Subjects with a second Accountable claimant, each with the reason.

    Doc 03 invariant 2. These also become attention items, because that
    invariant says in its own words that a second claimant is a conflict *for
    the human-attention model*.
    """

    downgraded: tuple[tuple[str, str], ...]
    """Non-human claimants of Accountable, refused and reported.

    Deliberately **not** attention. Invariant 1 is a governance rule KAE holds
    by itself, and a rule that fired correctly is not an interruption — turning
    it into one is how a queue fills with KAE's own bookkeeping.
    """

    @property
    def personas(self) -> tuple[str, ...]:
        """The candidates that acquired no responsibility anywhere.

        Doc 03 line 10 as a query rather than as a stored column: somebody the
        product serves, who holds nothing in the project.
        """

        return tuple(statement for _, statement, kind in self.roles if kind is RoleKind.PERSONA)


class ActorSynthesisService:
    """Turn actor evidence into the project's role and responsibility model."""

    def __init__(self, session_factory: sessionmaker[DbSession]) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> ActorSynthesisReport:
        """Plan and persist the role model for one project."""

        started = datetime.now(UTC)
        candidates, members_of = self._read(project_id)
        plan = plan_role_model(candidates)

        summary = (
            f"actors: {len(plan.roles)} roles, {len(plan.assignments)} responsibilities, "
            f"{len(plan.conflicts)} conflicts, {len(plan.downgraded)} downgraded, "
            f"from {len(candidates)} observations"
        )
        key = (
            idempotency_key or f"actor-synthesis:{len(candidates)}:{len(plan.assignments)}"
        ).strip()

        object_for: dict[str, SynthesizedObjectId] = {}
        roles: list[tuple[SynthesizedObjectId, str, RoleKind]] = []
        for candidate, kind in plan.roles:
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.ACTOR.value,
                identity_key=identity_key_for(candidate.statement),
                title=candidate.statement,
                statement=candidate.statement,
            )
            object_for[candidate.statement] = obj.id
            roles.append((obj.id, candidate.statement, kind))
            for member in members_of[candidate.canonical_key]:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )

        assignments: list[tuple[str, str, str]] = []
        for assignment in plan.assignments:
            self._synthesis.assign_responsibility(
                project_id,
                object_for[assignment.role_statement],
                assignment.subject_key,
                assignment.letter.value,
                assignment.basis,
            )
            assignments.append(
                (assignment.role_statement, assignment.subject_key, assignment.letter.value)
            )

        for statement, reason in plan.conflicts:
            self._synthesis.put_attention(
                project_id,
                AttentionKind.CONFLICT,
                title="Two parties are accountable for the same subject",
                explanation=reason,
                identity_key=f"actor-conflict:{identity_key_for(statement)}",
                recommendation=(
                    "Decide which one answers for it. Two accountable parties means nobody is."
                ),
                synthesized_object_id=object_for.get(statement),
                actions=("Name the accountable party",),
            )

        event = self._synthesis.record_change(
            project_id,
            idempotency_key=key,
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )

        return ActorSynthesisReport(
            project_id=project_id,
            replayed=event.created_at is not None and event.created_at < started,
            considered=len(candidates),
            clustered=False,
            roles=tuple(roles),
            assignments=tuple(assignments),
            conflicts=plan.conflicts,
            downgraded=plan.downgraded,
        )

    def _read(
        self, project_id: ProjectId
    ) -> tuple[tuple[RoleCandidate, ...], dict[str, tuple[KnowledgeItemId, ...]]]:
        """Read actor evidence, one candidate per distinct statement.

        Statements identical after normalisation share a candidate, so a corpus
        that recorded the same actor twice does not produce two roles. Anything
        beyond that is not merged — see the module docstring.

        Candidates come back ordered by canonical key rather than by row id, so
        the report reads the same on every run and on any database. Item ids are
        random, and a report whose order depends on them cannot be pinned.
        """

        def operation(
            session: DbSession,
        ) -> tuple[tuple[RoleCandidate, ...], dict[str, tuple[KnowledgeItemId, ...]]]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            actors = [
                item
                for item in knowledge.list_for_project(project_id, None)
                if item.kind == KnowledgeKind.ACTOR.value and item.lifecycle in RETRIEVABLE
            ]
            actors.sort(key=lambda item: str(item.id))

            grouped: dict[str, list[KnowledgeItemId]] = {}
            statement_of: dict[str, str] = {}
            for item in actors:
                content = item.current_version.content
                key = identity_key_for(content)
                if not key:
                    continue
                grouped.setdefault(key, []).append(item.id)
                statement_of.setdefault(key, content)

            candidates = tuple(
                RoleCandidate(
                    members=tuple(str(member) for member in members),
                    canonical_key=key,
                    statement=statement_of[key],
                )
                for key, members in sorted(grouped.items())
            )
            members_of = {key: tuple(members) for key, members in grouped.items()}
            return candidates, members_of

        return run_transaction(self._session_factory, operation)
