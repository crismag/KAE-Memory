"""The acquisition-to-package pipeline over HTTP (N3, ADR-0023).

Search, ingestion, clarification, and assembly reached MCP in Phases C to E and
never reached HTTP. Studio is an HTTP client, so five of nine application
services were unreachable by the product's own frontend
(the adapter capability matrix).

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

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from kae_memory.application.assembly_service import AssemblyPurpose, describe_package
from kae_memory.application.assumption_service import AssumptionNotFoundError
from kae_memory.application.deliverable_service import DeliverableNotFoundError
from kae_memory.application.ingestion_service import IngestionPolicy
from kae_memory.application.setup_service import (
    DefaultConflictError,
    SetupNotFoundError,
    SetupService,
)
from kae_memory.application.source_service import SourceNotFoundError
from kae_memory.domain.assumptions import (
    AssumptionOrigin,
    Consequence,
    InvalidAssumptionTransitionError,
    RevisitTrigger,
)
from kae_memory.domain.deliverables import InvalidDeliverableTransitionError
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import KnowledgeItemId, MessageId, ProjectId
from kae_memory.domain.knowledge_review import RejectionReason
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.project_configuration import ConfigurationError
from kae_memory.domain.publication_targets import (
    AuthorizationState,
    Provider,
    TargetError,
    TargetPurpose,
)
from kae_memory.domain.setup import SetupError, ValueState
from kae_memory.mcp import response_policy
from kae_memory.messages import message

from ..dependencies import (
    Assembly,
    Assumptions,
    Clarifications,
    Deliverables,
    Ingestion,
    Memory,
    Preliminary,
    Readiness,
    Retrieval,
    Setup,
)
from ..errors import ApiError, not_found
from ..schemas import (
    AcceptAssumptionRequest,
    AnswerClarificationRequest,
    AssemblyResponse,
    AssumptionListResponse,
    AssumptionResponse,
    AuthorizeConnectionRequest,
    ClarificationListResponse,
    ClarificationResponse,
    ConfigureFieldRequest,
    CorrectKnowledgeRequest,
    DeliverableListResponse,
    DeliverableResponse,
    IngestDocumentRequest,
    IngestionResponse,
    KnowledgeReviewResponse,
    PreliminaryContextResponse,
    ProviderConnectionListResponse,
    ProviderConnectionResponse,
    PublicationTargetListResponse,
    PublicationTargetResponse,
    QuestionCandidateListResponse,
    RecordAssumptionRequest,
    RecordConnectionRequest,
    RecordDeliverableRequest,
    RegisterTargetRequest,
    RejectKnowledgeRequest,
    SearchResponse,
    SetDefaultTargetRequest,
    SetupGapResponse,
    SetupQuestionListResponse,
    SetupQuestionResponse,
    SetupStateResponse,
    SupersedeDeliverableRequest,
    WithdrawDeliverableRequest,
)

router = APIRouter(prefix="/v1", tags=["pipeline"])

MAX_PAGE: int = response_policy.MAX_PAGE_SIZE
"""The ceiling a caller cannot raise. A page is a budget, not a suggestion.

