"""Classified observations and operational state over HTTP (N3, ADR-0023).

The reads and the settle command N4 built on MCP, reached through the transport
Studio actually speaks. The application service is the same one; nothing here
decides what a transition means.

Everything returned is a **report**. `authority` says who claimed it and
`state` says whether anyone has accepted the claim — a milestone is never
completed because a sentence said so, and a record still in `proposed` has been
read by nobody.
"""

from typing import Annotated

from fastapi import APIRouter, Query, status

from kae_memory.application.classification_service import OperationalRecordNotFoundError
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.observation import (
    InvalidOperationalTransitionError,
    OperationalState,
    RetentionTier,
)

from ..dependencies import Classification, Memory
from ..errors import ApiError, not_found
from ..schemas import (
    ClassificationListResponse,
    OperationalRecordResponse,
    OperationalStateResponse,
    SettleOperationalRequest,
)

router = APIRouter(prefix="/v1", tags=["classification"])


def _project(project_id: str, memory: Memory) -> ProjectId:
    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    return project.id


@router.get("/projects/{project_id}/operational-state", response_model=OperationalStateResponse)
def operational_state(
    project_id: str,
    memory: Memory,
    classification: Classification,
    states: Annotated[list[str] | None, Query()] = None,
    kinds: Annotated[list[str] | None, Query()] = None,
    subject: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OperationalStateResponse:
    """Where the work stands, as reported.

    Defaults to the states a briefing may show as current. Asking for a
    terminal state is allowed and explicit: reviewing what was rejected is a
    real question, and it should not be answered by accident.
    """

    resolved = _project(project_id, memory)
    records = classification.operational_state(
        resolved, states=states, kinds=kinds, subject=subject
    )
    return OperationalStateResponse.of(records, limit=limit, states=states)


@router.get("/projects/{project_id}/classifications", response_model=ClassificationListResponse)
def classifications(
    project_id: str,
    memory: Memory,
    classification: Classification,
    tiers: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ClassificationListResponse:
    """Classified spans, each carrying the range of stored text it came from.

    A reader can check a classification against the words rather than against a
    summary of them, which is the whole reason spans are stored as real offsets.
    """

    resolved = _project(project_id, memory)
    selected: list[RetentionTier] | None = None
    if tiers:
        try:
            selected = [RetentionTier(tier) for tier in tiers]
        except ValueError as error:
            valid = ", ".join(tier.value for tier in RetentionTier)
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "invalid_argument",
                f"unknown retention tier; expected one of {valid}",
            ) from error

    rows = classification.classifications(resolved, selected)
    return ClassificationListResponse.of(
        rows,
        limit=limit,
        semantic=classification.semantic,
        classifier=classification.classifier_name,
        version=classification.classifier_version,
    )


@router.post(
    "/projects/{project_id}/operational-state/{record_id}/settle",
    response_model=OperationalRecordResponse,
)
def settle(
    project_id: str,
    record_id: str,
    body: SettleOperationalRequest,
    memory: Memory,
    classification: Classification,
) -> OperationalRecordResponse:
    """Relay a person's decision about a reported operational record.

    Settling is not verifying. It records that someone took responsibility for
    a claim; the record keeps saying who reported it and whether anything
    verified it. `actor` is required for the same reason `reviewer` is on
    confirmation — a decision nobody is named for cannot be audited.
    """

    resolved = _project(project_id, memory)
    try:
        target = OperationalState(body.state)
    except ValueError as error:
        valid = ", ".join(s.value for s in OperationalState)
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown state {body.state!r}; expected one of {valid}",
        ) from error

    try:
        record = classification.settle(resolved, record_id, target, body.actor, body.note)
    except OperationalRecordNotFoundError as error:
        raise not_found("operational record", record_id) from error
    except InvalidOperationalTransitionError as error:
        raise ApiError(status.HTTP_409_CONFLICT, "invalid_state_transition", str(error)) from error

    return OperationalRecordResponse.of(record)
