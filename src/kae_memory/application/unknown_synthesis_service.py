"""Turn 59 extracted unknowns into what is currently unknown, and who must act.

`ADR-0007`, `09-MATERIAL-UNKNOWNS.md`. The extracted rows keep their lifecycle
and stay retrievable; this adds a synthesized object per current theme, bindings
to the observations that asked it, and — for the few that warrant it — an
attention item.

**This is the first thing in the estate that writes `attention_items`.** Until
now the table existed and nothing filled it, which was deliberate: `ADR-0007`
says attention is generated *after* reconciliation and materiality, never by
extraction succeeding.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.application.goal_synthesis_service import identity_key_for
from kae_memory.application.synthesis_service import SynthesisService, payload_fingerprint
from kae_memory.domain.identifiers import (
    AttentionItemId,
    KnowledgeItemId,
    ProjectId,
    SynthesizedObjectId,
)
from kae_memory.domain.lifecycle import RETRIEVABLE
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.readiness import AreaState
from kae_memory.domain.synthesis import AttentionKind, ChangeTrigger, EvidenceBindingKind
from kae_memory.domain.synthesizers.goals import distance_over
from kae_memory.domain.synthesizers.unknowns import (
    ATTENTION_BOUND,
    UNKNOWN_ACTIONS,
    UnknownPlan,
    explain,
    plan_unknowns,
    theme_priority,
)
from kae_memory.persistence.chunk_repository import ChunkRepository
from kae_memory.persistence.readiness_repositories import ReadinessSnapshotRepository
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.synthesis_repository import SynthesisRepository
from kae_memory.persistence.transactions import run_transaction


@dataclass(frozen=True, slots=True)
class UnknownSynthesisReport:
    """What one run concluded, including what it deliberately did not raise."""

    project_id: ProjectId
    considered: int
    resolved: int
    """Extracted unknowns another source already answered. Kept, not raised."""

    themes: int
    attention: tuple[tuple[AttentionItemId, str], ...]
    withheld: tuple[str, ...]
    """Current themes that did not reach a person. Real, and below the bound."""

    clustered: bool
    ranked_by_blocking: bool


class UnknownSynthesisService:
    """Reconcile unknowns against the current model and raise only what matters."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        embedder: object | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)
        self._embedder = embedder

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> UnknownSynthesisReport:
        plan, clustered, considered = self._read(project_id)

        raised: list[tuple[AttentionItemId, str]] = []
        for theme in plan.attention:
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.UNKNOWN.value,
                identity_key=identity_key_for(theme.question),
                title=theme.question,
                statement=theme.question,
            )
            for member in theme.members:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )
            item = self._synthesis.put_attention(
                project_id,
                kind=AttentionKind.UNKNOWN,
                title=theme.question,
                explanation=explain(theme, plan.ranked_by_blocking),
                identity_key=identity_key_for(theme.question),
                synthesized_object_id=SynthesizedObjectId(str(obj.id)),
                priority=theme_priority(theme),
                # Never empty. Doc 01: an item with no semantically appropriate
                # path toward resolution is not promoted into the queue, and
                # defer alone does not count as one.
                actions=UNKNOWN_ACTIONS,
            )
            raised.append((item.id, theme.question))

        summary = (
            f"unknowns: {len(plan.themes)} themes from {considered} observations, "
            f"{len(plan.resolved)} already answered, {len(raised)} raised"
        )
        self._synthesis.record_change(
            project_id,
            # **The key names the inputs *and* the measurement.** Keyed on the
            # observation count alone, a run with vectors and a run without
            # collided: same 59 unknowns, genuinely different output, and the
            # second raised a conflict against the first. They are different
            # acts — one compared the evidence and one could not — so they are
            # different events, and a rerun in the same mode still replays.
            idempotency_key=(
                idempotency_key
                or f"unknown-synthesis:{considered}:{'compared' if clustered else 'uncompared'}"
            ).strip(),
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )
        # Recomputed, not returned by the write, so a replay reports the same
        # numbers as a first run rather than zero.
        _ = payload_fingerprint(ChangeTrigger.RECONCILIATION, summary)

        return UnknownSynthesisReport(
            project_id=project_id,
            considered=considered,
            resolved=len(plan.resolved),
            themes=len(plan.themes),
            attention=tuple(raised),
            withheld=tuple(theme.question for theme in plan.themes[ATTENTION_BOUND:]),
            clustered=clustered,
            ranked_by_blocking=plan.ranked_by_blocking,
        )

    def _read(self, project_id: ProjectId) -> tuple[UnknownPlan, bool, int]:
        def operation(session: DbSession) -> tuple[UnknownPlan, bool, int]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            unknowns = [
                item
                for item in knowledge.list_for_project(project_id, None)
                if item.kind == KnowledgeKind.UNKNOWN.value and item.lifecycle in RETRIEVABLE
            ]
            unknowns.sort(key=lambda item: str(item.id))
            item_ids = [item.id for item in unknowns]
            questions = {item.id: item.current_version.content for item in unknowns}
            # Severity is not on a knowledge item; the corpus grades a material
            # unknown by kind alone. Held as a map so a future grader changes one
            # line here rather than the domain.
            severities = {item.id: "critical" for item in unknowns}

            # **The evidence graph decides currency, not this service.** Phase 2
            # already marked identity unknowns `resolved` against the project's
            # own identity statement, and re-deciding that here would be a
            # second opinion competing with the reconciliation that produced it.
            roles = {
                record.knowledge_item_id: record.role.value
                for record in SynthesisRepository(session).list_roles(project_id)
            }

            vectors = self._statement_vectors(session, project_id, item_ids, questions)
            plan = plan_unknowns(
                item_ids,
                questions,
                severities,
                {item_id: roles.get(item_id) for item_id in item_ids},
                distance_over(vectors),
                incomplete_areas=self._incomplete_areas(session, project_id),
            )
            return plan, bool(vectors), len(item_ids)

        return run_transaction(self._session_factory, operation)

    def _incomplete_areas(self, session: DbSession, project_id: ProjectId) -> frozenset[str] | None:
        """Area keys the last readiness snapshot leaves short of coverage.

        `D-149`. ``None`` means the project has never had readiness calculated,
        and the plan reports `ranked_by_blocking` false rather than ranking
        against an empty set — which would look exactly like a project whose
        areas are all covered.
        """

        snapshot = ReadinessSnapshotRepository(session).latest(project_id)
        if snapshot is None:
            return None
        return frozenset(
            area.key
            for area in snapshot.areas
            if area.state not in {AreaState.SUFFICIENT, AreaState.NOT_APPLICABLE}
        )

    def _statement_vectors(
        self,
        session: DbSession,
        project_id: ProjectId,
        item_ids: list[KnowledgeItemId],
        content: dict[KnowledgeItemId, str],
    ) -> dict[KnowledgeItemId, tuple[float, ...]]:
        """Statement-space vectors, for `D-102`'s reason.

        Identical in shape to the goals synthesizer's, and deliberately not
        shared yet: two callers is not a pattern, and the third will show
        whether the seam belongs on the repository or on a synthesizer base.
        """

        chunks = ChunkRepository(session)
        if chunks.statement_space(project_id, item_ids):
            stored = chunks.embeddings_for(project_id, item_ids)
            if stored:
                return stored
        embedder = self._embedder
        if embedder is None:
            return {}
        ordered = [item_id for item_id in item_ids if content.get(item_id, "").strip()]
        if not ordered:
            return {}
        try:
            embedded = embedder.embed([content[item_id] for item_id in ordered])  # type: ignore[attr-defined]
        except Exception:
            return {}
        return dict(zip(ordered, embedded.vectors, strict=True))