Not a second constant. This was `100` written here and `100` written in the MCP
response policy, with the same docstring — two adapters holding one limit, and
nothing that would have noticed them diverging (N7).
"""


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
    try:
        result = ingestion.ingest_document(
            resolved,
            body.document,
            body.text,
            policy=policy,
            actor_id=body.actor_id,
            source_type=body.source_type,
            source_id=body.source_id,
        )
    except SourceNotFoundError as error:
        raise not_found("source", str(body.source_id)) from error
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


@router.get(
    "/projects/{project_id}/clarifications/candidates",
    response_model=QuestionCandidateListResponse,
)
def clarification_candidates(
    project_id: str,
    memory: Memory,
    clarifications: Clarifications,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
    include_deferred: bool = False,
) -> QuestionCandidateListResponse:
    """What this project's findings justify asking. **Writes nothing.**

    **GET, and it means it.** The sibling `POST /clarifications` materialises
    the questions it returns, because answering needs an identity and a derived
    clarification has none. That is the asking transition and it belongs behind
    a command.

    This is the query. A monitor, a prefetch, a refresh or a retry may call it
    freely; none of them puts a question to anybody, and none of them decides
    what id a question will get — which it did decide, before this existed,
    simply by being read first.

    A candidate that has already been asked carries `asked_id`, read back rather
    than created. One that has not carries `null` and a stable `candidate_key`.
    """

    resolved = _project(project_id, memory)
    # The service is asked for everything and the schema does the cut (`D-281`).
    # Truncating twice made `omitted` zero on every call ever made — `of`
    # subtracts what it was given from what it shows — so a project with more
    # candidates than the ceiling was told none were left out, and `total`
    # reported the page. `candidates` applies its own limit after iterating
    # every pending clarification, so asking for all of them costs nothing.
    found = clarifications.candidates(resolved, include_deferred=include_deferred)
    return QuestionCandidateListResponse.of(found, limit=limit)


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

    Nor is every answer a decision. A disposition that does not settle the
    question records what was said and leaves it open, and the response reports
    that in `question_settled` rather than making the caller infer it.
    """

    resolved = _project(project_id, memory)
    outcome = clarifications.answer(
        resolved,
        MessageId(question_id),
        body.answer,
        actor_id=body.actor_id,
        idempotency_key=body.idempotency_key,
        disposition=body.disposition,
        assumption_id=body.assumption_id,
    )
    return ClarificationResponse.of(outcome)


@router.get("/projects/{project_id}/setup", response_model=SetupStateResponse)
def setup_state(project_id: str, memory: Memory, setup: Setup) -> SetupStateResponse:
    """Report what this project is configured to do.

    Deliberately a different route from `/readiness`, and the separation is the
    point: setup readiness and knowledge readiness answer different questions,
    and a client that could read one as the other would tell a person a
    well-understood project can publish.

    Never refuses over sparse knowledge. Every blocking gap names an unmade
    choice, a missing authorisation, an integrity failure, an unavailable
    provider, or an unsupported feature.
    """

    resolved = _project(project_id, memory)
    readiness = setup.readiness(resolved)
    configuration = setup.configuration(resolved)
    return SetupStateResponse(
        project_id=str(resolved),
        setup_state=readiness.state.value,
        blocks_anything=readiness.blocks_anything,
        gaps=[
            SetupGapResponse(
                field=gap.field_name,
                capability=gap.capability,
                blocking=gap.blocking,
                reason=gap.reason,
                next_action=gap.next_action,
            )
            for gap in readiness.gaps
        ],
        configuration=configuration.as_dict(),
        unknown_fields=list(configuration.unknown_fields()),
        disclosures=[
            {"field": value.field_name, "value": value.value, "state": value.state.value}
            for value in configuration.disclosures()
        ],
        targets=[_target_response(setup, resolved, target) for target in setup.targets(resolved)],
    )


@router.post(
    "/projects/{project_id}/setup/configuration",
    response_model=SetupStateResponse,
    status_code=status.HTTP_200_OK,
)
def configure_field(
    project_id: str, body: ConfigureFieldRequest, memory: Memory, setup: Setup
) -> SetupStateResponse:
    """Set one configuration field.

    **The first write path setup has ever had.** `SetupService.set_value` was
    written, tested, and reachable from nothing — as were `register_target` and
    `record_connection` — so the four tables migration `0020` created held zero
    rows on the deployed system. Stage one of the product was schema.

    Returns the whole setup state rather than the one value. A caller setting a
    field wants to know what it unblocked, and the gaps are recomputed here
    anyway.
    """

    resolved = _project(project_id, memory)
    try:
        state = ValueState(body.state)
    except ValueError as error:
        valid = ", ".join(v.value for v in ValueState)
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown value state {body.state!r}. Valid: {valid}",
        ) from error
    try:
        setup.set_value(
            resolved,
            body.field,
            body.value,
            state,
            evidence=body.evidence,
            confirmed_by=body.confirmed_by,
            derived_from_knowledge_id=body.derived_from_knowledge_id,
        )
    except (ConfigurationError, SetupError) as error:
        # `ConfigurationError` covers both an unknown field and a field that
        # may not be configured at all. Both are the caller naming something
        # wrong, which is 422 rather than 500 — and the message names what is
        # valid, because a rejection that does not is a guessing game.
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return setup_state(project_id, memory, setup)


