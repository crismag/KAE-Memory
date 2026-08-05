"""Transport shapes.

Separate from the domain dataclasses on purpose. Transport shape and domain shape
change for different reasons — a field can be renamed for a client without
touching an invariant, and an invariant can tighten without breaking a client —
so the duplication buys independence rather than costing it (ADR-0014).

Clients must ignore unknown fields: adding one is not a breaking change within
``/v1``.
"""

from collections.abc import Sequence
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


# -- pipeline (N3) ---------------------------------------------------------


class SearchResultResponse(BaseModel):
    """One retrieval hit, with what justifies it.

    `lifecycle` is present on every hit because searchable and authoritative
    are different questions. A caller that treats a proposed statement as
    established fact is the failure this field exists to prevent, and dropping
    it to shorten the response would remove the only thing preventing it.
    """

    knowledge_id: str
    kind: str
    text: str
    label: str
    lifecycle: str
    authoritative: bool
    why: str
    distance: float | None = None
    matched_terms: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, hit: Any) -> "SearchResultResponse":
        return cls(
            knowledge_id=str(hit.knowledge_id),
            kind=hit.kind.value,
            text=hit.text,
            label="confirmed" if hit.authoritative else "proposed",
            lifecycle=hit.lifecycle.value,
            authoritative=hit.authoritative,
            why=hit.why,
            distance=hit.distance,
            matched_terms=list(hit.matched_terms),
        )


class SearchResponse(BaseModel):
    """Search results, and an honest account of how they were found.

    `semantic_search_available` is false whenever no semantic embedding model
    is configured. A caller who believes a conceptual query was understood
    reads an empty result as "the project does not know this"; the truth may be
    "the words did not match", and only this field separates them.
    """

    results: list[SearchResultResponse]
    matched_chunks: int
    matched_knowledge_items: int
    search_mode: str
    semantic_search_available: bool
    indexing: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, hits: Sequence[Any], mode: str, indexing: Any) -> "SearchResponse":
        semantic = mode == "semantic"
        warnings: list[str] = []
        if not semantic:
            warnings.append(
                "Matched on query terms rather than meaning. Conceptual queries "
                "that share no wording with the stored text will not be found."
            )
        if not indexing.lexically_searchable:
            warnings.append("No knowledge is searchable yet. This is not the same as no match.")
        return cls(
            results=[SearchResultResponse.of(hit) for hit in hits],
            # Split deliberately (ADR-0021 rule 5): one number could not say
            # whether three hits came from three statements or three spans of one.
            matched_chunks=len(hits),
            matched_knowledge_items=len({str(hit.knowledge_id) for hit in hits}),
            search_mode=mode,
            semantic_search_available=semantic,
            indexing={
                "knowledge_items": indexing.knowledge_items,
                "chunks": indexing.chunks,
                "embedded_chunks": indexing.embedded_chunks,
            },
            warnings=warnings,
        )


class IngestDocumentRequest(BaseModel):
    document: str = Field(min_length=1)
    text: str = Field(min_length=1)
    max_chunks: int | None = Field(default=None, ge=1)
    actor_id: str | None = None


class IngestionResponse(BaseModel):
    """What an ingestion recorded, and what it did not.

    Three facts stay separate and only one of them is yes: text recorded,
    extraction queued, knowledge unchanged. A caller reading "recorded" as
    "known" would plan against statements no run has produced and no person has
    confirmed.
    """

    document: str
    session_id: str
    evidence_recorded: bool
    knowledge_changed: bool
    workflow_state: str
    chunks_recorded: int
    extraction_runs_queued: list[str]
    complete: bool
    truncated_chunks: int
    idempotent_replay: bool
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, result: Any) -> "IngestionResponse":
        return cls(
            document=result.document,
            session_id=str(result.session_id),
            evidence_recorded=True,
            knowledge_changed=False,
            workflow_state="extraction_queued",
            chunks_recorded=len(result.chunks),
            extraction_runs_queued=[str(chunk.run_id) for chunk in result.chunks],
            complete=result.complete,
            truncated_chunks=result.truncated_chunks,
            idempotent_replay=result.replayed,
            warnings=list(result.warnings),
        )


class RejectKnowledgeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reviewer: str = Field(min_length=1)
    reason_code: str = "other"
    note: str | None = None
    idempotency_key: str | None = None


class CorrectKnowledgeRequest(BaseModel):
    expected_version: int = Field(ge=1)
    content: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    note: str | None = None
    idempotency_key: str | None = None


class KnowledgeReviewResponse(BaseModel):
    """The outcome of a reviewed lifecycle decision.

    `replayed` separates "your decision was applied" from "your decision
    already held". Both succeed and both return the same state, but a caller
    retrying after a timeout needs to know which happened before it tells a
    person they confirmed something.
    """

    knowledge_id: str
    lifecycle: str
    version: int
    replayed: bool

    @classmethod
    def of(cls, outcome: Any) -> "KnowledgeReviewResponse":
        item = outcome.item
        return cls(
            knowledge_id=str(item.id),
            lifecycle=item.lifecycle.value,
            version=item.current_version.number,
            replayed=outcome.replayed,
        )


