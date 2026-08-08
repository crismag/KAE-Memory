"""Blueprint readiness, blockers, contradictions, and area assignment.

The percentage is never returned alone. Every response carries the areas, the
counts, the missing mandatory areas, and whether the snapshot is stale — because
a number a user cannot interrogate misrepresents project state (ADR-0012).
"""

from fastapi import APIRouter, status

from kae_memory.domain.identifiers import BlockerId, KnowledgeItemId, ProjectId, RelationshipId
from kae_memory.domain.readiness import BlockerSeverity, BlockerStatus

from ..dependencies import Ingestion, Memory, Readiness, Review
from ..errors import not_found
from ..parsing import parse_enum
from ..schemas import (
    AssignAreaRequest,
    BlockerResponse,
    CalculateReadinessRequest,
    ContradictionResponse,
    EnqueueReviewRequest,
    EnqueueReviewResponse,
    FindingResponse,
    RaiseBlockerRequest,
    ReadinessResponse,
    RecordContradictionRequest,
    ResolvedResponse,
    ResolveRequest,
    ReviewResponse,
)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["readiness"])


@router.get("/readiness", response_model=ReadinessResponse)
def get_readiness(project_id: str, memory: Memory, readiness: Readiness) -> ReadinessResponse:
    """Return the latest snapshot, calculating one if none exists.

    Calculating on first read rather than returning 404 means the workspace shows
    a real zero for an untouched project instead of an error it would have to
    explain.
    """

    _require_project(memory, project_id)
    identifier = ProjectId(project_id)
    snapshot = readiness.latest(identifier) or readiness.calculate(identifier)
    return ReadinessResponse.of(snapshot, readiness.knowledge_revision(identifier))


@router.post("/readiness/calculate", response_model=ReadinessResponse)
def calculate_readiness(
    project_id: str, body: CalculateReadinessRequest, memory: Memory, readiness: Readiness
) -> ReadinessResponse:
    """Recalculate and append a snapshot.

    Appends rather than replaces. Readiness history is how the product shows
    readiness *moving* as knowledge is confirmed.
    """

    _require_project(memory, project_id)
    identifier = ProjectId(project_id)
    snapshot = readiness.calculate(identifier, body.not_applicable_areas)
    return ReadinessResponse.of(snapshot, readiness.knowledge_revision(identifier))


@router.get("/readiness/history", response_model=list[ReadinessResponse])
def readiness_history(
    project_id: str, memory: Memory, readiness: Readiness, limit: int = 50
) -> list[ReadinessResponse]:
    """Return snapshots oldest first."""

    _require_project(memory, project_id)
    identifier = ProjectId(project_id)
    revision = readiness.knowledge_revision(identifier)
    return [
        ReadinessResponse.of(snapshot, revision)
        for snapshot in readiness.history(identifier, limit)
    ]


@router.post("/readiness/areas", status_code=status.HTTP_204_NO_CONTENT)
def assign_area(
    project_id: str, body: AssignAreaRequest, memory: Memory, readiness: Readiness
) -> None:
    """Link a knowledge item to a discovery area.

    An authoritative change: it alters which areas an item can cover, so the
    project's knowledge revision advances and earlier snapshots go stale.
    """

    _require_project(memory, project_id)
    readiness.assign_area(
        ProjectId(project_id), KnowledgeItemId(body.knowledge_item_id), body.area_key
    )


@router.post(
    "/review/runs", response_model=EnqueueReviewResponse, status_code=status.HTTP_202_ACCEPTED
)
def enqueue_review(
    project_id: str, body: EnqueueReviewRequest, memory: Memory, ingestion: Ingestion
) -> EnqueueReviewResponse:
    """Queue the review pass over everything extraction has produced.

    **This is the step that makes readiness mean anything.** Extraction writes
    knowledge; review is what assigns each item to a discovery area, and
    readiness counts items per area. Without it a project holding eight hundred
    statements reports 0% and every area empty — which is what four real
    projects did, because `IngestionService.enqueue_review` existed and was on
    no adapter. Its only caller in the repository was a unit test.

    Separate from ingestion rather than folded into it, for the reason the
    service already gives: review is cross-chunk, so it is meaningful only once
    extraction has drained, and there is no run-dependency mechanism to express
    that. Enqueuing both together lets a worker claim the review first and
    review an empty project.

    So the caller decides when. `outstanding_runs` on an ingestion response is
    how they know extraction is done.

    **202.** Nothing has been reviewed when this returns. A run is queued.
    """

    _require_project(memory, project_id)
    resolved = ProjectId(project_id)
    outstanding = ingestion.outstanding_runs(resolved)
    run_id = ingestion.enqueue_review(resolved, body.idempotency_key)
    return EnqueueReviewResponse(
        run_id=str(run_id),
        outstanding_extraction_runs=outstanding,
        # Reported rather than refused. A caller who knows they are re-running
        # review over a partially extracted project is doing something
        # legitimate; a caller who does not needs to be told, not blocked.
        warnings=(
            [
                f"{outstanding} extraction runs have not finished. Review reads what "
                f"exists now, so anything still queued will not be classified and the "
                f"pass will need running again."
            ]
            if outstanding
            else []
        ),
    )


