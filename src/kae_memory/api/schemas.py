"""Transport shapes.

Separate from the domain dataclasses on purpose. Transport shape and domain shape
change for different reasons — a field can be renamed for a client without
touching an invariant, and an invariant can tighten without breaking a client —
so the duplication buys independence rather than costing it (ADR-0014).

Clients must ignore unknown fields: adding one is not a breaking change within
``/v1``.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from kae_memory.application.blueprint_service import Blueprint, BlueprintStatement, KnowledgeTrace
from kae_memory.application.review_service import Finding
from kae_memory.domain.execution import AgentRun
from kae_memory.domain.models import KnowledgeItem, Project
from kae_memory.domain.readiness import AreaResult, Blocker, ReadinessSnapshot
from kae_memory.domain.workspace import Message, Session


class HealthResponse(BaseModel):
    """FR-017. Reports without authentication and without leaking credentials."""

    status: str
    database: str
    migration_revision: str | None
    version: str


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1)
    key: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    key: str | None
    description: str | None
    status: str

    @classmethod
    def of(cls, project: Project) -> "ProjectResponse":
        return cls(
            id=str(project.id),
            name=project.name,
            key=project.key,
            description=project.description,
            status=project.status.value,
        )


class OpenSessionRequest(BaseModel):
    session_type: str


class SessionResponse(BaseModel):
    id: str
    project_id: str
    type: str
    status: str
    started_at: datetime
    ended_at: datetime | None

    @classmethod
    def of(cls, session: Session) -> "SessionResponse":
        return cls(
            id=str(session.id),
            project_id=str(session.project_id),
            type=session.type.value,
            status=session.status.value,
            started_at=session.started_at,
            ended_at=session.ended_at,
        )


class RecordMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    actor_type: str = "user"
    message_type: str = "input"
    actor_id: str | None = None
    #: Supply to make a retry safe. The same key with the same payload returns
    #: the original record; the same key with different content is a conflict.
    idempotency_key: str | None = Field(default=None, max_length=200)


class MessageResponse(BaseModel):
    id: str
    session_id: str
    sequence_number: int
    actor_type: str
    message_type: str
    content: str
    created_at: datetime

    @classmethod
    def of(cls, message: Message) -> "MessageResponse":
        return cls(
            id=str(message.id),
            session_id=str(message.session_id),
            sequence_number=message.sequence_number,
            actor_type=message.actor_type.value,
            message_type=message.message_type.value,
            content=message.content,
            created_at=message.created_at,
        )


class KnowledgeVersionResponse(BaseModel):
    number: int
    content: str
    source: str
    recorded_at: datetime


class KnowledgeResponse(BaseModel):
    """Carries every version, because history is the product.

    A knowledge item that only exposes its current text would make the audit
    trail invisible to the interface that exists to show it.
    """

    id: str
    project_id: str
    kind: str
    lifecycle: str
    current_content: str
    versions: list[KnowledgeVersionResponse]

    @classmethod
    def of(cls, item: KnowledgeItem) -> "KnowledgeResponse":
        return cls(
            id=str(item.id),
            project_id=str(item.project_id),
            kind=item.kind,
            lifecycle=item.lifecycle.value,
            current_content=item.current_version.content,
            versions=[
                KnowledgeVersionResponse(
                    number=version.number,
                    content=version.content,
                    source=version.provenance.source,
                    recorded_at=version.provenance.recorded_at,
                )
                for version in item.versions
            ],
        )


class EnqueueRunRequest(BaseModel):
    """``idempotency_key`` is required, not optional.

    ``MemoryService`` deduplicates on it, so a client that retries a request it
    never saw the answer to converges on one run instead of two. Making it
    optional would leave the one durable replay protection this API has to a
    caller's discretion.
    """

    role: str
    idempotency_key: str = Field(min_length=1)
    input_context: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None


class RunResponse(BaseModel):
    id: str
    project_id: str
    role: str
    status: str
    attempt_number: int
    idempotency_key: str
    continuation_state: dict[str, Any]
    output_summary: dict[str, Any]
    error_code: str | None
    error_message: str | None

    @classmethod
    def of(cls, run: AgentRun) -> "RunResponse":
        return cls(
            id=str(run.id),
            project_id=str(run.project_id),
            role=run.role.value,
            status=run.status.value,
            attempt_number=run.attempt_number,
            idempotency_key=run.idempotency_key,
            continuation_state=dict(run.continuation_state or {}),
            output_summary=dict(run.output_summary or {}),
            error_code=run.error_code,
            error_message=run.error_message,
        )


class AreaResultResponse(BaseModel):
    key: str
    name: str
    weight: float
    mandatory: bool
    state: str
    confirmed_count: int
    proposed_count: int
    minimum_confirmed: int
    contradicted: bool

    @classmethod
    def of(cls, area: AreaResult) -> "AreaResultResponse":
        return cls(
            key=area.key,
            name=area.name,
            weight=area.weight,
            mandatory=area.mandatory,
            state=area.state.value,
            confirmed_count=area.confirmed_count,
            proposed_count=area.proposed_count,
            minimum_confirmed=area.minimum_confirmed,
            contradicted=area.contradicted,
        )


class ReadinessResponse(BaseModel):
    """Everything needed to interrogate the number, never the number alone.

    ``is_stale`` is computed against the project's current revision at read time,
    which is why it is not a stored status.
    """

    id: str
    project_id: str
    percentage: int
    score: float
    status: str
    draft_eligible: bool
    implementation_eligible: bool
    missing_mandatory_areas: list[str]
    open_blocker_count: int
    critical_blocker_count: int
    unresolved_contradiction_count: int
    knowledge_revision: int
    template_key: str
    template_version: int
    calculation_version: int
    is_stale: bool
    areas: list[AreaResultResponse]
    calculated_at: datetime

    @classmethod
    def of(cls, snapshot: ReadinessSnapshot, current_revision: int) -> "ReadinessResponse":
        return cls(
            id=str(snapshot.id),
            project_id=str(snapshot.project_id),
            percentage=snapshot.percentage,
            score=snapshot.score,
            status=snapshot.status.value,
            draft_eligible=snapshot.draft_eligible,
            implementation_eligible=snapshot.implementation_eligible,
            missing_mandatory_areas=list(snapshot.missing_mandatory_areas),
            open_blocker_count=snapshot.open_blocker_count,
            critical_blocker_count=snapshot.critical_blocker_count,
            unresolved_contradiction_count=snapshot.unresolved_contradiction_count,
            knowledge_revision=snapshot.knowledge_revision,
            template_key=snapshot.template_key,
            template_version=snapshot.template_version,
            calculation_version=snapshot.calculation_version,
            is_stale=snapshot.is_stale_against(current_revision),
            areas=[AreaResultResponse.of(area) for area in snapshot.areas],
            calculated_at=snapshot.calculated_at,
        )


class CalculateReadinessRequest(BaseModel):
    not_applicable_areas: list[str] = Field(default_factory=list)


class AssignAreaRequest(BaseModel):
    knowledge_item_id: str
    area_key: str


class RaiseBlockerRequest(BaseModel):
    summary: str = Field(min_length=1)
    severity: str = "critical"
    area_key: str | None = None
    owner: str | None = None


class ResolveRequest(BaseModel):
    note: str | None = None


class BlockerResponse(BaseModel):
    id: str
    project_id: str
    summary: str
    severity: str
    status: str
    area_key: str | None
    owner: str | None
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None

    @classmethod
    def of(cls, blocker: Blocker) -> "BlockerResponse":
        return cls(
            id=str(blocker.id),
            project_id=str(blocker.project_id),
            summary=blocker.summary,
            severity=blocker.severity.value,
            status=blocker.status.value,
            area_key=blocker.area_key,
            owner=blocker.owner,
            resolution_note=blocker.resolution_note,
            created_at=blocker.created_at,
            resolved_at=blocker.resolved_at,
        )


class RecordContradictionRequest(BaseModel):
    source_knowledge_item_id: str
    target_knowledge_item_id: str


class ContradictionResponse(BaseModel):
    id: str
    project_id: str
    source_knowledge_item_id: str
    target_knowledge_item_id: str


class ResolvedResponse(BaseModel):
    """Whether the call changed anything.

    ``False`` means it was already resolved, which is not an error — a retried
    resolution should be safe.
    """

    resolved: bool


class FindingResponse(BaseModel):
    """One quality finding.

    No identifier, deliberately: findings are derived from state, not stored, so
    there is nothing stable to address. A finding disappears when the condition
    that produced it does (ADR-0015).
    """

    kind: str
    severity: str
    summary: str
    recommended_action: str
    area_key: str | None
    knowledge_item_ids: list[str]

    @classmethod
    def of(cls, finding: Finding) -> "FindingResponse":
        return cls(
            kind=finding.kind.value,
            severity=finding.severity.value,
            summary=finding.summary,
            recommended_action=finding.recommended_action,
            area_key=finding.area_key,
            knowledge_item_ids=[str(item) for item in finding.knowledge_item_ids],
        )


class ReviewResponse(BaseModel):
    """What a reviewer needs without inspecting the database (FR-015)."""

    project_id: str
    counts: dict[str, int]
    findings: list[FindingResponse]


class StatementResponse(BaseModel):
    """One blueprint statement.

    Carries its knowledge item, so tracing it is one hop rather than a parallel
    trace API over derived identifiers (ADR-0016). No statement lacks a label or
    a trace target — FR-008's acceptance condition, and it holds structurally.
    """

    id: str
    text: str
    label: str
    kind: str
    knowledge_item_id: str
    knowledge_version: int
    source_message_id: str | None
    produced_by_run_id: str | None

    @classmethod
    def of(cls, statement: BlueprintStatement) -> "StatementResponse":
        return cls(
            id=statement.id,
            text=statement.text,
            label=statement.label.value,
            kind=statement.kind,
            knowledge_item_id=str(statement.knowledge_item_id),
            knowledge_version=statement.knowledge_version,
            source_message_id=(
                None if statement.source_message_id is None else str(statement.source_message_id)
            ),
            produced_by_run_id=(
                None if statement.produced_by_run_id is None else str(statement.produced_by_run_id)
            ),
        )


class SectionResponse(BaseModel):
    area_key: str
    area_name: str
    statements: list[StatementResponse]


class BlueprintResponse(BaseModel):
    """A blueprint, with its own limits attached rather than implied."""

    project_id: str
    project_name: str
    complete: bool
    draft_eligible: bool
    implementation_eligible: bool
    readiness_percentage: int
    statement_count: int
    missing_mandatory_areas: list[str]
    open_questions: list[str]
    unassigned_confirmed_count: int
    sections: list[SectionResponse]

    @classmethod
    def of(cls, blueprint: Blueprint) -> "BlueprintResponse":
        return cls(
            project_id=str(blueprint.project_id),
            project_name=blueprint.project_name,
            complete=blueprint.complete,
            draft_eligible=blueprint.draft_eligible,
            implementation_eligible=blueprint.implementation_eligible,
            readiness_percentage=blueprint.readiness_percentage,
            statement_count=blueprint.statement_count,
            missing_mandatory_areas=list(blueprint.missing_mandatory_areas),
            open_questions=list(blueprint.open_questions),
            unassigned_confirmed_count=blueprint.unassigned_confirmed_count,
            sections=[
                SectionResponse(
                    area_key=section.area_key,
                    area_name=section.area_name,
                    statements=[StatementResponse.of(s) for s in section.statements],
                )
                for section in blueprint.sections
            ],
        )


class TraceStepResponse(BaseModel):
    relation: str
    reference: str
    detail: str | None


class TraceResponse(BaseModel):
    """A knowledge item's chain of custody: project, session, message, run, versions."""

    knowledge_item_id: str
    project_id: str
    kind: str
    lifecycle: str
    current_content: str
    produced_by_run_id: str | None
    used_by_run_ids: list[str]
    source_message_ids: list[str]
    session_ids: list[str]
    steps: list[TraceStepResponse]

    @classmethod
    def of(cls, trace: KnowledgeTrace) -> "TraceResponse":
        return cls(
            knowledge_item_id=str(trace.knowledge_item_id),
            project_id=str(trace.project_id),
            kind=trace.kind,
            lifecycle=trace.lifecycle,
            current_content=trace.current_content,
            produced_by_run_id=(
                None if trace.produced_by_run_id is None else str(trace.produced_by_run_id)
            ),
            used_by_run_ids=[str(run) for run in trace.used_by_run_ids],
            source_message_ids=[str(message) for message in trace.source_message_ids],
            session_ids=[str(session) for session in trace.session_ids],
            steps=[
                TraceStepResponse(relation=s.relation, reference=s.reference, detail=s.detail)
                for s in trace.steps
            ],
        )