class ClarificationResponse(BaseModel):
    """An answer recorded, and the run scheduled to read it.

    `knowledge_changed` is false and stays false until a run reads the answer
    and a person confirms what it proposed. "Answered" must never read as "the
    project now knows this".
    """

    question_id: str
    answer_id: str
    run_id: str
    knowledge_changed: bool
    knowledge_state: str
    replayed: bool

    @classmethod
    def of(cls, answered: Any) -> "ClarificationResponse":
        return cls(
            question_id=str(answered.question.id),
            answer_id=str(answered.answer.id),
            run_id=str(answered.run_id),
            knowledge_changed=False,
            knowledge_state="unchanged_until_extraction_and_confirmation",
            replayed=answered.replayed,
        )


class ClarificationQuestionResponse(BaseModel):
    clarification_id: str
    question: str
    finding_kind: str
    severity: str
    area_key: str | None = None


class ClarificationListResponse(BaseModel):
    """Open questions, and what a limit left out.

    `omitted` is distinct from a detail level's truncation: a caller needs to
    tell "work you have not seen" from "detail we compacted away".
    """

    questions: list[ClarificationQuestionResponse]
    total: int
    omitted: int
    note: str

    @classmethod
    def of(cls, questions: Sequence[Any], limit: int) -> "ClarificationListResponse":
        shown = list(questions)[:limit]
        return cls(
            questions=[
                ClarificationQuestionResponse(
                    clarification_id=str(question.id),
                    question=question.question,
                    finding_kind=question.finding_kind,
                    severity=question.severity,
                    area_key=question.area_key,
                )
                for question in shown
            ],
            total=len(questions),
            omitted=max(0, len(questions) - len(shown)),
            note=(
                "These are unresolved. Do not choose an answer on the project's "
                "behalf; if one blocks the work, report it and stop."
            ),
        )


class AssemblyResponse(BaseModel):
    """A bounded context, pinned to the revision it read.

    `package_id` is fresh per call and is **not** deliverable identity. A
    durable deliverable is a concept this repository does not have, and a
    response that implied otherwise would invite a client to store an id that
    resolves to nothing.
    """

    manifest: dict[str, Any]
    sections: list[dict[str, Any]]
    package: dict[str, Any]
    knowledge_revision: int
    guidance: list[str]

    @classmethod
    def of(cls, assembled: Any, package: dict[str, Any], revision: int) -> "AssemblyResponse":
        manifest = assembled.manifest
        return cls(
            manifest={
                "package_id": manifest.package_id,
                "project_id": manifest.project_id,
                "scope": manifest.scope,
                "purpose": manifest.purpose,
                "knowledge_revision": manifest.knowledge_revision,
                "content_hash": manifest.content_hash,
                "statement_count": manifest.statement_count,
                "traced_statements": manifest.traced_statements,
                "confirmation_state": {
                    "confirmed": manifest.confirmation_state.confirmed,
                    "proposed": manifest.confirmation_state.proposed,
                    "contested": manifest.confirmation_state.contested,
                },
                "unresolved_critical_gaps": [
                    {"area_key": gap.area_key, "summary": gap.summary}
                    for gap in manifest.unresolved_critical_gaps
                ],
                "warnings": list(manifest.warnings),
            },
            sections=[
                {
                    "area": section.area_key,
                    "name": section.name,
                    "statements": [
                        {
                            "knowledge_id": statement.knowledge_id,
                            "kind": statement.kind,
                            "text": statement.text,
                            "label": statement.label,
                            "lifecycle": statement.lifecycle,
                            "version": statement.version,
                        }
                        for statement in section.statements
                    ],
                }
                for section in assembled.sections
            ],
            package=package,
            knowledge_revision=revision,
            guidance=[
                "Statements labelled proposed are candidates, not decisions.",
                "Unresolved questions travel with this package. Do not choose an "
                "answer on the project's behalf.",
            ],
        )


class AnswerClarificationRequest(BaseModel):
    answer: str = Field(min_length=1)
    actor_id: str | None = None
    idempotency_key: str | None = None


class OperationalRecordResponse(BaseModel):
    """One operational fact, as reported.

    `authority` and `verification` are the fields that keep a sentence from
    completing a milestone. A response that dropped them would make "someone
    said the tests passed" indistinguishable from "the tests passed".
    """

    operational_update_id: str
    kind: str
    subject: str | None
    reported_status: str | None
    current_status: str | None
    transition_type: str | None
    authority: str
    state: str
    verification: str | None
    effective_date: str | None
    date_role: str | None
    settlements: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def of(cls, record: Any) -> "OperationalRecordResponse":
        return cls(
            operational_update_id=record.operational_update_id,
            kind=record.kind,
            subject=record.subject,
            reported_status=record.reported_status,
            current_status=record.current_status,
            transition_type=record.transition_type,
            authority=record.authority,
            state=record.state,
            verification=record.verification,
            effective_date=record.effective_date,
            date_role=record.date_role,
            settlements=list(record.detail.get("settlements", [])),
        )


