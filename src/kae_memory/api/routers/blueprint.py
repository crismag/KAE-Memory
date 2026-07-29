"""Blueprint generation, Markdown export, and knowledge traceability.

FR-008: statements link back to their supporting evidence, are labelled, and
export as Markdown. AT-004 is satisfied by the pair — a statement carries its
knowledge item, and the trace endpoint resolves that item to the project,
session, message, and run behind it.
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from kae_memory.application.blueprint_service import Blueprint, render_markdown
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId

from ..dependencies import Blueprints, Memory, Readiness
from ..errors import not_found
from ..schemas import BlueprintResponse, TraceResponse

router = APIRouter(prefix="/v1", tags=["blueprint"])


def _build(
    project_id: str, memory: Memory, readiness: Readiness, blueprints: Blueprints
) -> Blueprint:
    """Assemble a blueprint against the project's current readiness.

    Readiness is recalculated rather than read from the latest snapshot, so a
    blueprint can never claim eligibility that a later confirmation invalidated.
    """

    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    snapshot = readiness.calculate(project.id)
    return blueprints.generate(
        project.id,
        project.name,
        snapshot.percentage,
        snapshot.draft_eligible,
        snapshot.implementation_eligible,
        snapshot.missing_mandatory_areas,
    )


@router.get("/projects/{project_id}/blueprint", response_model=BlueprintResponse)
def get_blueprint(
    project_id: str, memory: Memory, readiness: Readiness, blueprints: Blueprints
) -> BlueprintResponse:
    """Render confirmed knowledge as a blueprint.

    Returned even below the draft threshold, marked incomplete. Refusing would
    tell a user nothing about *what is missing*, and for an early project the
    missing-area list is the most useful thing the blueprint can say.

    Every statement is a confirmed knowledge item's own text. No model writes
    blueprint prose (ADR-0016), because generated connective text would be
    unattributable — the failure FR-008's labelling exists to prevent.
    """

    return BlueprintResponse.of(_build(project_id, memory, readiness, blueprints))


@router.get(
    "/projects/{project_id}/blueprint.md",
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/markdown": {}}}},
)
def export_blueprint(
    project_id: str, memory: Memory, readiness: Readiness, blueprints: Blueprints
) -> PlainTextResponse:
    """Export the same blueprint as Markdown (FR-008).

    A rendering of the same structure the JSON exposes, so the two cannot
    disagree. Every statement keeps its label and knowledge identifier, so an
    exported document is as traceable as the API response.
    """

    blueprint = _build(project_id, memory, readiness, blueprints)
    return PlainTextResponse(render_markdown(blueprint), media_type="text/markdown")


@router.get("/knowledge/{item_id}/trace", response_model=TraceResponse)
def trace_knowledge(item_id: str, blueprints: Blueprints) -> TraceResponse:
    """Return a knowledge item's chain of custody.

    Project, the sessions and messages it came from, the run that produced it,
    the runs that consumed it, and every version with its provenance — the answer
    to "why does the blueprint say this?"
    """

    trace = blueprints.trace(KnowledgeItemId(item_id))
    if trace is None:
        raise not_found("knowledge_item", item_id)
    return TraceResponse.of(trace)