@router.post(
    "/projects/{project_id}/publication-targets",
    response_model=PublicationTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_publication_target(
    project_id: str, body: RegisterTargetRequest, memory: Memory, setup: Setup
) -> PublicationTargetResponse:
    """Register where this project may publish — the output repository.

    A coordinate lives here and **never on a publication request**. That is the
    rule `publication_targets.py` states outright: *"A request may not carry a
    coordinate… Requests name a `target_id` or nothing."* Otherwise every
    authorisation check is advisory, because the caller could name a destination
    the check never saw.
    """

    resolved = _project(project_id, memory)
    try:
        provider = Provider(body.provider)
        purpose = TargetPurpose(body.purpose)
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown provider or purpose: {body.provider!r}, {body.purpose!r}. "
            f"Providers: {', '.join(p.value for p in Provider)}. "
            f"Purposes: {', '.join(p.value for p in TargetPurpose)}",
        ) from error
    try:
        target = setup.register_target(
            resolved,
            provider,
            body.name,
            purpose=purpose,
            configuration=body.configuration,
            connection_id=body.connection_id,
            make_default=body.make_default,
        )
    except TargetError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    except DefaultConflictError as error:
        # 409, not 422. The request is well-formed and the project's state
        # refuses it — and the remedy is `set_default`, which the message names.
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "default_target_conflict",
            f"{error} To change which target is the default, use "
            f"POST /v1/projects/{{id}}/publication-targets/default.",
        ) from error
    return _target_response(setup, resolved, target)


@router.post(
    "/projects/{project_id}/publication-targets/default",
    response_model=PublicationTargetResponse,
)
def set_default_target(
    project_id: str, body: SetDefaultTargetRequest, memory: Memory, setup: Setup
) -> PublicationTargetResponse:
    """Point a purpose at a different registered target.

    There was no way to do this. `register_target(make_default=True)` refuses
    once a default exists, so a project's output destination could be chosen
    once and never changed — which is not a destination, it is a commitment.
    """

    resolved = _project(project_id, memory)
    try:
        purpose = TargetPurpose(body.purpose)
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown purpose {body.purpose!r}. Valid: {', '.join(p.value for p in TargetPurpose)}",
        ) from error
    try:
        target = setup.set_default(resolved, body.target_id, purpose=purpose)
    except SetupNotFoundError as error:
        raise not_found("publication_target", body.target_id) from error
    except TargetError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return _target_response(setup, resolved, target)


@router.get("/projects/{project_id}/connections", response_model=ProviderConnectionListResponse)
def list_connections(
    project_id: str, memory: Memory, setup: Setup
) -> ProviderConnectionListResponse:
    """What this project has connected. **Never a credential.**"""

    resolved = _project(project_id, memory)
    connections = setup.connections(resolved)
    return ProviderConnectionListResponse(
        project_id=str(resolved),
        results=[ProviderConnectionResponse.of(c) for c in connections],
        total=len(connections),
    )


@router.post(
    "/projects/{project_id}/connections",
    response_model=ProviderConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_connection(
    project_id: str, body: RecordConnectionRequest, memory: Memory, setup: Setup
) -> ProviderConnectionResponse:
    """Record permission to reach a provider, never the means.

    The domain refuses a `credential_reference` that looks like a credential
    itself, because this record is returned to callers and a secret in it is a
    secret disclosed — already written somewhere readable, and not unwritten by
    removing it afterwards.
    """

    resolved = _project(project_id, memory)
    try:
        provider = Provider(body.provider)
        state = AuthorizationState(body.state)
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown provider or authorization state: {body.provider!r}, {body.state!r}",
        ) from error
    try:
        connection = setup.record_connection(
            resolved,
            provider,
            credential_reference=body.credential_reference,
            state=state,
            authorized_by=body.authorized_by,
            detail=body.detail,
        )
    except TargetError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return ProviderConnectionResponse.of(connection)


