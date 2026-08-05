"""The acquisition-to-package pipeline over HTTP (N3, ADR-0023).

Search, ingestion, clarification, and assembly reached MCP in Phases C to E and
never reached HTTP. Studio is an HTTP client, so five of nine application
services were unreachable by the product's own frontend
(`docs/06_architecture/ADAPTER_CAPABILITY_MATRIX.md`).

These routes are adapters and nothing more. Every rule they appear to enforce —
lifecycle transitions, idempotency, truncation reporting, revision pinning —
belongs to the application service and is reached, not reimplemented. A router
that re-derived one would give the two adapters a way to disagree about what
the product does, which is exactly what ADR-0023 exists to prevent.

Two honesty rules carry over from the MCP surface unchanged, because they are
domain behaviour rather than transport convention:

* a response never claims more than it can support — search names the mode that
  ran and says when its ranking is not semantic;
* a bound that changed what was read is reported, never silently applied.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from kae_memory.application.assembly_service import AssemblyPurpose, describe_package
from kae_memory.application.ingestion_service import IngestionPolicy
from kae_memory.domain.identifiers import KnowledgeItemId, MessageId, ProjectId
from kae_memory.domain.knowledge_review import RejectionReason
from kae_memory.domain.models import KnowledgeKind

from ..dependencies import (
    Assembly,
    Clarifications,
    Ingestion,
    Memory,
    Readiness,
    Retrieval,
)
from ..errors import ApiError, not_found
from ..schemas import (
    AnswerClarificationRequest,
    AssemblyResponse,
    ClarificationListResponse,
    ClarificationResponse,
    CorrectKnowledgeRequest,
    IngestDocumentRequest,
    IngestionResponse,
    KnowledgeReviewResponse,
    RejectKnowledgeRequest,
    SearchResponse,
)

router = APIRouter(prefix="/v1", tags=["pipeline"])

MAX_PAGE = 100
"""The ceiling a caller cannot raise. A page is a budget, not a suggestion."""


def _project(project_id: str, memory: Memory) -> ProjectId:
    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    return project.id


@router.get("/projects/{project_id}/knowledge/search", response_model=SearchResponse)
def search_knowledge(
    project_id: str,
    query: Annotated[str, Query(min_length=1)],
    memory: Memory,
    retrieval: Retrieval,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 8,
    kinds: Annotated[list[str] | None, Query()] = None,
) -> SearchResponse:
    """Search a project's knowledge without loading the whole project.

    The response names the mode that actually ran. When no semantic embedding
    model is configured the search is lexical, and saying so is not a detail:
    a caller who believes a conceptual query was understood will read an empty
    result as "the project does not know this" rather than "the words did not
    match".
    """

    resolved = _project(project_id, memory)
    selected: tuple[KnowledgeKind, ...] | None = None
    if kinds:
        try:
            selected = tuple(KnowledgeKind(kind) for kind in kinds)
        except ValueError as error:
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
            ) from error

    hits, mode = retrieval.best_effort(resolved, query, limit=limit, kinds=selected)
    return SearchResponse.of(hits, mode, retrieval.indexing_status(resolved))


@router.post(
    "/projects/{project_id}/documents",
    response_model=IngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def ingest_document(
    project_id: str,
    body: IngestDocumentRequest,
    memory: Memory,
    ingestion: Ingestion,
) -> IngestionResponse:
    """Record a document as evidence and queue the extraction it needs.

    **202, not 201.** Nothing has been read yet. The text is durable and runs
    are queued; a worker turns them into candidates a person then reviews. A
    201 would say a resource was created that a caller can now read, and what
    exists at this point is a promise to read one.
    """

    resolved = _project(project_id, memory)
    policy = IngestionPolicy(max_chunks=body.max_chunks) if body.max_chunks else IngestionPolicy()
    result = ingestion.ingest_document(
        resolved,
        body.document,
        body.text,
        policy=policy,
        actor_id=body.actor_id,
    )
    return IngestionResponse.of(result)


@router.post(
    "/projects/{project_id}/knowledge/{item_id}/reject", response_model=KnowledgeReviewResponse
)
def reject_knowledge(
    project_id: str, item_id: str, body: RejectKnowledgeRequest, memory: Memory
) -> KnowledgeReviewResponse:
    """Record a person's decision to refuse a candidate.

    HTTP had `confirm` and neither `reject` nor `correct`, which made review
    one-sided: a reviewer could accept a proposal through this adapter and had
    to leave the adapter to refuse one.

    `expected_version` is required, not optional. A decision must not be applied
    to wording that changed after the reviewer read it, and the version is what
    ties the two together.
    """

    resolved = _project(project_id, memory)
    return KnowledgeReviewResponse.of(
        memory.review_reject(
            resolved,
            KnowledgeItemId(item_id),
            expected_version=body.expected_version,
            reason_code=RejectionReason(body.reason_code),
            actor_id=body.reviewer,
            note=body.note,
            idempotency_key=body.idempotency_key,
        )
    )


@router.post(
    "/projects/{project_id}/knowledge/{item_id}/correct", response_model=KnowledgeReviewResponse
)
def correct_knowledge(
    project_id: str, item_id: str, body: CorrectKnowledgeRequest, memory: Memory
) -> KnowledgeReviewResponse:
    """Record corrected wording as a new version.

    The prior version survives. A correction that overwrote what a reviewer read
    would leave the audit trail describing a decision made about text that no
    longer exists.
    """

    resolved = _project(project_id, memory)
    return KnowledgeReviewResponse.of(
        memory.review_correct(
            resolved,
            KnowledgeItemId(item_id),
            expected_version=body.expected_version,
            content=body.content,
            actor_id=body.reviewer,
            note=body.note,
            idempotency_key=body.idempotency_key,
        )
    )


@router.post("/projects/{project_id}/clarifications", response_model=ClarificationListResponse)
def open_clarifications(
    project_id: str,
    memory: Memory,
    clarifications: Clarifications,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
) -> ClarificationListResponse:
    """Return the questions this project's findings justify asking.

    **POST, not GET.** A clarification derived from a finding has no identity
    until it is recorded, and answering one needs an identity, so this call
    materialises the questions it returns. That is a mutation, and a GET that
    mutates is a GET that a proxy, a prefetch, or a retry will perform again
    without anyone intending it.

    Materialisation is idempotent by question: asking twice does not ask a
    person twice.
    """

    resolved = _project(project_id, memory)
    questions = clarifications.open_questions(resolved, limit=limit)
    return ClarificationListResponse.of(questions, limit=limit)


@router.post(
    "/projects/{project_id}/clarifications/{question_id}/answer",
    response_model=ClarificationResponse,
)
def answer_clarification(
    project_id: str,
    question_id: str,
    body: AnswerClarificationRequest,
    memory: Memory,
    clarifications: Clarifications,
) -> ClarificationResponse:
    """Record an answer and queue the extraction it justifies.

    An answer is evidence, not knowledge. The response says so: `knowledge_changed`
    stays false until a run reads the answer and a person confirms what it
    proposed. A caller reading "answered" as "the project now knows this" is the
    one thing this loop must not imply.
    """

    resolved = _project(project_id, memory)
    outcome = clarifications.answer(
        resolved,
        MessageId(question_id),
        body.answer,
        actor_id=body.actor_id,
        idempotency_key=body.idempotency_key,
    )
    return ClarificationResponse.of(outcome)


@router.get("/projects/{project_id}/context", response_model=AssemblyResponse)
def assemble_context(
    project_id: str,
    memory: Memory,
    assembly: Assembly,
    readiness: Readiness,
    purpose: Annotated[str, Query()] = "implementation",
    include_proposed: Annotated[bool, Query()] = False,
) -> AssemblyResponse:
    """Assemble a bounded context, pinned to the knowledge revision it read.

    A GET because it is deterministic and creates nothing: the same project at
    the same revision produces the same content hash. `package_id` is fresh per
    call and is **not** deliverable identity — a durable deliverable is a
    concept this repository does not have, and a route must not invent one.

    Proposed statements are excluded unless asked for, and arrive labelled when
    they are. An implementer who cannot tell a candidate from a confirmed
    statement will build whichever they read first.
    """

    resolved = _project(project_id, memory)
    try:
        selected = AssemblyPurpose(purpose)
    except ValueError as error:
        valid = ", ".join(p.value for p in AssemblyPurpose)
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown purpose {purpose!r}; expected one of {valid}",
        ) from error

    assembled = assembly.assemble(resolved, selected, include_proposed=include_proposed)
    description = describe_package(assembled)
    package: dict[str, Any] = {
        "package_id": description.package_id,
        "artifact_count": description.artifact_count,
        "total_statements": description.total_statements,
        "content_hash": description.content_hash,
        "artifacts": [
            {
                "path": entry.path,
                "area": entry.area_key,
                "title": entry.title,
                "statements": entry.statement_count,
                "confirmed": entry.confirmed_count,
                "content_hash": entry.content_hash,
            }
            for entry in description.artifacts
        ],
    }
    return AssemblyResponse.of(assembled, package, readiness.knowledge_revision(resolved))
