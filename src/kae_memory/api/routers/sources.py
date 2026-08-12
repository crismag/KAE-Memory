"""Where a project's material comes from, over HTTP (`D-21`, `AUD-005`).

Studio held sources in a process dictionary, so a person who connected a
repository, set its include and exclude paths, and pinned a revision lost all of
it on the next deploy. `ADR-0004` ruled that KAE-Memory owns the source
reference. These are the routes over that record.

**A source names material and never holds it.** Nothing here accepts file
bodies, and the ruling this implements exists precisely to stop a repository
being copied wholesale into this database.

**Nothing here reads a provider.** Studio contacts GitHub, resolves a revision,
and discovers a refusal; these record what it was told. Memory verifying the
same thing independently would give two systems an opinion about one lifecycle.
"""

from fastapi import APIRouter, status

from kae_memory.application.source_service import SourceNotFoundError
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import ProjectId

from ..dependencies import Memory, Sources
from ..errors import ApiError, not_found
from ..schemas import (
    ClassifySourceRequest,
    PinSourceRequest,
    RecordSourceStateRequest,
    RegisterSourceRequest,
    SourceResponse,
)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["sources"])


def _project(project_id: str, memory: Memory) -> ProjectId:
    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    return project.id


def _refuse(error: DomainInvariantError) -> ApiError:
    return ApiError(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error))


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def register_source(
    project_id: str, body: RegisterSourceRequest, memory: Memory, sources: Sources
) -> SourceResponse:
    """Record where material comes from, or return the source already there.

    Idempotent by `(kind, location)`. Registering the same repository twice is
    one source registered twice, so a caller that loses its response can retry
    without first asking whether it succeeded.

    `201` either way, deliberately: the caller's intent — *this project draws on
    this location* — holds after both, and a `200`/`201` split would invite a
    client to branch on which of two identical outcomes occurred.
    """

    resolved = _project(project_id, memory)
    try:
        return SourceResponse.of(
            sources.register(
                resolved,
                kind=body.kind,
                location=body.location,
                state=body.state,
                connection_id=body.connection_id,
                scope=body.scope,
                disposition=body.disposition,
            )
        )
    except DomainInvariantError as error:
        raise _refuse(error) from error


@router.get("/sources", response_model=list[SourceResponse])
def list_sources(project_id: str, memory: Memory, sources: Sources) -> list[SourceResponse]:
    """Every source this project has, oldest first.

    An empty list means the project has none — a real answer, and the one that
    could not be given while the store lived in a process that had just
    restarted.
    """

    resolved = _project(project_id, memory)
    return [SourceResponse.of(source) for source in sources.sources(resolved)]


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(project_id: str, source_id: str, memory: Memory, sources: Sources) -> SourceResponse:
    resolved = _project(project_id, memory)
    try:
        return SourceResponse.of(sources.get(resolved, source_id))
    except SourceNotFoundError as error:
        raise not_found("source", source_id) from error


@router.post("/sources/{source_id}/state", response_model=SourceResponse)
def record_source_state(
    project_id: str,
    source_id: str,
    body: RecordSourceStateRequest,
    memory: Memory,
    sources: Sources,
) -> SourceResponse:
    """Record what Studio observed against the provider."""

    resolved = _project(project_id, memory)
    try:
        return SourceResponse.of(sources.record_state(resolved, source_id, body.state, body.detail))
    except SourceNotFoundError as error:
        raise not_found("source", source_id) from error
    except DomainInvariantError as error:
        raise _refuse(error) from error


@router.post("/sources/{source_id}/pin", response_model=SourceResponse)
def pin_source(
    project_id: str,
    source_id: str,
    body: PinSourceRequest,
    memory: Memory,
    sources: Sources,
) -> SourceResponse:
    """Fix this source to an immutable revision.

    The point of the record. A branch moves and a commit does not, so a claim
    drawn from *"the main branch"* cannot be rechecked against what the branch
    actually said at the time it was read.
    """

    resolved = _project(project_id, memory)
    try:
        return SourceResponse.of(
            sources.pin(resolved, source_id, body.revision, body.digest, body.state)
        )
    except SourceNotFoundError as error:
        raise not_found("source", source_id) from error
    except DomainInvariantError as error:
        raise _refuse(error) from error


@router.post("/sources/{source_id}/disposition", response_model=SourceResponse)
def classify_source(
    project_id: str,
    source_id: str,
    body: ClassifySourceRequest,
    memory: Memory,
    sources: Sources,
) -> SourceResponse:
    """Record where this source's material is to live (`ADR-0004`).

    **Stored, and enforced by nothing yet.** The five dispositions gate
    ingestion at volume; making `EPHEMERAL` actually discard content is
    behaviour these routes do not implement. Recording the decision first is the
    cheaper order — reclassifying real data afterwards is the expensive one —
    and it must not be read as the rule being in force.
    """

    resolved = _project(project_id, memory)
    try:
        return SourceResponse.of(sources.classify(resolved, source_id, body.disposition))
    except SourceNotFoundError as error:
        raise not_found("source", source_id) from error
    except DomainInvariantError as error:
        raise _refuse(error) from error