@router.post(
    "/projects/{project_id}/connections/{connection_id}/authorization",
    response_model=ProviderConnectionResponse,
)
def authorize_connection(
    project_id: str,
    connection_id: str,
    body: AuthorizeConnectionRequest,
    memory: Memory,
    setup: Setup,
) -> ProviderConnectionResponse:
    """Move a connection's authorisation state after checking it.

    `record_connection` only inserts, so a connection created `never_granted`
    could never become `granted` — and re-recording instead leaves a second row
    behind on every attempt.
    """

    resolved = _project(project_id, memory)
    try:
        state = AuthorizationState(body.state)
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown authorization state {body.state!r}. "
            f"Valid: {', '.join(s.value for s in AuthorizationState)}",
        ) from error
    try:
        connection = setup.authorize_connection(
            resolved,
            connection_id,
            state,
            authorized_by=body.authorized_by,
            detail=body.detail,
            verified_at=datetime.now(UTC),
        )
    except SetupNotFoundError as error:
        raise not_found("connection", connection_id) from error
    except TargetError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return ProviderConnectionResponse.of(connection)


@router.get("/projects/{project_id}/setup/questions", response_model=SetupQuestionListResponse)
def setup_questions(
    project_id: str,
    memory: Memory,
    setup: Setup,
    blocking_only: Annotated[bool, Query()] = False,
) -> SetupQuestionListResponse:
    """Unsettled questions about configuration, never about the product.

    A GET, unlike `/clarifications`. A setup question is recorded when someone
    decides to ask it; there is nothing to materialise on read, so nothing here
    mutates.
    """

    resolved = _project(project_id, memory)
    questions = setup.open_questions(resolved, blocking_only=blocking_only)
    return SetupQuestionListResponse(
        project_id=str(resolved),
        questions=[
            SetupQuestionResponse(
                setup_question_id=str(question.id),
                purpose=question.purpose.value,
                question=question.question,
                field=question.field_name,
                blocking=question.blocking,
                suggested_answer=question.suggested_answer,
                suggestion_evidence=question.suggestion_evidence,
                becomes_default=question.becomes_default,
                disposition=question.disposition.value,
            )
            for question in questions
        ],
        count=len(questions),
    )


@router.get(
    "/projects/{project_id}/publication-targets",
    response_model=PublicationTargetListResponse,
)
def publication_targets(
    project_id: str, memory: Memory, setup: Setup
) -> PublicationTargetListResponse:
    """Where this project may publish, including where it currently cannot.

    Unavailable targets are included. A target that vanished when its
    authorisation expired would take the decision with it.
    """

    resolved = _project(project_id, memory)
    targets = setup.targets(resolved)
    return PublicationTargetListResponse(
        project_id=str(resolved),
        results=[_target_response(setup, resolved, target) for target in targets],
        total=len(targets),
    )


def _target_response(
    setup: SetupService, project_id: ProjectId, target: Any
) -> PublicationTargetResponse:
    authorization = setup.authorization_for(project_id, target.connection_id)
    return PublicationTargetResponse(
        target_id=str(target.id),
        name=target.name,
        provider=target.provider.value,
        purpose=target.purpose.value,
        is_default=target.is_default,
        enabled=target.enabled,
        available=target.available(authorization),
        unavailable_reason=target.unavailable_reason(authorization),
        authorization=authorization.value,
        configuration=dict(target.configuration or {}),
    )


@router.get(
    "/projects/{project_id}/preliminary-context",
    response_model=PreliminaryContextResponse,
)
def preliminary_context(
    project_id: str,
    memory: Memory,
    preliminary: Preliminary,
    purpose: Annotated[str, Query()] = "discovery",
) -> PreliminaryContextResponse:
    """Compose the most useful view this project's current state supports.

    A GET because it creates nothing and decides nothing. That is the property
    that makes it safe at any readiness: it cannot confirm, cannot accept, and
    cannot promote, so there is no state in which producing it is a risk worth
    withholding output over.

    Distinct from `/context`, which shows what a person confirmed — the right
    default for building against, and the wrong one for a project someone
    described in a sentence yesterday. Here, known, proposed, assumed and
    unknown are four separate collections and never merge.
    """

    resolved = _project(project_id, memory)
    try:
        chosen = AssemblyPurpose(purpose)
    except ValueError as error:
        valid = ", ".join(p.value for p in AssemblyPurpose)
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            message("refusal.unknown_purpose", purpose=purpose, valid=valid),
        ) from error
    return PreliminaryContextResponse.of(preliminary.compose(resolved, chosen))


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
            message("refusal.unknown_purpose", purpose=purpose, valid=valid),
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


