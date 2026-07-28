"""Projects, sessions, messages, knowledge, and runs."""

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import AgentRunId, KnowledgeItemId, ProjectId, SessionId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.workspace import ActorType, MessageType, SessionType

from ..dependencies import Memory, SessionFactory
from ..errors import not_found
from ..events import StreamConfig, run_events
from ..parsing import parse_enum
from ..schemas import (
    CreateProjectRequest,
    EnqueueRunRequest,
    KnowledgeResponse,
    MessageResponse,
    OpenSessionRequest,
    ProjectResponse,
    RecordMessageRequest,
    RunResponse,
    SessionResponse,
)

router = APIRouter(prefix="/v1", tags=["workspace"])


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(body: CreateProjectRequest, memory: Memory) -> ProjectResponse:
    """Create a durable project."""

    return ProjectResponse.of(memory.create_project(body.name, body.key, body.description))


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(memory: Memory) -> list[ProjectResponse]:
    """List every project, newest first."""

    return [ProjectResponse.of(project) for project in memory.list_projects()]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, memory: Memory) -> ProjectResponse:
    """Return one project."""

    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    return ProjectResponse.of(project)


@router.post(
    "/projects/{project_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def open_session(project_id: str, body: OpenSessionRequest, memory: Memory) -> SessionResponse:
    """Open a working session."""

    _require_project(memory, project_id)
    session_type = parse_enum(SessionType, body.session_type, "session_type")
    return SessionResponse.of(memory.open_session(ProjectId(project_id), session_type))


@router.get("/projects/{project_id}/sessions", response_model=list[SessionResponse])
def list_sessions(project_id: str, memory: Memory) -> list[SessionResponse]:
    """List a project's sessions."""

    _require_project(memory, project_id)
    return [
        SessionResponse.of(session)
        for session in memory.sessions_for_project(ProjectId(project_id))
    ]


@router.post("/sessions/{session_id}/close", response_model=SessionResponse)
def close_session(session_id: str, memory: Memory) -> SessionResponse:
    """Close a session."""

    return SessionResponse.of(memory.close_session(SessionId(session_id)))


@router.post(
    "/sessions/{session_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_message(session_id: str, body: RecordMessageRequest, memory: Memory) -> MessageResponse:
    """Record a message verbatim as source evidence.

    The stored text is never rewritten by extraction, so the original wording
    stays available as the source of anything derived from it.
    """

    session = memory.get_session(SessionId(session_id))
    if session is None:
        raise not_found("session", session_id)
    return MessageResponse.of(
        memory.record_message(
            session.project_id,
            session.id,
            body.content,
            actor_type=parse_enum(ActorType, body.actor_type, "actor_type"),
            message_type=parse_enum(MessageType, body.message_type, "message_type"),
            actor_id=body.actor_id,
        )
    )


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def list_messages(session_id: str, memory: Memory) -> list[MessageResponse]:
    """List a session's messages in submission order."""

    return [
        MessageResponse.of(message)
        for message in memory.messages_for_session(SessionId(session_id))
    ]


@router.get("/projects/{project_id}/knowledge", response_model=list[KnowledgeResponse])
def list_knowledge(
    project_id: str, memory: Memory, lifecycle: str | None = None
) -> list[KnowledgeResponse]:
    """List a project's knowledge.

    Unfiltered by default. The workspace needs to show proposed candidates beside
    confirmed knowledge, because the difference between them is the thing a user
    acts on.
    """

    _require_project(memory, project_id)
    state = None if lifecycle is None else parse_enum(LifecycleState, lifecycle, "lifecycle")
    items = memory.retrieve_knowledge(ProjectId(project_id), lifecycle=state)
    return [KnowledgeResponse.of(item) for item in items]


@router.post("/knowledge/{item_id}/confirm", response_model=KnowledgeResponse)
def confirm_knowledge(item_id: str, memory: Memory) -> KnowledgeResponse:
    """Confirm a candidate.

    Confirmation is a human act. No agent performs it, which is why this is an
    endpoint and not a step inside a run.
    """

    return KnowledgeResponse.of(memory.confirm_knowledge(KnowledgeItemId(item_id)))


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_run(project_id: str, body: EnqueueRunRequest, memory: Memory) -> RunResponse:
    """Enqueue agent work and return immediately.

    **202, never 200.** The run is durable when this returns, but it has not
    started: a worker claims it. The browser does not own the run (ADR-0009), so
    closing the tab cannot lose it.

    Idempotent on ``idempotency_key`` — a retried request converges on the
    original run rather than creating a second.
    """

    _require_project(memory, project_id)
    role = parse_enum(AgentRole, body.role, "role")
    run = memory.enqueue_run(
        ProjectId(project_id),
        role,
        body.idempotency_key,
        session_id=None if body.session_id is None else SessionId(body.session_id),
        input_context=body.input_context,
    )
    return RunResponse.of(run)


@router.get("/projects/{project_id}/runs", response_model=list[RunResponse])
def list_runs(project_id: str, memory: Memory, run_status: str | None = None) -> list[RunResponse]:
    """List a project's execution history, most recent first."""

    _require_project(memory, project_id)
    state = None if run_status is None else parse_enum(RunStatus, run_status, "status")
    return [RunResponse.of(run) for run in memory.runs_for_project(ProjectId(project_id), state)]


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, memory: Memory) -> RunResponse:
    """Return one run. This is what a client polls while work proceeds."""

    run = memory.get_run(AgentRunId(run_id))
    if run is None:
        raise not_found("run", run_id)
    return RunResponse.of(run)


@router.get(
    "/runs/{run_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_run_events(run_id: str, factory: SessionFactory) -> StreamingResponse:
    """Stream run progress as Server-Sent Events.

    A convenience over ``GET /v1/runs/{id}``, never a replacement for it.
    Correctness must not depend on an uninterrupted browser connection
    (ADR-0009), so a client that misses the stream entirely can still read the
    same state with an ordinary request.

    Emits the current state immediately, then on every change to status,
    attempt, checkpoint, or error. Closes when the run reaches a terminal
    status.
    """

    return StreamingResponse(
        run_events(factory, AgentRunId(run_id), StreamConfig()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/knowledge", response_model=list[KnowledgeResponse])
def knowledge_produced_by(run_id: str, memory: Memory) -> list[KnowledgeResponse]:
    """Return the knowledge a run produced.

    One run, one result: replaying a completed run returns its original output
    rather than producing a second set.
    """

    return [KnowledgeResponse.of(item) for item in memory.knowledge_produced_by(AgentRunId(run_id))]


def _require_project(memory: Memory, project_id: str) -> None:
    """Reject early rather than returning an empty list for a project that does not exist.

    An empty collection and a wrong identifier are different answers, and a
    client cannot tell them apart from a 200.
    """

    if memory.get_project(ProjectId(project_id)) is None:
        raise not_found("project", project_id)