class OperationalStateResponse(BaseModel):
    records: list[OperationalRecordResponse]
    total: int
    omitted: int
    states: list[str]
    note: str

    @classmethod
    def of(
        cls, records: Sequence[Any], limit: int, states: Sequence[str] | None
    ) -> "OperationalStateResponse":
        shown = list(records)[:limit]
        return cls(
            records=[OperationalRecordResponse.of(record) for record in shown],
            total=len(records),
            omitted=max(0, len(records) - len(shown)),
            states=list(states) if states else ["proposed", "active"],
            note=(
                "Reported, not verified. A milestone is never completed because a "
                "sentence said so; a proposed record is a claim nobody has accepted."
            ),
        )


class ClassificationListResponse(BaseModel):
    """Classified spans.

    `semantic_classification` is false for the rule-based classifier. Wording it
    does not recognise is invisible to it, and a caller told otherwise would
    read an unclassified span as "there was nothing there".
    """

    classifications: list[dict[str, Any]]
    total: int
    omitted: int
    classifier: str
    classifier_version: str
    semantic_classification: bool
    knowledge_changed: bool
    note: str

    @classmethod
    def of(
        cls,
        rows: Sequence[Any],
        limit: int,
        semantic: bool,
        classifier: str,
        version: str,
    ) -> "ClassificationListResponse":
        shown = [dict(row) for row in list(rows)[:limit]]
        return cls(
            classifications=shown,
            total=len(rows),
            omitted=max(0, len(rows) - len(shown)),
            classifier=classifier,
            classifier_version=version,
            semantic_classification=semantic,
            knowledge_changed=False,
            note=(
                "Classification says what a span was, not whether it is true. "
                "Nothing listed here is confirmed knowledge."
            ),
        )


class SettleOperationalRequest(BaseModel):
    state: str
    actor: str = Field(min_length=1)
    note: str | None = None


# -- deliverables (N20) ----------------------------------------------------


class RecordDeliverableRequest(BaseModel):
    purpose: str = "implementation"
    include_proposed: bool = False
    recorded_by: str | None = None


class SupersedeDeliverableRequest(BaseModel):
    replacement_id: str = Field(min_length=1)


class WithdrawDeliverableRequest(BaseModel):
    reason: str = Field(min_length=1)


class DeliverableResponse(BaseModel):
    """A durable record of an assembled output.

    `rendered` and `published` are present and always false. Their absence
    would let a caller assume either happened; N20 records that an output
    existed and deliberately performs no storage or publication side effect.
    """

    deliverable_id: str
    purpose: str
    scope: str
    module: str | None
    state: str
    knowledge_revision: int
    content_hash: str
    stale: bool
    artifacts: list[dict[str, Any]]
    source_knowledge: list[str]
    manifest: dict[str, Any]
    recorded_by: str | None
    superseded_by: str | None
    rendered: bool = False
    published: bool = False
    recorded: bool | None = None

    @classmethod
    def of(
        cls, deliverable: Any, current_revision: int, created: bool | None = None
    ) -> "DeliverableResponse":
        return cls(
            deliverable_id=str(deliverable.id),
            purpose=deliverable.purpose,
            scope=deliverable.scope,
            module=deliverable.module_key,
            state=deliverable.state.value,
            knowledge_revision=deliverable.knowledge_revision,
            content_hash=deliverable.content_hash,
            # Derived, never stored. A stored flag is true until something
            # remembers to update it.
            stale=deliverable.is_stale_against(current_revision),
            artifacts=[
                {
                    "path": artifact.path,
                    "area": artifact.area_key,
                    "title": artifact.title,
                    "statements": artifact.statement_count,
                    "confirmed": artifact.confirmed_count,
                    "content_hash": artifact.content_hash,
                }
                for artifact in deliverable.artifacts
            ],
            source_knowledge=list(deliverable.source_knowledge),
            manifest=dict(deliverable.manifest),
            recorded_by=deliverable.recorded_by,
            superseded_by=deliverable.superseded_by,
            recorded=created,
        )


class DeliverableListResponse(BaseModel):
    deliverables: list[DeliverableResponse]
    total: int
    omitted: int
    knowledge_revision: int
    note: str

    @classmethod
    def of(
        cls, records: Sequence[Any], current_revision: int, limit: int
    ) -> "DeliverableListResponse":
        shown = list(records)[:limit]
        return cls(
            deliverables=[DeliverableResponse.of(r, current_revision) for r in shown],
            total=len(records),
            omitted=max(0, len(records) - len(shown)),
            knowledge_revision=current_revision,
            note=(
                "A stale deliverable is one recorded before the project moved. It "
                "is still what was produced; it is no longer what the project now says."
            ),
        )