@router.post(
    "/projects/{project_id}/deliverables",
    response_model=DeliverableResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_deliverable(
    project_id: str,
    body: RecordDeliverableRequest,
    memory: Memory,
    assembly: Assembly,
    readiness: Readiness,
    deliverables: Deliverables,
) -> DeliverableResponse:
    """Record what an assembly produced, as a durable deliverable (N20).

    **201, unlike assembly's GET.** Something durable now exists that a caller
    can resolve by id later — which is exactly the difference between a
    deliverable and an assembly, whose `package_id` is fresh per call because a
    computation should not hand out an identity that outlives it.

    Idempotent by content: recording the same output twice returns the same
    deliverable, and `recorded` says which happened.

    Nothing is rendered, stored, or published here. That is N21's concern and
    belongs to whoever owns the destination.
    """

    resolved = _project(project_id, memory)
    try:
        purpose = AssemblyPurpose(body.purpose)
    except ValueError as error:
        valid = ", ".join(p.value for p in AssemblyPurpose)
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown purpose {body.purpose!r}; expected one of {valid}",
        ) from error

    assembled = assembly.assemble(resolved, purpose, include_proposed=body.include_proposed)
    deliverable, created = deliverables.record(resolved, assembled, body.recorded_by)
    return DeliverableResponse.of(deliverable, readiness.knowledge_revision(resolved), created)


@router.get("/projects/{project_id}/deliverables", response_model=DeliverableListResponse)
def list_deliverables(
    project_id: str,
    memory: Memory,
    readiness: Readiness,
    deliverables: Deliverables,
    states: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
) -> DeliverableListResponse:
    """Recorded deliverables, newest first.

    The port Studio's `listDeliverables` was blocked on. It could not be
    written before because assembly UUIDs are not identity, and a route that
    invented one would have handed a client an id resolving to nothing.
    """

    resolved = _project(project_id, memory)
    records = deliverables.list_for_project(resolved, states)
    return DeliverableListResponse.of(records, readiness.knowledge_revision(resolved), limit)


@router.get(
    "/projects/{project_id}/deliverables/{deliverable_id}", response_model=DeliverableResponse
)
def read_deliverable(
    project_id: str,
    deliverable_id: str,
    memory: Memory,
    readiness: Readiness,
    deliverables: Deliverables,
) -> DeliverableResponse:
    """One deliverable, scoped to its project."""

    resolved = _project(project_id, memory)
    try:
        deliverable = deliverables.get(resolved, deliverable_id)
    except DeliverableNotFoundError as error:
        raise not_found("deliverable", deliverable_id) from error
    return DeliverableResponse.of(deliverable, readiness.knowledge_revision(resolved))


@router.post(
    "/projects/{project_id}/deliverables/{deliverable_id}/supersede",
    response_model=DeliverableResponse,
)
def supersede_deliverable(
    project_id: str,
    deliverable_id: str,
    body: SupersedeDeliverableRequest,
    memory: Memory,
    readiness: Readiness,
    deliverables: Deliverables,
) -> DeliverableResponse:
    """Mark a deliverable replaced by a later one.

    The record survives. What was shipped stays readable, because the question
    a deliverable answers is historical and a deleted answer answers nothing.
    """

    resolved = _project(project_id, memory)
    try:
        deliverable = deliverables.supersede(resolved, deliverable_id, body.replacement_id)
    except DeliverableNotFoundError as error:
        raise not_found("deliverable", deliverable_id) from error
    except InvalidDeliverableTransitionError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "invalid_state_transition", str(error)) from error
    return DeliverableResponse.of(deliverable, readiness.knowledge_revision(resolved))


