"""Projects, sessions, messages, knowledge, and runs."""

from fastapi import APIRouter, Response, status
from fastapi.responses import StreamingResponse

from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import AgentRunId, KnowledgeItemId, ProjectId, SessionId
from kae_memory.domain.lexical import group_related
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.workspace import ActorType, MessagePurpose, MessageType, SessionType

from ..dependencies import Memory, ProjectDeletion, Readiness, SessionFactory
from ..errors import ApiError, not_found
from ..events import StreamConfig, run_events
from ..parsing import parse_enum
from ..schemas import (
    ConfirmKnowledgeSetRequest,
    CreateProjectRequest,
    DeletionPlanResponse,
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
def create_project(
    body: CreateProjectRequest, memory: Memory, response: Response
) -> ProjectResponse:
    """Create a durable project, or return the one that already holds this key.

    Idempotent, matching `kae_create_project`. The two surfaces previously
    disagreed: this endpoint created a second project keyed `name-2` while the
    MCP tool resolved to the existing one. The same request should not mean two
    different things depending on which door it arrived through.

    ``201`` when a project was created, ``200`` when an existing one was
    returned, so a caller can tell without comparing identifiers.
    """

    project, created = memory.ensure_project(body.name, body.key, body.description)
    if not created:
        response.status_code = status.HTTP_200_OK
    return ProjectResponse.of(project)


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


@router.get("/projects/{project_id}/deletion-plan", response_model=DeletionPlanResponse)
def deletion_plan(project_id: str, deletion: ProjectDeletion) -> DeletionPlanResponse:
    """What deleting this project would remove. Changes nothing.

    Separate from the deletion and safe to call repeatedly, because reading the
    list is the part a person should take their time over. Fifty-five test
    projects were once cleared by hand-ordered SQL against production; the
    difference between that and this is that this can be read first.
    """

    plan = deletion.plan([project_id])
    if not plan.projects:
        raise not_found("project", project_id)
    summary = plan.projects[0]
    return DeletionPlanResponse(
        project_id=summary.project_id,
        name=summary.name,
        knowledge_revision=summary.knowledge_revision,
        rows=plan.rows,
        total_rows=plan.total_rows,
    )


@router.delete("/projects/{project_id}", response_model=DeletionPlanResponse)
def delete_project(project_id: str, deletion: ProjectDeletion) -> DeletionPlanResponse:
    """Delete this project and everything scoped to it, in one transaction.

    **Irreversible.** There is no archive and nothing is retained; the
    `deletion-plan` above is the only chance to see what goes.

    Returns what was removed rather than an empty body, so a caller can record
    it. One project per call deliberately: a batch is one decision covering many
    projects, and the ability to delete fifty in a request is the ability to
    delete forty-nine by accident.
    """

    plan = deletion.delete([project_id])
    if not plan.projects:
        raise not_found("project", project_id)
    summary = plan.projects[0]
    return DeletionPlanResponse(
        project_id=summary.project_id,
        name=summary.name,
        knowledge_revision=summary.knowledge_revision,
        rows=plan.rows,
        total_rows=plan.total_rows,
    )


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
    """Record a message verbatim as source evidence, and interpret it.

    The stored text is never rewritten by extraction, so the original wording
    stays available as the source of anything derived from it.

    **A person's message is enqueued for discovery extraction**, which is the
    edge this route was missing. N42 gave `kae_submit_observation` that edge and
    the capability register recorded, correctly, that Studio's equivalent is a
    conversation message — "a different durable act with its own session
    ordering". What nobody added was interpretation for that different act, so a
    project driven entirely through Studio stored every word a person said and
    derived nothing from any of it. The same failure N42 was written to fix,
    surviving in the adapter N42 did not touch.

    Only messages **from a person** are interpreted. An agent's own turn is
    already derived, and extracting from it would let a model's output re-enter
    as evidence for the next inference — a loop that manufactures confidence
    from nothing but its own prior output.

    **And only messages the caller says are about the project** (EM-2). This
    route used to interpret every human message unconditionally, so a browser
    suite proving the round trip works wrote twelve copies of one test sentence
    into a project's candidate knowledge. Nothing could have known not to:
    there was no way to say "store this, do not interpret it". A `diagnostic`
    or `conversation_control` message is still recorded, still attributed, and
    still visible in the transcript — it simply produces no candidates.

    The gate is on the caller's declaration, never on the words. A genuine
    requirement about testing software is project input and is extracted.
    """

    session = memory.get_session(SessionId(session_id))
    if session is None:
        raise not_found("session", session_id)
    actor_type = parse_enum(ActorType, body.actor_type, "actor_type")
    record = memory.record_message(
        session.project_id,
        session.id,
        body.content,
        actor_type=actor_type,
        message_type=parse_enum(MessageType, body.message_type, "message_type"),
        actor_id=body.actor_id,
        idempotency_key=body.idempotency_key,
        metadata=body.metadata,
        purpose=parse_enum(MessagePurpose, body.purpose, "purpose"),
    )

    if actor_type is ActorType.USER and record.message.is_interpreted and not record.replayed:
        # After the message is durable, and never in the same breath: evidence
        # capture must not depend on the queue being writable, and a submission
        # that failed because extraction could not be enqueued would lose the
        # text it was trying to keep.
        memory.enqueue_run(
            session.project_id,
            AgentRole.DISCOVERY,
            # Derived from the message, so a retry reuses the run rather than
            # paying for a second model call and producing a second set of
            # candidates for one thing a person said once.
            idempotency_key=f"message:{record.message.id}",
            session_id=session.id,
            input_context={"message_id": str(record.message.id), "source": "conversation"},
        )

    return MessageResponse.of(record.message)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def list_messages(session_id: str, memory: Memory) -> list[MessageResponse]:
    """List a session's messages in submission order."""

    return [
        MessageResponse.of(message)
        for message in memory.messages_for_session(SessionId(session_id))
    ]


#: Above this many statements, the listing stops grouping.
#:
#: Grouping compares every statement with every other. The number is a budget on
#: that, not a judgement about projects: past it the answer would still be
#: correct and would cost a reader more time than the grouping saves them.
MAX_GROUPED_STATEMENTS = 400


@router.get("/projects/{project_id}/knowledge", response_model=list[KnowledgeResponse])
def list_knowledge(
    project_id: str, memory: Memory, readiness: Readiness, lifecycle: str | None = None
) -> list[KnowledgeResponse]:
    """List a project's knowledge, and what each statement is about.

    Unfiltered by default. The workspace needs to show proposed candidates beside
    confirmed knowledge, because the difference between them is the thing a user
    acts on.

    **Each item now carries its discovery areas.** Memory has always held them
    and this listing did not return them, so a consumer could see what a project
    knows and not what any of it was about. The visible cost was a Definition
    page that reported the problem statement as uncomputable for every project
    in existence — "the problem" is the statements linked to
    `problem_and_value`, and nothing else identifies them.
    """

    _require_project(memory, project_id)
    resolved = ProjectId(project_id)
    state = None if lifecycle is None else parse_enum(LifecycleState, lifecycle, "lifecycle")
    items = memory.retrieve_knowledge(resolved, lifecycle=state)

    # One query for the project's assignments, not one per item. A statement can
    # belong to several areas, so this is a grouping rather than a lookup.
    by_item: dict[str, list[str]] = {}
    # And which claim inside an area, where the link says. Keyed by area so a
    # consumer asking "is this the problem or the value" has one place to look.
    claims_by_item: dict[str, dict[str, str]] = {}
    for link in readiness.area_links(resolved):
        by_item.setdefault(str(link.knowledge_item_id), []).append(link.area_key)
        if link.claim_key:
            claims_by_item.setdefault(str(link.knowledge_item_id), {})[link.area_key] = (
                link.claim_key
            )

    # Which statements say adjacent things (`PPA-15`, `ES-5`).
    #
    # **Computed here and stored nowhere.** Grouping is not merging: every
    # statement stays whole, visible and separately confirmable, which is why
    # this can ship while `EM-3`'s ruling on unattended merging stays open.
    #
    # Bounded rather than left to grow. Grouping is O(n²) in a project's
    # statements — a few milliseconds at the largest real project seen so far
    # (178 statements), and not a promise for a project ten times that. Past the
    # cap the listing returns no groups **and says so** through the absence,
    # because a slow listing is worse than an ungrouped one and a silently
    # partial grouping is worse than both.
    group_of: dict[str, int] = {}
    if len(items) <= MAX_GROUPED_STATEMENTS:
        for index, group in enumerate(
            group_related([(str(item.id), item.current_version.content) for item in items])
        ):
            for member in group:
                group_of[member] = index

    return [
        KnowledgeResponse.of(
            item,
            sorted(by_item.get(str(item.id), [])),
            claims_by_item.get(str(item.id)),
            group_of.get(str(item.id)),
        )
        for item in items
    ]


@router.post("/knowledge/{item_id}/confirm", response_model=KnowledgeResponse)
def confirm_knowledge(item_id: str, memory: Memory) -> KnowledgeResponse:
    """Confirm a candidate.

    Confirmation is a human act. No agent performs it, which is why this is an
    endpoint and not a step inside a run.

    **Transitional (ADR-0007).** This confirms an extracted row. It is not the
    attention queue; ``POST /v1/projects/{project_id}/attention`` is.
    """

    return KnowledgeResponse.of(memory.confirm_knowledge(KnowledgeItemId(item_id)))


@router.post("/projects/{project_id}/knowledge/confirm", response_model=list[KnowledgeResponse])
def confirm_knowledge_set(
    project_id: str, body: ConfirmKnowledgeSetRequest, memory: Memory
) -> list[KnowledgeResponse]:
    """Confirm a named set of candidates as one act.

    **The reading is what a person agrees to, not the rows underneath it.** A
    conversation synthesises nine statements into one sentence and asks whether
    it holds; the answer is one yes. Confirming per item made a caller decompose
    that yes itself, and none did — an interviewer wrote "Confirmed" while the
    panel two across read "0 of 1 confirmed".

    The set is the turn's provenance: the items the synthesis was drawn from.
    Sending it back is what binds agreement to what was actually shown.

    All or nothing, and one revision bump. A partially applied confirmation
    would leave someone believing they agreed to a reading while part of it
    stayed proposed, and no surface distinguishes that from having agreed.

    On the adapter deliberately. Four capabilities in this codebase were built
    complete and reachable from nothing, and the reason readiness reported 0%
    was a fifth. A service method with passing tests looks healthy from below.
    """

    _require_project(memory, project_id)
    try:
        confirmed = memory.confirm_knowledge_set(
            ProjectId(project_id), [KnowledgeItemId(i) for i in body.item_ids]
        )
    except LookupError as error:
        raise ApiError(status.HTTP_404_NOT_FOUND, "not_found", str(error)) from error
    return [KnowledgeResponse.of(item) for item in confirmed]


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
