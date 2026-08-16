"""Run goal synthesis: evidence in, a small model out, nothing destroyed.

`ADR-0007`. The extracted rows stay exactly where they were and keep their
lifecycle; what this adds is a `synthesized_objects` row per goal, bindings back
to the evidence that supports it, an evidence role for the rows that were
absorbed, and one idempotent change event for the run.

## What is deterministic and what is judged

Clustering is complete linkage at a measured radius (`D-100`). Canonical wording
is a member's own sentence, chosen as the medoid — the model quotes the project
rather than paraphrasing it. Membership is judged, because three deterministic
exclusions were tried against the fixture and each failed (`D-101`); the reason
is stored so a person can see why something is in the model and overrule it.

## Rerunning changes nothing

Identity is the canonical statement, normalised. Unchanged evidence produces the
same clusters, the same medoids, the same identity keys, and therefore the same
rows — `put_object` returns the existing object rather than minting a twin, and
the run's event replays instead of being recorded again. That property is what
makes this safe to call after every extraction rather than by hand.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.agents.embedding import EmbeddingError, EmbeddingPort
from kae_memory.application.synthesis_service import SynthesisService, payload_fingerprint
from kae_memory.domain.clustering import cluster_by_complete_linkage
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId, SynthesizedObjectId
from kae_memory.domain.lifecycle import RETRIEVABLE
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.synthesis import ChangeTrigger, EvidenceBindingKind, EvidenceRole
from kae_memory.domain.synthesizers.goals import (
    CLUSTER_RADIUS,
    GoalCandidate,
    GoalJudge,
    distance_over,
    medoid,
    plan_goal_model,
)
from kae_memory.persistence.chunk_repository import ChunkRepository
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import run_transaction

#: Statements that say what the project *is*, for the judge's context.
#: Bounded deliberately: a judge handed the whole corpus is a summarizer.
IDENTITY_LIMIT = 12

_PUNCTUATION = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def identity_key_for(statement: str) -> str:
    """A stable key from the canonical wording.

    Case, punctuation and spacing are removed so a reworded quote does not
    remint the object, while a genuinely different sentence does. Not a hash:
    the key is read by people debugging why two runs disagreed.
    """

    lowered = _PUNCTUATION.sub(" ", statement.strip().lower())
    return _SPACES.sub(" ", lowered).strip()[:200]


@dataclass(frozen=True, slots=True)
class GoalSynthesisReport:
    """What one run concluded. Returned whole, including what it left out."""

    project_id: ProjectId
    replayed: bool
    judged: bool
    considered: int
    clustered: bool
    """Whether evidence could be compared at all.

    `False` means the deployment's vectors measure the chunk envelope rather
    than the sentence (`D-102`), so every observation stood alone. A caller must
    be able to tell a model that was *compacted* from one that merely was not —
    the second looks like a project with no duplicate ideas.
    """

    promoted: tuple[tuple[SynthesizedObjectId, str], ...]
    withheld: tuple[tuple[str, str], ...]
    """Statements that did not enter the model, each with the reason."""


class GoalSynthesisService:
    """Turn goal evidence into the project's goal model."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        judge: GoalJudge | None = None,
        embedder: EmbeddingPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._synthesis = SynthesisService(session_factory)
        self._judge = judge
        self._embedder = embedder

    def synthesize(
        self, project_id: ProjectId, *, idempotency_key: str | None = None
    ) -> GoalSynthesisReport:
        """Cluster, judge, and persist the goal model for one project."""

        candidates, identity, judged_ids, clustered = self._read(project_id)
        plan = plan_goal_model(candidates, identity, self._judge)

        summary = (
            f"goals: {len(plan.promoted)} promoted, {len(plan.withheld)} withheld, "
            f"from {len(judged_ids)} observations"
            + ("" if clustered else " (uncompared: evidence vectors are not statement-space)")
        )
        key = (idempotency_key or f"goal-synthesis:{len(judged_ids)}:{len(plan.promoted)}").strip()
        fingerprint = payload_fingerprint(ChangeTrigger.RECONCILIATION, summary)

        promoted: list[tuple[SynthesizedObjectId, str]] = []
        for candidate, reason in plan.promoted:
            obj = self._synthesis.put_object(
                project_id,
                domain=KnowledgeKind.GOAL.value,
                identity_key=identity_key_for(candidate.statement),
                title=candidate.statement,
                statement=candidate.statement,
            )
            promoted.append((obj.id, reason))
            for member in candidate.members:
                self._synthesis.bind_evidence(
                    project_id, obj.id, member, EvidenceBindingKind.SUPPORTS
                )
            # The medoid stays `active`; the rest are `supporting`. Neither is a
            # lifecycle change — every row is still retrievable and still says
            # what it said.
            for member in candidate.members:
                if member == candidate.canonical_id:
                    continue
                self._synthesis.set_evidence_role(project_id, member, EvidenceRole.SUPPORTING)

        event = self._synthesis.record_change(
            project_id,
            idempotency_key=key,
            trigger=ChangeTrigger.RECONCILIATION,
            summary=summary,
        )

        return GoalSynthesisReport(
            project_id=project_id,
            replayed=event.payload_fingerprint == fingerprint and not promoted,
            judged=plan.judged,
            considered=len(judged_ids),
            clustered=clustered,
            promoted=tuple(promoted),
            withheld=tuple((candidate.statement, reason) for candidate, reason in plan.withheld),
        )

    def _statement_vectors(
        self,
        session: DbSession,
        project_id: ProjectId,
        item_ids: Sequence[KnowledgeItemId],
        content: Mapping[KnowledgeItemId, str],
    ) -> dict[KnowledgeItemId, tuple[float, ...]]:
        """Vectors of the statements themselves, however this deployment can.

        Stored vectors are used **only** where the chunk body carries no
        envelope, which is the rare case. Otherwise the statements are embedded
        for this run. Not persisted: the schema keys a chunk by
        `(knowledge_id, chunk_index, embedding_version)`, so a second space
        needs a version reserved for it, and reserving one is a storage decision
        rather than something to slip in beside a synthesizer.

        Empty is a real answer — no embedder and no statement-space index means
        nothing here can compare two sentences, and the caller reports that
        rather than clustering on numbers that mean something else.
        """

        chunks = ChunkRepository(session)
        if chunks.statement_space(project_id, item_ids):
            stored = chunks.embeddings_for(project_id, item_ids)
            if stored:
                return stored
        if self._embedder is None:
            return {}
        ordered = [item_id for item_id in item_ids if content.get(item_id, "").strip()]
        if not ordered:
            return {}
        try:
            embedded = self._embedder.embed([content[item_id] for item_id in ordered])
        except EmbeddingError:
            # A model that is down is not a project with no duplicate ideas. The
            # run continues uncompared and says so.
            return {}
        return dict(zip(ordered, embedded.vectors, strict=True))

    def _read(
        self, project_id: ProjectId
    ) -> tuple[tuple[GoalCandidate, ...], tuple[str, ...], tuple[KnowledgeItemId, ...], bool]:
        """Read goal evidence and cluster it, outside any write."""

        def operation(
            session: DbSession,
        ) -> tuple[tuple[GoalCandidate, ...], tuple[str, ...], tuple[KnowledgeItemId, ...], bool]:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            goals = [
                item
                for item in knowledge.list_for_project(project_id, None)
                if item.kind == KnowledgeKind.GOAL.value and item.lifecycle in RETRIEVABLE
            ]
            # Sorted, so clustering ties break the same way on every run and the
            # identity keys do not drift between two identical corpora.
            goals.sort(key=lambda item: str(item.id))
            item_ids = [item.id for item in goals]
            content = {item.id: item.current_version.content for item in goals}

            # **The measurement is taken in the space the radius was measured
            # in** (`D-102`, `CHUNK-ENVELOPE`).
            #
            # Every stored chunk begins with `Type:`/`Project:`/`Status:`,
            # identical for every item of one kind in one project, so those
            # vectors measure the template: mean pair distance 0.144 as stored
            # against 0.510 as statements. `D-100`'s radius was measured on
            # statements and puts all 47 corpus goals in **one cluster** when
            # read from enveloped ones — the whole model as a single object, and
            # no lower radius rescues it.
            #
            # The prefix earns its place in retrieval, where it tells the model
            # that "monthly" is a rule inside a reporting project. Synthesis asks
            # a different question — *how far apart are these two sentences* —
            # so it pays for its own measurement rather than reusing an answer
            # to another one.
            vectors = self._statement_vectors(session, project_id, item_ids, content)
            distance = distance_over(vectors)
            clusters = cluster_by_complete_linkage(item_ids, distance, radius=CLUSTER_RADIUS)
            comparable = bool(vectors)

            candidates = tuple(
                GoalCandidate(
                    members=members,
                    canonical_id=(canonical := medoid(members, distance)),
                    statement=content[canonical],
                )
                for members in clusters
            )
            # **What the project repeatedly says about itself**, as background
            # for the judge.
            #
            # Confirmed statements alone are not enough: on a young project
            # almost nothing is confirmed, and a judge given one sentence
            # measures every candidate against a single theme. Measured against
            # `qwen2.5:14b`, that judge refused **every** candidate including
            # the corroborated ones — a project with no goals at all.
            #
            # So corroborated wordings come first. A cluster with several
            # members is something the conversation returned to, which is the
            # best available statement of what this project is about without
            # waiting for somebody to confirm anything.
            corroborated = sorted(
                (candidate for candidate in candidates if candidate.corroborated),
                key=lambda candidate: (-len(candidate.members), candidate.statement),
            )
            confirmed = [
                item.current_version.content
                for item in sorted(goals, key=lambda item: str(item.id))
                if item.lifecycle.value == "validated"
            ]
            identity = tuple(
                dict.fromkeys([candidate.statement for candidate in corroborated] + confirmed)
            )[:IDENTITY_LIMIT]
            return candidates, identity, tuple(item_ids), comparable

        return run_transaction(self._session_factory, operation)


def goal_statements(report: GoalSynthesisReport) -> Sequence[str]:
    """The withheld statements, for a caller reporting what was left out."""

    return [statement for statement, _ in report.withheld]