@router.post(
    "/projects/{project_id}/deliverables/{deliverable_id}/withdraw",
    response_model=DeliverableResponse,
)
def withdraw_deliverable(
    project_id: str,
    deliverable_id: str,
    body: WithdrawDeliverableRequest,
    memory: Memory,
    readiness: Readiness,
    deliverables: Deliverables,
) -> DeliverableResponse:
    """Mark a deliverable as one the project no longer stands behind.

    Distinct from superseded, which names a replacement. Withdrawn says there
    is none, and collapsing the two would leave a reader unable to tell "there
    is a newer one" from "do not use this".
    """

    resolved = _project(project_id, memory)
    try:
        deliverable = deliverables.withdraw(resolved, deliverable_id, body.reason)
    except DeliverableNotFoundError as error:
        raise not_found("deliverable", deliverable_id) from error
    except InvalidDeliverableTransitionError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "invalid_state_transition", str(error)) from error
    return DeliverableResponse.of(deliverable, readiness.knowledge_revision(resolved))


@router.post(
    "/projects/{project_id}/assumptions",
    response_model=AssumptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_assumption(
    project_id: str,
    body: RecordAssumptionRequest,
    memory: Memory,
    assumptions: Assumptions,
) -> AssumptionResponse:
    """Record what KAE proceeded on in place of information nobody supplied.

    Proposed, whoever asked. Acceptance is a separate act by a named person,
    because a caller that could record one already accepted would be recording
    a decision nobody made.

    **`origin` may not be `user_stated`.** Everything reaching this route is
    KAE's — inferred, recommended and accepted, or an alternative nobody chose.
    A caller that could claim a person said something would be manufacturing
    the one distinction the origin exists to make.
    """

    resolved = _project(project_id, memory)
    if body.origin == AssumptionOrigin.USER_STATED.value:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            "an assumption recorded through this route is KAE's, so it cannot be "
            "user_stated: that origin exists to mark what a person actually said",
        )
    try:
        origin = AssumptionOrigin(body.origin)
    except ValueError as error:
        valid = ", ".join(
            o.value for o in AssumptionOrigin if o is not AssumptionOrigin.USER_STATED
        )
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown origin {body.origin!r}; expected one of {valid}",
        ) from error
    try:
        recorded = assumptions.record(
            resolved,
            origin=origin,
            subject=body.subject,
            assumed_value=body.assumed_value,
            reason=body.reason,
            consequence=Consequence(body.consequence),
            confidence=body.confidence,
            reversible=body.reversible,
            revisit=RevisitTrigger(body.revisit),
            evidence=body.evidence,
        )
    except (ValueError, DomainInvariantError) as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return AssumptionResponse.of(recorded)


@router.get("/projects/{project_id}/assumptions", response_model=AssumptionListResponse)
def list_assumptions(
    project_id: str,
    memory: Memory,
    assumptions: Assumptions,
    active_only: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
) -> AssumptionListResponse:
    """What this project is proceeding on without knowing."""

    resolved = _project(project_id, memory)
    return AssumptionListResponse.of(
        assumptions.list_for_project(resolved, active_only=active_only), limit
    )


@router.post(
    "/projects/{project_id}/assumptions/{assumption_id}/accept",
    response_model=AssumptionResponse,
)
def accept_assumption(
    project_id: str,
    assumption_id: str,
    body: AcceptAssumptionRequest,
    memory: Memory,
    assumptions: Assumptions,
) -> AssumptionResponse:
    """Relay a person taking responsibility for proceeding on an assumption.

    Accepting is not confirming. It records willingness to build on a guess,
    which is a weaker and more honest claim than believing it true.
    """

    resolved = _project(project_id, memory)
    try:
        accepted = assumptions.accept(resolved, assumption_id, body.actor)
    except AssumptionNotFoundError as error:
        raise not_found("assumption", assumption_id) from error
    except InvalidAssumptionTransitionError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "invalid_state_transition", str(error)) from error
    except ValueError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return AssumptionResponse.of(accepted)
