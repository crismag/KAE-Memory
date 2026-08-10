"""Blueprint readiness calculation and the writes that feed it.

Readiness is **synchronous deterministic application logic**, not agent work.
ADR-0012's proposal allowed recalculation "through the durable worker", but
``enqueue_run`` requires an :class:`AgentRole` and FR-009 authorises exactly
three. Adding a fourth role to run weighted arithmetic would breach that for no
benefit. Classification — deciding which area a piece of knowledge serves — may
be agent work, and that is the Review Agent, already authorised. **Classification
proposes; calculation decides.**

The same inputs therefore produce the same score regardless of which model ran,
or whether a model ran at all.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import (
    AgentRunId,
    AreaLinkId,
    BlockerId,
    KnowledgeItemId,
    ProjectId,
    RelationshipId,
    SnapshotId,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, Relationship, RelationshipType
from kae_memory.domain.readiness import (
    CALCULATION_VERSION,
    DRAFT_THRESHOLD,
    SOFTWARE_TEMPLATE,
    AreaDefinition,
    AreaResult,
    AreaState,
    Blocker,
    BlockerSeverity,
    BlockerStatus,
    KnowledgeAreaLink,
    ReadinessSnapshot,
    ReadinessStatus,
    ReadinessTemplate,
)
from kae_memory.persistence.readiness_repositories import (
    BlockerRepository,
    KnowledgeAreaLinkRepository,
    ReadinessSnapshotRepository,
    ReadinessTemplateRepository,
    RelationshipRepository,
    bump_knowledge_revision,
    count_open_blockers,
    current_knowledge_revision,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction
from kae_memory.persistence.workspace_repositories import AgentRunRepository


def _new_id() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


def evaluate_area(
    area: AreaDefinition,
    items: Sequence[KnowledgeItem],
    contradicted_item_ids: frozenset[str],
    not_applicable: bool = False,
) -> AreaResult:
    """Return one area's coverage from the knowledge assigned to it.

    Only ``VALIDATED`` knowledge can make an area sufficient. Proposed extraction
    establishes partial coverage and steers the next question, but never completes
    an area on its own — otherwise a project could raise its own readiness simply
    by generating more candidates, which is the failure mode this model exists to
    prevent. Rejected and superseded knowledge contributes nothing.
    """

    allowed = {kind.value for kind in area.kinds}
    eligible = [item for item in items if item.kind in allowed]
    confirmed = [item for item in eligible if item.lifecycle is LifecycleState.VALIDATED]
    proposed = [item for item in eligible if item.lifecycle is LifecycleState.PROPOSED]
    contradicted = any(str(item.id) in contradicted_item_ids for item in confirmed + proposed)

    if not_applicable:
        state = AreaState.NOT_APPLICABLE
    elif len(confirmed) >= area.minimum_confirmed:
        state = AreaState.SUFFICIENT
    elif confirmed or proposed:
        state = AreaState.PARTIAL
    else:
        state = AreaState.MISSING

    return AreaResult(
        key=area.key,
        name=area.name,
        weight=area.weight,
        mandatory=area.mandatory,
        state=state,
        confirmed_count=len(confirmed),
        proposed_count=len(proposed),
        minimum_confirmed=area.minimum_confirmed,
        contradicted=contradicted,
    )


def score_areas(areas: Sequence[AreaResult]) -> float:
    """Return the weighted percentage over applicable areas.

    Areas marked not applicable leave the denominator entirely, so excluding one
    neither rewards nor punishes the project.
    """

    applicable = [area for area in areas if area.state is not AreaState.NOT_APPLICABLE]
    total_weight = sum(area.weight for area in applicable)
    if total_weight == 0:
        return 0.0
    earned = sum(area.weight * area.credit for area in applicable)
    return 100.0 * earned / total_weight


def derive_status(
    areas: Sequence[AreaResult],
    score: float,
    implementation_eligible: bool,
    blocked: bool,
) -> ReadinessStatus:
    """Return the semantic status, which is not the percentage.

    ``blocked`` is checked before ``blueprint_ready`` because it means coverage
    would otherwise permit generation. Ordering it the other way would let a
    project report ready while a critical blocker or a mandatory contradiction
    stood unresolved.

    ``stale`` is deliberately absent here: staleness is a property of a snapshot
    compared against the project's later revision, not something the calculation
    can know about itself. See :meth:`ReadinessSnapshot.is_stale_against`.
    """

    touched = any(area.confirmed_count or area.proposed_count for area in areas)
    if not touched:
        return ReadinessStatus.NOT_STARTED
    if blocked:
        return ReadinessStatus.BLOCKED
    if implementation_eligible:
        return ReadinessStatus.BLUEPRINT_READY
    if score >= DRAFT_THRESHOLD:
        return ReadinessStatus.DRAFT_READY
    return ReadinessStatus.DISCOVERING


#: Roles whose runs turn submitted text into knowledge.
#:
#: Review and architecture read what already exists; abandoning one loses
#: classification or a derived decision, not source content. Counting them here
#: would report loss that did not happen.
_EXTRACTION_ROLES = frozenset({AgentRole.REQUIREMENTS, AgentRole.DISCOVERY})


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    """Which engine classified this project's knowledge, and when.

    `engine` is `None` when no review has run — which is a fact about the
    project, not a missing field, and reads differently from "classified
    offline". A caller must be able to tell *never reviewed* from *reviewed
    without a model*.
    """

    #: `reviewed_by_model`, `partially_reviewed_by_model`,
    #: `offline_by_kind_after_reviewer_error`, or `None` when none has run.
    engine: str | None
    reviewed_at: datetime | None

    @property
    def by_model(self) -> bool:
        return self.engine == "reviewed_by_model"

    @property
    def degraded(self) -> bool:
        """Whether any part of this classification fell back to rules.

        The distinction the readiness payload exists to carry: a degraded run
        still succeeds, still recalculates readiness, and still produces a
        number — one capped far below what a model would have reached.
        """

        return self.engine in {
            "partially_reviewed_by_model",
            "offline_by_kind_after_reviewer_error",
        }


@dataclass(frozen=True, slots=True)
class ExtractionCoverage:
    """How much of what was submitted survived extraction.

    Reported beside a readiness percentage, never folded into it. A percentage
    computed over content that was never captured is a confident lie, and the
    two numbers answer different questions: one is *how much of this project is
    understood*, the other is *how much of it was read*.
    """

    succeeded: int
    abandoned: int
    #: Chunks a document was truncated to before any run existed. Counted here
    #: because they are loss, and counting runs alone cannot see them.
    not_ingested: int = 0

    @property
    def total(self) -> int:
        """Everything submitted, including what was never attempted."""

        return self.succeeded + self.abandoned + self.not_ingested

    @property
    def is_complete(self) -> bool:
        """Whether everything submitted became knowledge.

        A project with nothing submitted is complete rather than unknown: there
        is no loss to disclose, and saying "coverage unknown" to someone who has
        not started would be a warning about nothing.

        Truncation counts. A document cut off at `max_chunks` reported complete
        while most of it had never been read, because the dropped chunks never
        became runs (AUD-024).
        """

        return self.abandoned == 0 and self.not_ingested == 0


class ReadinessService:
    """Application entry point for readiness, blockers, and contradictions."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        policy: RetryPolicy | None = None,
        clock: Callable[[], datetime] = _now,
        template: ReadinessTemplate = SOFTWARE_TEMPLATE,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy or RetryPolicy()
        self._clock = clock
        self._template = template

    def _run[ResultT](self, operation: Callable[[DbSession], ResultT]) -> ResultT:
        return run_transaction(self._session_factory, operation, self._policy)

    def install_template(self, template: ReadinessTemplate | None = None) -> ReadinessTemplate:
        """Persist a template version so snapshots reference stored configuration."""

        chosen = template or self._template
        moment = self._clock()

        def operation(session: DbSession) -> ReadinessTemplate:
            ReadinessTemplateRepository(session).upsert(chosen, moment)
            return chosen

        return self._run(operation)

    def assign_area(
        self,
        project_id: ProjectId,
        item_id: KnowledgeItemId,
        area_key: str,
        assigned_by_agent_run_id: AgentRunId | None = None,
    ) -> KnowledgeAreaLink:
        """Link a knowledge item to a discovery area.

        Linking is an authoritative change: it alters which areas a confirmed item
        can cover, so it bumps the project's knowledge revision and any earlier
        snapshot becomes stale.
        """

        area = self._template.area(area_key)
        if area is None:
            raise LookupError(f"unknown readiness area: {area_key!r}")
        link = KnowledgeAreaLink(
            id=AreaLinkId(_new_id()),
            project_id=project_id,
            knowledge_item_id=item_id,
            area_key=area_key,
            created_at=self._clock(),
            assigned_by_agent_run_id=assigned_by_agent_run_id,
        )

        def operation(session: DbSession) -> KnowledgeAreaLink:
            # An area only counts knowledge of a kind it declares, so accepting an
            # assignment it can never count would make "assigned" and "counts"
            # two different things — and a blueprint would render a statement
            # that contributes nothing to the score it sits beside.
            item = SqlAlchemyKnowledgeRepository(session).get(item_id)
            if item is None:
                raise LookupError(f"unknown knowledge item: {item_id}")
            if item.kind not in {kind.value for kind in area.kinds}:
                raise DomainInvariantError(
                    f"area {area_key!r} does not accept {item.kind!r} knowledge; "
                    f"it accepts {', '.join(sorted(kind.value for kind in area.kinds))}"
                )
            KnowledgeAreaLinkRepository(session).add(link)
            bump_knowledge_revision(session, project_id)
            return link

        return self._run(operation)

    def area_links(self, project_id: ProjectId) -> tuple[KnowledgeAreaLink, ...]:
        """Return every area assignment in a project."""

        return self._run(
            lambda session: KnowledgeAreaLinkRepository(session).list_for_project(project_id)
        )

    def extraction_coverage(self, project_id: ProjectId) -> "ExtractionCoverage":
        """How much of what was submitted actually became knowledge.

        **The disclosure `PLANNING_MODEL.md` requires and nothing implemented:**
        *"Content loss is reported separately and never folded in. While F-018 is
        open, a project whose extraction abandoned chunks must say so."*

        F-018 measured 29–65% of chunks abandoned across four real corpora, every
        one `retry_budget_exhausted` after `verify_quotes` rejected a citation
        that was a directory tree or a code fence. Everything downstream —
        requirements, readiness, definition, coverage — is computed over what
        survived, and the survivors look exactly like a complete project.

        This does not repair the loss. It makes the existing number honest,
        which is what makes deferring the repair defensible rather than
        convenient.

        Counted from the runs themselves rather than stored, so it cannot drift
        from what happened.
        """

        def operation(session: DbSession) -> ExtractionCoverage:
            runs = AgentRunRepository(session).list_for_project(project_id, None)
            extraction = [r for r in runs if r.role in _EXTRACTION_ROLES]
            succeeded = sum(1 for r in extraction if r.status is RunStatus.SUCCEEDED)
            abandoned = sum(1 for r in extraction if r.status is RunStatus.ABANDONED)
            # Content dropped at ingest never became a run, so counting runs
            # alone reported a truncated document as fully covered (AUD-024).
            # Recorded on chunk zero of each ingest, so this sums without
            # double-counting a document.
            not_ingested = sum(
                int((r.input_context or {}).get("chunks_not_ingested", 0)) for r in extraction
            )
            return ExtractionCoverage(
                succeeded=succeeded, abandoned=abandoned, not_ingested=not_ingested
            )

        return self._run(operation)

    def classification(self, project_id: ProjectId) -> "ClassificationReport":
        """How the knowledge behind this project's readiness was classified.

        **The half of `PPA/REVIEW-01` that was met at the run and not at the
        number.** The worker already computes whether a review ran on a model,
        partially degraded, or fell back to offline unambiguous-only
        classification — and writes it into the run's `output_summary`, where a
        reader of `GET /readiness` will never see it. So a percentage produced
        by the 16% offline ceiling was indistinguishable from one a model
        produced (AUD-025, AUD-026).

        Read from the runs rather than stored, for the same reason coverage is:
        it cannot then drift from what happened. Reported beside readiness and
        never folded into it — this says *how* the number was reached, not
        what it is.
        """

        def operation(session: DbSession) -> ClassificationReport:
            runs = AgentRunRepository(session).list_for_project(project_id, None)
            reviews = [r for r in runs if r.role is AgentRole.REVIEW]
            for run in reviews:  # most recent first
                engine = (run.output_summary or {}).get("classification")
                if isinstance(engine, str) and engine:
                    return ClassificationReport(engine=engine, reviewed_at=run.completed_at)
            return ClassificationReport(engine=None, reviewed_at=None)

        return self._run(operation)

    def record_contradiction(
        self,
        project_id: ProjectId,
        source_id: KnowledgeItemId,
        target_id: KnowledgeItemId,
        created_by_agent_run_id: AgentRunId | None = None,
    ) -> Relationship:
        """Record that two knowledge items contradict each other."""

        relationship = Relationship(
            id=RelationshipId(_new_id()),
            project_id=project_id,
            source_id=source_id,
            target_id=target_id,
            type=RelationshipType.CONTRADICTS,
        )
        moment = self._clock()

        def operation(session: DbSession) -> Relationship:
            RelationshipRepository(session).add(relationship, moment, created_by_agent_run_id)
            bump_knowledge_revision(session, project_id)
            return relationship

        return self._run(operation)

    def resolve_contradiction(
        self, project_id: ProjectId, relationship_id: RelationshipId, note: str | None = None
    ) -> bool:
        """Resolve a recorded contradiction. Returns whether it was still open."""

        moment = self._clock()

        def operation(session: DbSession) -> bool:
            resolved = RelationshipRepository(session).resolve(relationship_id, moment, note)
            if resolved:
                bump_knowledge_revision(session, project_id)
            return resolved

        return self._run(operation)

    def raise_blocker(
        self,
        project_id: ProjectId,
        summary: str,
        severity: BlockerSeverity = BlockerSeverity.CRITICAL,
        area_key: str | None = None,
        owner: str | None = None,
    ) -> Blocker:
        """Record something that must be closed before a blueprint is credible."""

        blocker = Blocker(
            id=BlockerId(_new_id()),
            project_id=project_id,
            summary=summary,
            severity=severity,
            created_at=self._clock(),
            area_key=area_key,
            owner=owner,
        )

        def operation(session: DbSession) -> Blocker:
            BlockerRepository(session).add(blocker)
            bump_knowledge_revision(session, project_id)
            return blocker

        return self._run(operation)

    def resolve_blocker(self, blocker_id: BlockerId, note: str | None = None) -> Blocker:
        """Close a blocker."""

        moment = self._clock()

        def operation(session: DbSession) -> Blocker:
            repository = BlockerRepository(session)
            blocker = repository.get(blocker_id)
            if blocker is None:
                raise LookupError(f"unknown blocker: {blocker_id}")
            resolved = blocker.resolve(moment, note)
            repository.save(resolved)
            bump_knowledge_revision(session, blocker.project_id)
            return resolved

        return self._run(operation)

    def blockers(
        self, project_id: ProjectId, status: BlockerStatus | None = None
    ) -> tuple[Blocker, ...]:
        """Return a project's blockers."""

        return self._run(
            lambda session: BlockerRepository(session).list_for_project(project_id, status)
        )

    def calculate(
        self, project_id: ProjectId, not_applicable_areas: Sequence[str] = ()
    ) -> ReadinessSnapshot:
        """Calculate readiness and append a snapshot.

        Reads the knowledge, area links, contradictions, and blockers in one
        transaction alongside the project's revision, so the snapshot describes a
        single consistent state rather than a moving one.
        """

        excluded = set(not_applicable_areas)
        unknown = excluded - {area.key for area in self._template.areas}
        if unknown:
            raise LookupError(f"unknown readiness areas: {sorted(unknown)}")
        moment = self._clock()

        def operation(session: DbSession) -> ReadinessSnapshot:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            items = {str(item.id): item for item in knowledge.list_for_project(project_id, None)}
            links = KnowledgeAreaLinkRepository(session).list_for_project(project_id)
            relationships = RelationshipRepository(session)
            open_contradictions = relationships.list_for_project(
                project_id, RelationshipType.CONTRADICTS, unresolved_only=True
            )
            contradicted = relationships.unresolved_contradiction_items(project_id)
            open_blockers, critical_blockers = count_open_blockers(session, project_id)
            revision = current_knowledge_revision(session, project_id)

            by_area: dict[str, list[KnowledgeItem]] = {}
            for link in links:
                item = items.get(str(link.knowledge_item_id))
                if item is not None:
                    by_area.setdefault(link.area_key, []).append(item)

            areas = tuple(
                evaluate_area(
                    definition,
                    by_area.get(definition.key, ()),
                    contradicted,
                    not_applicable=definition.key in excluded,
                )
                for definition in self._template.areas
            )
            score = score_areas(areas)

            mandatory = [area for area in areas if area.mandatory]
            mandatory_contradiction = any(
                area.contradicted
                for area in mandatory
                if area.state is not AreaState.NOT_APPLICABLE
            )
            blocked = bool(critical_blockers) or mandatory_contradiction
            all_mandatory_covered = all(
                area.state in (AreaState.SUFFICIENT, AreaState.NOT_APPLICABLE) for area in mandatory
            )
            implementation_eligible = all_mandatory_covered and not blocked
            snapshot = ReadinessSnapshot(
                id=SnapshotId(_new_id()),
                project_id=project_id,
                template_key=self._template.key,
                template_version=self._template.version,
                calculation_version=CALCULATION_VERSION,
                knowledge_revision=revision,
                score=score,
                status=derive_status(areas, score, implementation_eligible, blocked),
                # A percentage alone never authorises an implementation blueprint.
                draft_eligible=score >= DRAFT_THRESHOLD,
                implementation_eligible=implementation_eligible,
                areas=areas,
                open_blocker_count=open_blockers,
                critical_blocker_count=critical_blockers,
                unresolved_contradiction_count=len(open_contradictions),
                calculated_at=moment,
            )
            ReadinessSnapshotRepository(session).add(snapshot)
            return snapshot

        return self._run(operation)

    def latest(self, project_id: ProjectId) -> ReadinessSnapshot | None:
        """Return a project's most recent snapshot."""

        return self._run(lambda session: ReadinessSnapshotRepository(session).latest(project_id))

    def history(self, project_id: ProjectId, limit: int = 50) -> tuple[ReadinessSnapshot, ...]:
        """Return a project's snapshots, oldest first."""

        return self._run(
            lambda session: ReadinessSnapshotRepository(session).history(project_id, limit)
        )

    def knowledge_revision(self, project_id: ProjectId) -> int:
        """Return a project's current authoritative knowledge revision."""

        return self._run(lambda session: current_knowledge_revision(session, project_id))


__all__ = [
    "ReadinessService",
    "derive_status",
    "evaluate_area",
    "score_areas",
]