@router.get("/review", response_model=ReviewResponse)
def review_findings(project_id: str, memory: Memory, review: Review) -> ReviewResponse:
    """Return quality findings, most severe first (FR-015).

    Derived from operational data on every request rather than stored, so the
    findings can never disagree with the state they describe. Acting on one means
    changing that state — confirm the knowledge, assign the area, resolve the
    contradiction — and the finding disappears.
    """

    _require_project(memory, project_id)
    identifier = ProjectId(project_id)
    return ReviewResponse(
        project_id=project_id,
        counts=review.summary(identifier),
        findings=[FindingResponse.of(finding) for finding in review.findings(identifier)],
    )


@router.get("/blockers", response_model=list[BlockerResponse])
def list_blockers(
    project_id: str, memory: Memory, readiness: Readiness, blocker_status: str | None = None
) -> list[BlockerResponse]:
    """List a project's blockers."""

    _require_project(memory, project_id)
    state = (
        None
        if blocker_status is None
        else parse_enum(BlockerStatus, blocker_status, "blocker_status")
    )
    return [
        BlockerResponse.of(blocker) for blocker in readiness.blockers(ProjectId(project_id), state)
    ]


@router.post("/blockers", response_model=BlockerResponse, status_code=status.HTTP_201_CREATED)
def raise_blocker(
    project_id: str, body: RaiseBlockerRequest, memory: Memory, readiness: Readiness
) -> BlockerResponse:
    """Record something that must be closed before a blueprint is credible."""

    _require_project(memory, project_id)
    severity = parse_enum(BlockerSeverity, body.severity, "severity")
    return BlockerResponse.of(
        readiness.raise_blocker(
            ProjectId(project_id), body.summary, severity, body.area_key, body.owner
        )
    )


@router.post("/blockers/{blocker_id}/resolve", response_model=BlockerResponse)
def resolve_blocker(
    project_id: str, blocker_id: str, body: ResolveRequest, readiness: Readiness
) -> BlockerResponse:
    """Close a blocker."""

    return BlockerResponse.of(readiness.resolve_blocker(BlockerId(blocker_id), body.note))


@router.post(
    "/contradictions",
    response_model=ContradictionResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_contradiction(
    project_id: str, body: RecordContradictionRequest, memory: Memory, readiness: Readiness
) -> ContradictionResponse:
    """Record that two knowledge items contradict each other.

    An unresolved contradiction touching a mandatory area blocks readiness, which
    is what makes this more than an annotation.
    """

    _require_project(memory, project_id)
    relationship = readiness.record_contradiction(
        ProjectId(project_id),
        KnowledgeItemId(body.source_knowledge_item_id),
        KnowledgeItemId(body.target_knowledge_item_id),
    )
    return ContradictionResponse(
        id=str(relationship.id),
        project_id=str(relationship.project_id),
        source_knowledge_item_id=str(relationship.source_id),
        target_knowledge_item_id=str(relationship.target_id),
    )


@router.post("/contradictions/{relationship_id}/resolve", response_model=ResolvedResponse)
def resolve_contradiction(
    project_id: str, relationship_id: str, body: ResolveRequest, readiness: Readiness
) -> ResolvedResponse:
    """Resolve a contradiction.

    ``resolved: false`` means it was already settled. That is not an error — a
    retried resolution has to be safe — and the edge is never deleted, because a
    contradiction that was raised and closed is part of the audit trail.
    """

    resolved = readiness.resolve_contradiction(
        ProjectId(project_id), RelationshipId(relationship_id), body.note
    )
    return ResolvedResponse(resolved=resolved)


def _require_project(memory: Memory, project_id: str) -> None:
    if memory.get_project(ProjectId(project_id)) is None:
        raise not_found("project", project_id)
