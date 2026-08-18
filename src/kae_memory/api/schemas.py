"""Transport shapes.

Separate from the domain dataclasses on purpose. Transport shape and domain shape
change for different reasons — a field can be renamed for a client without
touching an invariant, and an invariant can tighten without breaking a client —
so the duplication buys independence rather than costing it (ADR-0014).

Clients must ignore unknown fields: adding one is not a breaking change within
``/v1``.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from kae_memory.application.blueprint_service import Blueprint, BlueprintStatement, KnowledgeTrace
from kae_memory.application.clarification_service import REASON_UNSTATED
from kae_memory.application.readiness_service import ClassificationReport, ExtractionCoverage
from kae_memory.application.review_service import Finding
from kae_memory.domain.dispositions import Disposition, settles
from kae_memory.domain.execution import AgentRun
from kae_memory.domain.models import KnowledgeItem, KnowledgeSourceType, Project
from kae_memory.domain.readiness import (
    SOFTWARE_TEMPLATE,
    AreaResult,
    Blocker,
    ReadinessSnapshot,
)
from kae_memory.domain.workspace import Message, Session
from kae_memory.messages import message


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
    """One project, and how far its knowledge has moved.

    ``knowledge_revision`` is here so a consumer holding two responses can tell
    whether the project changed between them. Without it a client comparing
    screens can only compare counts, and equal counts do not mean equal state.
    """

    id: str
    name: str
    key: str | None
    description: str | None
    status: str
    knowledge_revision: int

    @classmethod
    def of(cls, project: Project) -> "ProjectResponse":
        return cls(
            id=str(project.id),
            name=project.name,
            key=project.key,
            description=project.description,
            status=project.status.value,
            knowledge_revision=project.knowledge_revision,
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
    #: What this message is for (EM-2). `project_input` is interpreted and is
    #: the default; `diagnostic` and `conversation_control` are stored, marked,
    #: and never extracted from. Health checks and round-trip proofs should say
    #: `diagnostic` — otherwise their text becomes candidate project knowledge,
    #: which is how twelve copies of one test sentence entered a real project.
    purpose: str = "project_input"
    #: Structure *about* the message, not more message.
    #:
    #: `Message.metadata` has always existed and been persisted; this surface
    #: simply dropped it, so anything a caller knew about a turn — which
    #: statements it reflected, what it recommended doing next — had nowhere to
    #: live and was recomputed or lost on the next page load.
    #:
    #: Never extracted from. Metadata is the caller's own record, and treating
    #: it as evidence would let a client write knowledge without saying so.
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    id: str
    session_id: str
    sequence_number: int
    actor_type: str
    message_type: str
    content: str
    created_at: datetime
    #: Returned as well as accepted. Storing structure a caller can never read
    #: back is a write-only field, and the caller then keeps its own copy —
    #: which is the state this was added to end.
    metadata: dict[str, Any] = Field(default_factory=dict)

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
            metadata=dict(message.metadata),
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
    #: The discovery areas this statement was classified into.
    #:
    #: Memory has always held these; the listing simply did not return them. So
    #: a consumer could see *what* a project knows and not *what any of it is
    #: about* — which left Studio unable to show a problem statement at all,
    #: because "the problem" is the statements linked to `problem_and_value` and
    #: nothing else identifies them.
    #:
    #: Empty until review runs. That is the honest state, not a missing field:
    #: an unclassified statement belongs to no area yet.
    areas: list[str] = Field(default_factory=list)
    #: Which claim inside an area this statement establishes, where the area asks
    #: for more than one thing — `problem_statement` or `value_proposition`
    #: inside `problem_and_value`.
    #:
    #: Without this a consumer can see that a statement is about the problem and
    #: value of a project and cannot tell which, which is why Studio reported
    #: `value` as uncomputable for every project in existence (`RUN-D14`).
    #:
    #: Absent for a statement whose link names no claim, which is a fact about
    #: the assignment rather than a missing field.
    claims: dict[str, str] = Field(default_factory=dict)
    #: Which set of adjacent statements this one belongs to, if any.
    #:
    #: `PPA-15`: seventy flat statements is *"'I don't know how to organise my
    #: project' becomes 'KAE generated 70 things I don't know how to organise'"*.
    #: Statements sharing a group say adjacent things and are worth reading
    #: together.
    #:
    #: **A group is not a merge.** Every member is returned whole and stays
    #: separately confirmable; the grouping is computed per read and stored
    #: nowhere, so `EM-3`'s ruling on unattended merging is untouched.
    #:
    #: `None` means this statement resembles nothing else — which is a fact
    #: about it, not a missing field. It is also `None` for every statement on a
    #: project too large to group, and a consumer must not read that as
    #: "nothing here resembles anything".
    related_group: int | None = None
    versions: list[KnowledgeVersionResponse]

    @classmethod
    def of(
        cls,
        item: KnowledgeItem,
        areas: Sequence[str] = (),
        claims: Mapping[str, str] | None = None,
        related_group: int | None = None,
    ) -> "KnowledgeResponse":
        return cls(
            id=str(item.id),
            project_id=str(item.project_id),
            kind=item.kind,
            lifecycle=item.lifecycle.value,
            current_content=item.current_version.content,
            areas=list(areas),
            claims=dict(claims or {}),
            related_group=related_group,
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


class ExtractionCoverageResponse(BaseModel):
    """How much of what was submitted became knowledge.

    Beside a readiness percentage, never inside it. The two answer different
    questions — *how much of this project is understood* and *how much of it was
    read* — and folding the second into the first produces a number that is
    confident about content nobody extracted.
    """

    succeeded: int
    abandoned: int
    #: Chunks dropped at ingest, before any run existed. Separate from
    #: `abandoned` because they are a different failure: extraction did not
    #: fail on this content, it never saw it (AUD-024).
    not_ingested: int
    total: int
    complete: bool

    @classmethod
    def of(cls, coverage: "ExtractionCoverage") -> "ExtractionCoverageResponse":
        return cls(
            succeeded=coverage.succeeded,
            abandoned=coverage.abandoned,
            not_ingested=coverage.not_ingested,
            total=coverage.total,
            complete=coverage.is_complete,
        )


class ConfirmKnowledgeSetRequest(BaseModel):
    """The items a person's single "yes" applies to.

    Non-empty by constraint. An empty set is not a smaller confirmation; it is a
    caller that lost track of what it was asking about, and answering 200 with
    an empty list would let it carry on believing something was confirmed.

    Bounded because a confirmation set describes one synthesis. A request naming
    five hundred items is a caller confirming a whole project by accident, which
    is exactly the "silently becomes user-confirmed" failure the directive
    forbids.
    """

    item_ids: list[str] = Field(min_length=1, max_length=200)


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
    #: When it ran. A client watching a run could see that it failed and not
    #: when, or that it succeeded and not how long it took — so "is this stuck?"
    #: had no answer but the absence of a change.
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    #: The session the run belongs to, where it has one. Extraction runs are
    #: created from a message in a conversation, and the link back was modelled
    #: and never returned.
    session_id: str | None = None

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
            started_at=run.started_at,
            completed_at=run.completed_at,
            failed_at=run.failed_at,
            session_id=str(run.session_id) if run.session_id else None,
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


class ClassificationResponse(BaseModel):
    """How a project's knowledge reached its discovery areas.

    States a reader must be able to tell apart, and could not:

    - **never reviewed** — `engine` is null, and the percentage reflects
      whatever links exist rather than any classification;
    - **classified by a model** — the intended path;
    - **classified by a fixture** — a reviewer is configured and it replays
      recorded payloads. This reported `reviewed_by_model` until `AUD-039`,
      because a fixture satisfies `ReviewPort` like anything else;
    - **no engine configured** — the offline unambiguous-only rule, chosen;
    - **degraded** — a provider failed and that same rule ran instead.

    The last three cap readiness at 16% of the software template and make
    `implementation_eligible` unreachable whatever the corpus, while still
    returning a run status of `succeeded` and a number. `degraded` is what says
    so, and it is true for all three: what a reader needs is whether the
    percentage came from judgement, not how it came not to.
    """

    engine: str | None
    degraded: bool
    reviewed_at: datetime | None
    note: str

    @classmethod
    def of(cls, report: ClassificationReport) -> "ClassificationResponse":
        # Two different offline behaviours, so two different sentences. The
        # fixture reviewer still assigns only the kinds exactly one area
        # accepts; the offline rule reads the statement (`EPI-3b`). Saying
        # "only unambiguous kinds" about both was true until it was not.
        not_about_the_project = (
            "This percentage may differ from what a model would have reached, "
            "for a reason that is not about the project."
        )
        offline_rule = (
            "It places a statement from its own wording, and where the wording "
            f"decides nothing it uses the default area for that kind. {not_about_the_project}"
        )
        if report.engine is None:
            note = "No review has run. Areas reflect whatever links already exist."
        elif report.by_fixture:
            note = (
                "Classified by the fixture reviewer, which replays recorded payloads "
                "rather than judging and assigns only kinds exactly one area accepts. "
                f"{not_about_the_project}"
            )
        elif report.engine and report.engine.startswith("offline_by"):
            note = f"No review engine is configured, so the offline rule ran. {offline_rule}"
        elif report.degraded:
            note = (
                "Classification fell back to the offline rule for some or all "
                f"statements. {offline_rule}"
            )
        else:
            note = "Classified by the configured review model."
        return cls(
            engine=report.engine,
            degraded=report.degraded,
            reviewed_at=report.reviewed_at,
            note=note,
        )


class ReadinessResponse(BaseModel):
    """Everything needed to interrogate the number, never the number alone.

    ``is_stale`` is computed against the project's current revision at read time,
    which is why it is not a stored status.

    **Two revisions, deliberately.** ``knowledge_revision`` is the revision this
    snapshot was *calculated at*; ``current_knowledge_revision`` is where the
    project is *now*. Reporting only the first is what let Studio display a
    revision that stopped moving whenever readiness was last recalculated — a
    number that looks live and is not. Reporting only the second would make
    ``is_stale`` unexplainable: a reader could see that readiness is stale
    without being able to say how far behind it is.
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
    current_knowledge_revision: int
    template_key: str
    template_version: int
    calculation_version: int
    is_stale: bool
    #: Whether a newer template version exists than this was computed under.
    #:
    #: A different staleness from `is_stale`, which asks whether the *project*
    #: moved. This asks whether the meaning of the number did. A pinned project
    #: is not stale in the first sense and is still being evaluated under
    #: semantics that are no longer current — and without this, that deliberate
    #: choice is invisible (`RUN-D14`).
    is_behind_template: bool
    #: The template version currently shipped, so a reader can see the gap
    #: rather than only that one exists.
    current_template_version: int
    areas: list[AreaResultResponse]
    calculated_at: datetime
    #: How the knowledge behind this number was classified, and whether that
    #: classification degraded. Reported beside the percentage and never folded
    #: into it: a number produced by the 16% offline ceiling was previously
    #: indistinguishable from one a model produced (AUD-025, AUD-026).
    classification: "ClassificationResponse"

    @classmethod
    def of(
        cls,
        snapshot: ReadinessSnapshot,
        current_revision: int,
        classification: ClassificationReport | None = None,
    ) -> "ReadinessResponse":
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
            current_knowledge_revision=current_revision,
            template_key=snapshot.template_key,
            template_version=snapshot.template_version,
            calculation_version=snapshot.calculation_version,
            is_stale=snapshot.is_stale_against(current_revision),
            is_behind_template=snapshot.is_behind_template(SOFTWARE_TEMPLATE.version),
            current_template_version=SOFTWARE_TEMPLATE.version,
            areas=[AreaResultResponse.of(area) for area in snapshot.areas],
            calculated_at=snapshot.calculated_at,
            classification=ClassificationResponse.of(
                classification or ClassificationReport(engine=None, reviewed_at=None)
            ),
        )


class DeletionPlanResponse(BaseModel):
    """What deleting a project would remove, before anything is removed.

    `rows` is per table rather than a total so a reviewer can sanity-check
    scale. A project reporting zero messages where hundreds were expected is
    how a wrong identifier is caught before it is acted on.
    """

    project_id: str
    name: str
    knowledge_revision: int
    rows: dict[str, int]
    total_rows: int


class EnqueueReviewRequest(BaseModel):
    """Ask for a review pass.

    `idempotency_key` is required, not optional. Review is a model call over
    every statement a project holds; a retried request without a key is a second
    bill and a second set of classifications for one intent.
    """

    idempotency_key: str = Field(min_length=1, max_length=200)


class EnqueueReviewResponse(BaseModel):
    """A queued review, and what it will and will not see.

    `outstanding_extraction_runs` is reported rather than hidden because it
    decides whether this pass is complete. Zero means review sees everything
    extracted. Anything else means it will classify what exists now and miss the
    rest, and the caller has to run it again.
    """

    run_id: str
    outstanding_extraction_runs: int
    warnings: list[str] = Field(default_factory=list)


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
    subject_key: str = ""
    """What this finding is about, where the area alone does not say.

    Not an identity for the finding — the docstring above still holds, and
    findings remain underivable from anything stable. This names the *subject*:
    a blocker's id, for instance, which is addressable in its own right.

    Returned because a client rendering two blockers in one area otherwise
    cannot tell them apart, which is the same confusion that made their
    questions collide.
    """

    @classmethod
    def of(cls, finding: Finding) -> "FindingResponse":
        return cls(
            kind=finding.kind.value,
            severity=finding.severity.value,
            subject_key=finding.subject_key,
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
    #: The engine named by the producing run — a model identifier, or
    #: `deterministic-fixture` when the offline adapter produced it. `None` when
    #: no run recorded one.
    #:
    #: Fixture-derived knowledge was previously indistinguishable from
    #: model-extracted knowledge everywhere it could be read (`AUD-008`), so a
    #: project could show hundreds of "requirements" that were sentences split
    #: on punctuation.
    produced_by: str | None
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
            produced_by=trace.produced_by,
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
    """A document to read, and what kind of source it is.

    ``source_type`` defaults to an imported document because that is what a bare
    paste is. A caller reading a connected repository must say so: ADR-0008
    makes what an area may reach depend on it, and nothing downstream can tell a
    file from a paste once the text has been chunked.

    ``source_id`` names the registered source the text was read out of, when
    there is one. Optional, because a paste arrives before any source has been
    registered for it, and **checked** wherever it is given: an identifier
    naming no source of this project is refused rather than stored (`D-164`).
    """

    document: str = Field(min_length=1)
    text: str = Field(min_length=1)
    max_chunks: int | None = Field(default=None, ge=1)
    actor_id: str | None = None
    source_type: KnowledgeSourceType = KnowledgeSourceType.IMPORTED_DOCUMENT
    source_id: str | None = None


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
    disposition: str
    question_settled: bool
    """False when the response did not decide the question. It stays open."""
    assumption_id: str | None = None

    @classmethod
    def of(cls, answered: Any) -> "ClarificationResponse":
        return cls(
            question_id=str(answered.question.id),
            answer_id=str(answered.answer.id),
            run_id=str(answered.run_id),
            knowledge_changed=False,
            knowledge_state="unchanged_until_extraction_and_confirmation",
            replayed=answered.replayed,
            disposition=answered.disposition.value,
            question_settled=settles(answered.disposition),
            assumption_id=answered.assumption_id,
        )


class ClarificationQuestionResponse(BaseModel):
    clarification_id: str
    question: str
    finding_kind: str
    severity: str
    area_key: str | None = None
    #: Why it is worth asking, as the finding said it. The grade shipped here
    #: alone until `D-246`, so a caller read `critical` and nothing saying what
    #: was critical. A finding that offered no sentence says that, rather than
    #: sending an empty one for a surface to render as a gap.
    reason: str = REASON_UNSTATED


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
                    reason=question.reason or REASON_UNSTATED,
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


class QuestionCandidateResponse(BaseModel):
    """A question the findings justify asking, before anybody asked it.

    Distinct from `ClarificationQuestionResponse` in the one way that matters:
    `candidate_key` always exists and `asked_id` may not. Listing candidates
    writes nothing, so a caller reading this has not caused a question to be
    put to anyone.
    """

    candidate_key: str
    question: str
    finding_kind: str
    severity: str
    area_key: str | None = None
    #: The question's id, once it has been asked. `null` means nobody has been
    #: shown it — answering requires asking first, which is a different call.
    asked_id: str | None = None
    asked_at: datetime | None = None
    disposition: str = "open"
    #: Why the findings justify asking it, as the finding said it (`D-246`).
    reason: str = REASON_UNSTATED


class QuestionCandidateListResponse(BaseModel):
    candidates: list[QuestionCandidateResponse]
    total: int
    omitted: int
    note: str

    @classmethod
    def of(cls, candidates: Sequence[Any], limit: int) -> "QuestionCandidateListResponse":
        shown = list(candidates)[:limit]
        return cls(
            candidates=[
                QuestionCandidateResponse(
                    candidate_key=candidate.candidate_key,
                    question=candidate.question,
                    finding_kind=candidate.finding_kind,
                    severity=candidate.severity,
                    area_key=candidate.area_key,
                    asked_id=str(candidate.asked_id) if candidate.asked_id else None,
                    asked_at=candidate.asked_at,
                    disposition=candidate.disposition.value,
                    reason=candidate.reason or REASON_UNSTATED,
                )
                for candidate in shown
            ],
            total=len(candidates),
            omitted=max(0, len(candidates) - len(shown)),
            note=(
                "Nothing here has been asked unless it carries an asked_id. "
                "Reading this list did not ask anybody anything."
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


class PreliminaryStatementResponse(BaseModel):
    """One statement in preliminary context, with both of its qualifiers.

    `label` says where authority comes from; `inclusion_class` says whether a
    person has ruled. These were one field once, which made "KAE inferred this"
    and "nobody has confirmed this" the same word.
    """

    knowledge_id: str
    kind: str
    text: str
    area_key: str
    version: int
    lifecycle: str
    label: str
    inclusion_class: str

    @classmethod
    def of(cls, statement: Any) -> "PreliminaryStatementResponse":
        return cls(
            knowledge_id=statement.knowledge_id,
            kind=statement.kind,
            text=statement.text,
            area_key=statement.area_key,
            version=statement.version,
            lifecycle=statement.lifecycle,
            label=statement.label,
            inclusion_class=statement.inclusion_class,
        )


class StatedEntryResponse(BaseModel):
    """One thing that was said, with who said it and how it reached KAE."""

    message_id: str
    text: str
    actor_type: str
    message_type: str


class AssumedEntryResponse(BaseModel):
    """One assumption, with what it would cost to be wrong."""

    assumption_id: str
    subject: str
    assumed_value: str
    reason: str
    origin: str
    consequence: str
    state: str
    reversible: bool
    material: bool
    accepted_by: str | None
    disclosure: str
    """Carries the consequence in the sentence, so no renderer can drop it."""


class UnknownEntryResponse(BaseModel):
    """One thing nobody has decided."""

    clarification_id: str
    question: str
    area_key: str | None
    severity: str
    finding_kind: str
    disposition: str


class PreliminaryContextResponse(BaseModel):
    """What a project knows, what it is guessing, and what nobody decided.

    Four separate collections rather than one annotated list. A reader who
    cannot tell a confirmed requirement from a plausible guess has a document
    that is worse than nothing — the same document with the warning removed.
    """

    project_id: str
    project_name: str
    generated_at: datetime
    knowledge_revision: int
    readiness_percentage: int
    is_preliminary: bool
    stated_verbatim: list[StatedEntryResponse]
    known: list[PreliminaryStatementResponse]
    proposed: list[PreliminaryStatementResponse]
    assumed: list[AssumedEntryResponse]
    material_unknowns: list[UnknownEntryResponse]
    deferrable_unknowns: list[UnknownEntryResponse]
    package_id: str
    content_hash: str
    statement_pins: list[dict[str, Any]]
    warnings: list[str]
    knowledge_changed: bool = False

    @classmethod
    def of(cls, preliminary: Any) -> "PreliminaryContextResponse":
        return cls(
            project_id=preliminary.project_id,
            project_name=preliminary.project_name,
            generated_at=preliminary.generated_at,
            knowledge_revision=preliminary.knowledge_revision,
            readiness_percentage=preliminary.readiness_percentage,
            is_preliminary=preliminary.is_preliminary,
            stated_verbatim=[
                StatedEntryResponse(
                    message_id=entry.message_id,
                    text=entry.text,
                    actor_type=entry.actor_type,
                    message_type=entry.message_type,
                )
                for entry in preliminary.stated_verbatim
            ],
            known=[PreliminaryStatementResponse.of(s) for s in preliminary.known],
            proposed=[PreliminaryStatementResponse.of(s) for s in preliminary.proposed],
            assumed=[
                AssumedEntryResponse(
                    assumption_id=entry.assumption_id,
                    subject=entry.subject,
                    assumed_value=entry.assumed_value,
                    reason=entry.reason,
                    origin=entry.origin,
                    consequence=entry.consequence,
                    state=entry.state,
                    reversible=entry.reversible,
                    material=entry.material,
                    accepted_by=entry.accepted_by,
                    disclosure=entry.disclosure,
                )
                for entry in preliminary.assumed
            ],
            material_unknowns=[_unknown(entry) for entry in preliminary.material_unknowns],
            deferrable_unknowns=[_unknown(entry) for entry in preliminary.deferrable_unknowns],
            package_id=preliminary.assembly.manifest.package_id,
            content_hash=preliminary.assembly.manifest.content_hash,
            statement_pins=[
                {"knowledge_id": knowledge_id, "version": version}
                for knowledge_id, version in preliminary.assembly.manifest.statement_pins
            ],
            warnings=list(preliminary.warnings),
        )


def _unknown(entry: Any) -> UnknownEntryResponse:
    return UnknownEntryResponse(
        clarification_id=entry.clarification_id,
        question=entry.question,
        area_key=entry.area_key,
        severity=entry.severity,
        finding_kind=entry.finding_kind,
        disposition=entry.disposition,
    )


class ConfigureFieldRequest(BaseModel):
    """Set one configuration field.

    `state` is the caller's claim about *how well established* the value is, and
    it is not decoration. `confirmed` means a person chose it and must name who;
    `inferred` and `suggested` must carry evidence. The domain enforces both, so
    a caller cannot record "the user confirmed this" about a guess.
    """

    field: str = Field(min_length=1)
    value: str
    state: str = "confirmed"
    evidence: str = ""
    confirmed_by: str | None = None
    derived_from_knowledge_id: str | None = None


class RegisterTargetRequest(BaseModel):
    """Register where a project may publish.

    `configuration` carries the coordinate — `{"repository": "owner/name",
    "path": "docs/"}` — and the domain refuses any key that looks like a
    credential. `make_default` is explicit: a target that silently became the
    default would route the next publication somewhere nobody chose.
    """

    provider: str = Field(min_length=1)
    name: str = Field(min_length=1)
    purpose: str = "deliverable"
    configuration: dict[str, str] = Field(default_factory=dict)
    connection_id: str | None = None
    make_default: bool = False


class SetDefaultTargetRequest(BaseModel):
    """Point a purpose at a different registered target."""

    target_id: str = Field(min_length=1)
    purpose: str = "deliverable"


class RecordConnectionRequest(BaseModel):
    """Record permission to reach a provider, never the means of doing so.

    `credential_reference` names *where* a credential lives — `env:NAME`, a
    secret-manager path, an instance-role marker. The domain refuses anything
    that looks like a credential itself, because this record is returned to
    callers and a secret in it is a secret disclosed.
    """

    provider: str = Field(min_length=1)
    credential_reference: str | None = None
    state: str = "never_granted"
    authorized_by: str | None = None
    detail: str = ""


class AuthorizeConnectionRequest(BaseModel):
    """Move a connection's authorisation state after checking it."""

    state: str = Field(min_length=1)
    authorized_by: str | None = None
    detail: str = ""


class ProviderConnectionResponse(BaseModel):
    """One recorded connection. **Never carries a credential.**"""

    connection_id: str
    provider: str
    state: str
    credential_reference: str | None
    authorized_by: str | None
    last_verified_at: datetime | None
    detail: str

    @classmethod
    def of(cls, connection: Any) -> "ProviderConnectionResponse":
        return cls(
            connection_id=str(connection.id),
            provider=connection.provider.value,
            state=connection.state.value,
            credential_reference=connection.credential_reference,
            authorized_by=connection.authorized_by,
            last_verified_at=connection.last_verified_at,
            detail=connection.detail,
        )


class ProviderConnectionListResponse(BaseModel):
    project_id: str
    results: list[ProviderConnectionResponse]
    total: int


class SetupGapResponse(BaseModel):
    """One thing setup is missing, and whether it stops anything."""

    field: str
    capability: str
    blocking: bool
    reason: str
    next_action: str


class PublicationTargetResponse(BaseModel):
    """One registered destination, described without the means to reach it.

    `unavailable_reason` rather than a bare boolean: "I never set this up", "it
    stopped working", and "somebody turned it off" have three different
    remedies, and a caller given only the boolean has to guess.
    """

    target_id: str
    name: str
    provider: str
    purpose: str
    is_default: bool
    enabled: bool
    available: bool
    unavailable_reason: str | None
    authorization: str
    configuration: dict[str, str]
    """Credential-free by construction, not by redaction on the way out."""


class SetupStateResponse(BaseModel):
    """What a project is configured to do, apart from what it knows.

    Never merged with readiness. A project with a clear brief and no
    authorisation is fully understood and cannot publish; averaging those into
    one number produces a figure that is wrong about both.
    """

    project_id: str
    setup_state: str
    blocks_anything: bool
    gaps: list[SetupGapResponse]
    configuration: dict[str, Any]
    unknown_fields: list[str]
    disclosures: list[dict[str, Any]]
    targets: list[PublicationTargetResponse]
    knowledge_changed: bool = False


class SetupQuestionResponse(BaseModel):
    """One question about configuration. Never a clarification."""

    setup_question_id: str
    purpose: str
    question: str
    field: str
    blocking: bool
    suggested_answer: str | None
    suggestion_evidence: str | None
    """Travels with the suggestion or not at all. Without it a person can only
    judge whether to trust the machine."""

    becomes_default: bool
    disposition: str


class SetupQuestionListResponse(BaseModel):
    project_id: str
    questions: list[SetupQuestionResponse]
    count: int
    knowledge_changed: bool = False


class PublicationTargetListResponse(BaseModel):
    project_id: str
    results: list[PublicationTargetResponse]
    total: int
    knowledge_changed: bool = False


class AnswerClarificationRequest(BaseModel):
    """What a person said about a question — which is not always a decision.

    `disposition` defaults to `answered`. Anything else records the response and
    leaves the question open, because "I don't know yet, pick something
    reasonable" settles nothing and must not be stored as though it did.
    """

    answer: str = Field(min_length=1)
    disposition: Disposition = Disposition.ANSWERED
    assumption_id: str | None = None
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
            note=message("integrity.operational_reported"),
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
            note=message("integrity.classification_not_truth"),
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
    publication_eligible: bool = False
    ineligibility_reason: str | None = None
    statement_pins: list[dict[str, Any]] = Field(default_factory=list)
    render_inputs: dict[str, Any] | None = None
    qualification: dict[str, Any] | None = None
    provisional_context: dict[str, Any] | None = None
    """What this package rested on (N20.2). `None` where it was never captured.

    Absent rather than empty: "generated under no uncertainty" and "we did not
    record the uncertainty" are different claims, and only the first reassures.
    """
    rested_on_uncertainty: bool | None = None
    reproduces_uncertainty: bool = False
    """Whether the *claim* can be reproduced, not only the bytes (N20.2).

    Separate from `publication_eligible`: a record from before this existed can
    still be re-rendered identically, and refusing to publish it would withdraw
    a capability it genuinely has.
    """
    uncertainty_gap_reason: str | None = None
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
            publication_eligible=deliverable.publication_eligible,
            ineligibility_reason=deliverable.ineligibility_reason,
            statement_pins=[
                {"knowledge_id": pin.knowledge_id, "version": pin.version}
                for pin in deliverable.statement_pins
            ],
            render_inputs=(
                deliverable.render_inputs.as_dict() if deliverable.render_inputs else None
            ),
            qualification=deliverable.qualification,
            provisional_context=(
                deliverable.provisional_context.as_dict()
                if deliverable.provisional_context
                else None
            ),
            rested_on_uncertainty=(
                deliverable.provisional_context.rested_on_uncertainty
                if deliverable.provisional_context
                else None
            ),
            reproduces_uncertainty=deliverable.reproduces_uncertainty,
            uncertainty_gap_reason=deliverable.uncertainty_gap_reason,
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


# -- assumptions (N45) -----------------------------------------------------


class RecordAssumptionRequest(BaseModel):
    #: Where this assumption came from.
    #:
    #: The service has always taken it and this schema did not, so
    #: `kae_recommended_accepted` and `unresolved_alternative` could not be
    #: written over HTTP at all — the two origins that exist precisely to record
    #: what a person did with KAE's advice.
    #:
    #: **`user_stated` is refused.** A caller asserting that a person said
    #: something is a caller manufacturing provenance, and the whole point of
    #: the origin is that it distinguishes what somebody said from what KAE
    #: worked out. Directive principle 8: model-generated inference must never
    #: silently become user-confirmed knowledge.
    origin: str = "kae_inferred"
    subject: str = Field(min_length=1)
    assumed_value: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    consequence: str = "rework"
    confidence: float = Field(default=0.5, ge=0, le=1)
    reversible: bool = True
    revisit: str = "on_request"
    evidence: list[str] = Field(default_factory=list)


class AcceptAssumptionRequest(BaseModel):
    actor: str = Field(min_length=1)


class AssumptionResponse(BaseModel):
    """One interpretation used in place of missing information.

    `material` and `consequence` travel together because "we assumed
    PostgreSQL" and "we assumed single-tenant" are not the same risk, and a
    list that rendered them alike would bury the second among the first.
    """

    assumption_id: str
    subject: str
    assumed_value: str
    reason: str
    origin: str
    consequence: str
    material: bool
    confidence: float
    reversible: bool
    revisit: str
    state: str
    accepted_by: str | None
    evidence: list[str] = Field(default_factory=list)
    knowledge_changed: bool = False

    @classmethod
    def of(cls, assumption: Any) -> "AssumptionResponse":
        return cls(
            assumption_id=str(assumption.id),
            subject=assumption.subject,
            assumed_value=assumption.assumed_value,
            reason=assumption.reason,
            origin=assumption.origin.value,
            consequence=assumption.consequence.value,
            material=assumption.material,
            confidence=round(assumption.confidence, 2),
            reversible=assumption.reversible,
            revisit=assumption.revisit.value,
            state=assumption.state.value,
            accepted_by=assumption.accepted_by,
            evidence=list(assumption.evidence),
        )


class AssumptionListResponse(BaseModel):
    assumptions: list[AssumptionResponse]
    total: int
    omitted: int
    material_count: int
    note: str

    @classmethod
    def of(cls, records: Sequence[Any], limit: int) -> "AssumptionListResponse":
        shown = list(records)[:limit]
        return cls(
            assumptions=[AssumptionResponse.of(record) for record in shown],
            total=len(records),
            omitted=max(0, len(records) - len(shown)),
            material_count=sum(1 for record in records if record.material),
            note=(
                "Assumptions are not knowledge. A material one must be disclosed "
                "wherever the output it shaped is disclosed."
            ),
        )


# -- modules ------------------------------------------------------------------


class ModuleResponse(BaseModel):
    """One part of the system being defined.

    `status` is deliberately not progress. How far along an implementation is
    belongs to operational state and decays differently; this says whether the
    module is part of the system at all.
    """

    key: str
    name: str
    summary: str
    status: str

    @classmethod
    def of(cls, module: Any) -> "ModuleResponse":
        return cls(
            key=module.key,
            name=module.name,
            summary=module.summary,
            status=module.status.value,
        )


class ModuleEdgeResponse(BaseModel):
    """One directed edge, named by the keys a reader recognises.

    Module identifiers are internal; a graph returned in them is one the caller
    has to resolve before it can be drawn, and every caller would resolve it the
    same way. Edges to a statement carry `target_knowledge` instead, and the two
    are exclusive.
    """

    source: str
    relation: str
    target_module: str | None = None
    target_knowledge: str | None = None


class ModuleGraphResponse(BaseModel):
    """Every module, every edge, and the order they can be built in.

    Build order answers the question a dependency graph exists for, and ties
    break by key so the answer is stable — an order that varies between calls
    cannot be compared with the previous one, which is most of what it is for.
    """

    project_id: str
    modules: list[ModuleResponse]
    edges: list[ModuleEdgeResponse]
    build_order: list[str]
    note: str = (
        "Build order follows depends_on only. A module with no dependencies may "
        "still need knowledge that is not yet confirmed."
    )


class ModuleNeighbourhoodResponse(BaseModel):
    """What one module touches, in both directions.

    Dependencies and dependents are both here because they answer opposite
    questions a reader needs together: what must exist before I build this, and
    what breaks if I change it.
    """

    module: ModuleResponse
    depends_on: list[ModuleResponse]
    dependents: list[ModuleResponse]
    exposes: list[ModuleResponse]
    consumes: list[ModuleResponse]
    owns: list[ModuleResponse]
    owned_by: ModuleResponse | None
    satisfies: list[str]
    verified_by: list[str]

    @classmethod
    def of(cls, neighbourhood: Any) -> "ModuleNeighbourhoodResponse":
        def modules(values: Sequence[Any]) -> list[ModuleResponse]:
            return [ModuleResponse.of(module) for module in values]

        return cls(
            module=ModuleResponse.of(neighbourhood.module),
            depends_on=modules(neighbourhood.depends_on),
            dependents=modules(neighbourhood.dependents),
            exposes=modules(neighbourhood.exposes),
            consumes=modules(neighbourhood.consumes),
            owns=modules(neighbourhood.owns),
            owned_by=(
                ModuleResponse.of(neighbourhood.owned_by)
                if neighbourhood.owned_by is not None
                else None
            ),
            satisfies=list(neighbourhood.satisfies),
            verified_by=list(neighbourhood.verified_by),
        )


# -- sources ------------------------------------------------------------------


class RegisterSourceRequest(BaseModel):
    """Where a project's material comes from.

    `kind` and `state` are Studio's vocabulary and are carried rather than
    validated against an enumeration here. Memory has no rule that reads them,
    and two systems with an opinion about one lifecycle is how they come to
    disagree — `SourceState` lives in Studio's acquisition model and is the one
    place it should live.
    """

    kind: str
    location: str
    state: str = "configured"
    connection_id: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    disposition: str | None = None


class RecordSourceStateRequest(BaseModel):
    state: str
    #: The provider's own words for a refusal or an unreachable host. A reason
    #: paraphrased on the way through is one nobody can act on.
    detail: str = ""


class PinSourceRequest(BaseModel):
    revision: str
    digest: str | None = None
    state: str = "pinned"


class ClassifySourceRequest(BaseModel):
    disposition: str


class SourceResponse(BaseModel):
    """One source, with what was pinned and what nobody has decided.

    `disposition` is `null` until somebody classifies the source. That is not
    the same as *"keep it in Memory"*, and no default is supplied, because a
    source nobody has classified passing for one somebody decided to keep is
    the more expensive of the two mistakes.
    """

    source_id: str
    project_id: str
    kind: str
    location: str
    state: str
    connection_id: str | None
    scope: dict[str, Any]
    pinned_revision: str | None
    digest: str | None
    disposition: str | None
    detail: str
    #: Whether this source names an immutable revision. Computed rather than
    #: left to each caller, because "is this recheckable" is the question the
    #: record exists to answer.
    pinned: bool
    #: When somebody stopped KAE reading this source; `null` means nobody has.
    #: Served as the timestamp rather than a flag, so a reader can say *when*
    #: without a second call (`D-254`).
    retired_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def of(cls, source: Any) -> "SourceResponse":
        return cls(
            source_id=source.source_id,
            project_id=source.project_id,
            kind=source.kind,
            location=source.location,
            state=source.state,
            connection_id=source.connection_id,
            scope=dict(source.scope),
            pinned_revision=source.pinned_revision,
            digest=source.digest,
            disposition=source.disposition,
            detail=source.detail,
            pinned=source.is_pinned,
            retired_at=source.retired_at,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )


class SourceMaterialResponse(BaseModel):
    """One source and the stored text a decision about it would reach."""

    source_id: str
    kind: str
    location: str
    disposition: str | None
    #: Distinct documents ingested naming this source — what a person chose.
    documents: int
    #: Copies of text those choices produced, one per ingestion run. The number
    #: `ADR-0004` step 3 is about: a long file is one document and many bodies.
    stored_bodies: int

    @classmethod
    def of(cls, material: Any) -> "SourceMaterialResponse":
        return cls(
            source_id=material.source_id,
            kind=material.kind,
            location=material.location,
            disposition=material.disposition,
            documents=material.documents,
            stored_bodies=material.stored_bodies,
        )


class MaterialReportResponse(BaseModel):
    """What material a retention decision would apply to, before any is removed.

    Reports; enforces nothing. A source classified `ephemeral` is counted
    exactly like one classified `memory`, because no disposition is acted on
    anywhere in this system yet.
    """

    sources: list[SourceMaterialResponse]
    #: Material naming no source, which therefore no disposition can govern —
    #: every pasted document, and everything ingested before the link existed.
    #: Its own number rather than a share of a total, since the answer *nothing
    #: you decide reaches this* is the one a person most needs.
    unattributed_documents: int
    unattributed_bodies: int

    @classmethod
    def of(cls, report: Any) -> "MaterialReportResponse":
        return cls(
            sources=[SourceMaterialResponse.of(material) for material in report.sources],
            unattributed_documents=report.unattributed_documents,
            unattributed_bodies=report.unattributed_bodies,
        )


class IngestedDocumentResponse(BaseModel):
    """One document read out of a source, and when it was last read."""

    #: The coordinate the ingesting run named — for a repository, the path
    #: within it. The ingester's own word, not a name reconstructed from the
    #: source location and a guess about layout.
    document: str
    #: Ingestion runs that produced text for this document. More than one
    #: because a long file is chunked, which is why a document count and a body
    #: count are different numbers.
    stored_bodies: int
    last_read_at: datetime | None

    @classmethod
    def of(cls, document: Any) -> "IngestedDocumentResponse":
        return cls(
            document=document.document,
            stored_bodies=document.stored_bodies,
            last_read_at=document.last_read_at,
        )


class SourceDocumentsResponse(BaseModel):
    """Which documents a source taught KAE, named rather than counted.

    `/source-material` answers *how much*; this answers *which*. A person shown
    only a total cannot tell whether the include paths caught what they meant.
    """

    source_id: str
    documents: list[IngestedDocumentResponse]
    #: Every distinct document under this source, not just the ones listed —
    #: so a page can say *412, showing 200* rather than implying 200 is all
    #: there is.
    total_documents: int
    #: Whether documents exist that this response does not name. Computed here
    #: rather than left to a caller comparing two numbers, since a caller that
    #: forgot to compare would present a partial list as complete.
    truncated: bool

    @classmethod
    def of(cls, listing: Any) -> "SourceDocumentsResponse":
        return cls(
            source_id=listing.source_id,
            documents=[IngestedDocumentResponse.of(entry) for entry in listing.documents],
            total_documents=listing.total_documents,
            truncated=listing.truncated,
        )


class PutSynthesizedObjectRequest(BaseModel):
    """Create or update a working-model object. Idempotent by identity_key."""

    domain: str = Field(min_length=1)
    identity_key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class CorrectSynthesizedObjectRequest(BaseModel):
    """A person's wording for a synthesized object. Evidence is not deleted."""

    title: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class BindEvidenceRequest(BaseModel):
    knowledge_item_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class SetEvidenceRoleRequest(BaseModel):
    role: str = Field(min_length=1)


class PutAttentionRequest(BaseModel):
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    identity_key: str | None = None
    recommendation: str | None = None
    synthesized_object_id: str | None = None
    priority: int = 0
    actions: list[str] = Field(default_factory=list)


class ResolveAttentionRequest(BaseModel):
    status: str = "resolved"


class RecordChangeRequest(BaseModel):
    idempotency_key: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class EvidenceBindingResponse(BaseModel):
    id: str
    knowledge_item_id: str
    kind: str
    created_at: datetime | None

    @classmethod
    def of(cls, binding: Any) -> "EvidenceBindingResponse":
        return cls(
            id=str(binding.id),
            knowledge_item_id=str(binding.knowledge_item_id),
            kind=binding.kind.value,
            created_at=binding.created_at,
        )


class BoundEvidenceResponse(BaseModel):
    """An evidence link and the sentence it points at.

    Separate from `EvidenceBindingResponse`, which answers *the link was made*
    to a caller that already holds the statement. A statement field there would
    be empty on the write and populated on the read, and no reader could tell
    *not fetched* from *nothing to say*.
    """

    id: str
    knowledge_item_id: str
    kind: str
    statement: str
    knowledge_kind: str
    lifecycle: str
    created_at: datetime | None

    @classmethod
    def of(cls, evidence: Any) -> "BoundEvidenceResponse":
        binding = evidence.binding
        return cls(
            id=str(binding.id),
            knowledge_item_id=str(binding.knowledge_item_id),
            kind=binding.kind.value,
            statement=evidence.statement,
            knowledge_kind=evidence.knowledge_kind,
            lifecycle=evidence.lifecycle,
            created_at=binding.created_at,
        )


class SynthesizedObjectResponse(BaseModel):
    """One object in the current project model, not an extracted sentence."""

    id: str
    project_id: str
    domain: str
    identity_key: str
    title: str
    statement: str
    lifecycle: str
    authority: str
    revision: int
    evidence: list[BoundEvidenceResponse] = Field(default_factory=list)
    supporting_evidence: int
    """How many observations this object was drawn from — `D-167`.

    Bindings recorded as `supports` only (`D-187`). `evidence` below may be
    longer: a row bound as `contradicts`, `superseded_by` or `resolved_by` is
    evidence about this object, listed with its own `kind`, and is not something
    the object was drawn from — which is the sentence this number is read under.

    Present on **every** read, including the ones that carry no statements.
    `evidence` is empty on the list and populated on the detail, which without
    this field leaves a reader unable to tell *not fetched* from *nothing
    supports this* — the ambiguity `BoundEvidenceResponse` exists to prevent,
    one level up from where it was prevented.

    Doc 01's aggregation asks for one item with 73 expandable instances. This is
    the 73; the instances are the read below it.
    """

    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def of(
        cls, obj: Any, evidence: Sequence[Any] = (), *, supporting_evidence: int
    ) -> "SynthesizedObjectResponse":
        return cls(
            id=str(obj.id),
            project_id=str(obj.project_id),
            domain=obj.domain,
            identity_key=obj.identity_key,
            title=obj.title,
            statement=obj.statement,
            lifecycle=obj.lifecycle.value,
            authority=obj.authority.value,
            revision=obj.revision,
            evidence=[BoundEvidenceResponse.of(bound) for bound in evidence],
            supporting_evidence=supporting_evidence,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


class EvidenceRoleResponse(BaseModel):
    knowledge_item_id: str
    role: str

    @classmethod
    def of(cls, knowledge_item_id: str, role: Any) -> "EvidenceRoleResponse":
        value = role.value if hasattr(role, "value") else str(role)
        return cls(knowledge_item_id=knowledge_item_id, role=value)


class AttentionItemResponse(BaseModel):
    """A human-attention item. Unconfirmed extraction is not one of these."""

    id: str
    project_id: str
    kind: str
    title: str
    explanation: str
    status: str
    identity_key: str | None
    recommendation: str | None
    synthesized_object_id: str | None
    priority: int
    actions: list[str]
    created_at: datetime | None
    updated_at: datetime | None

    @classmethod
    def of(cls, item: Any) -> "AttentionItemResponse":
        object_id = item.synthesized_object_id
        return cls(
            id=str(item.id),
            project_id=str(item.project_id),
            kind=item.kind.value,
            title=item.title,
            explanation=item.explanation,
            status=item.status.value,
            identity_key=item.identity_key,
            recommendation=item.recommendation,
            synthesized_object_id=None if object_id is None else str(object_id),
            priority=item.priority,
            actions=list(item.actions),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class ReconciliationEventResponse(BaseModel):
    id: str
    project_id: str
    idempotency_key: str
    trigger: str
    summary: str
    created_at: datetime | None

    @classmethod
    def of(cls, event: Any) -> "ReconciliationEventResponse":
        return cls(
            id=str(event.id),
            project_id=str(event.project_id),
            idempotency_key=event.idempotency_key,
            trigger=event.trigger.value,
            summary=event.summary,
            created_at=event.created_at,
        )


class RunReconciliationRequest(BaseModel):
    """Optional key and incremental focus for a deterministic reconciliation pass."""

    idempotency_key: str | None = None
    item_ids: list[str] = Field(default_factory=list)


class RunGoalSynthesisRequest(BaseModel):
    """Optional idempotency key for a goal-synthesis pass."""

    idempotency_key: str | None = None


class WithheldCandidateResponse(BaseModel):
    """A statement that did not enter the model, and why it did not."""

    statement: str
    reason: str


class GoalSynthesisReportResponse(BaseModel):
    """What one goal-synthesis run concluded, including its exclusions."""

    project_id: str
    replayed: bool
    judged: bool
    """False when no judge was configured, and only corroborated clusters ran.

    A caller must be able to tell a smaller model from a fuller one: the same
    project synthesized with and without a judge produces different output for
    the same evidence, and reading one as the other would look like knowledge
    disappearing (`D-101`).
    """

    considered: int
    clustered: bool
    """False when the deployment's vectors measure the chunk envelope (`D-102`).

    Every observation then stands alone. A reader must be able to tell a model
    that was compacted from one that merely was not compared.
    """

    promoted: list[str]
    withheld: list[WithheldCandidateResponse]

    @classmethod
    def of(cls, report: Any) -> "GoalSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            judged=report.judged,
            considered=report.considered,
            clustered=report.clustered,
            promoted=[str(object_id) for object_id, _ in report.promoted],
            withheld=[
                WithheldCandidateResponse(statement=statement, reason=reason)
                for statement, reason in report.withheld
            ],
        )


class RunUnknownSynthesisRequest(BaseModel):
    """Optional idempotency key for an unknown-synthesis pass."""

    idempotency_key: str | None = None


class RaisedAttentionResponse(BaseModel):
    """An attention item this run put in front of a person."""

    attention_item_id: str
    question: str


class UnknownSynthesisReportResponse(BaseModel):
    """What one unknown-synthesis run concluded, including what it withheld."""

    project_id: str
    considered: int
    resolved: int
    """Extracted unknowns another source already answered. Kept, not raised."""

    themes: int
    raised: list[RaisedAttentionResponse]
    withheld: list[str]
    """Current themes below the attention bound. Real, and deliberately unraised.

    Reported for the same reason `GoalSynthesisReportResponse.withheld` is: a
    queue of 8 drawn from 36 themes makes its own 28 exclusions the first thing
    anybody asks about, and a response naming only the 8 would leave that
    question unanswerable from the wire.
    """

    clustered: bool
    """False when no statement-space vectors were available (`D-102`).

    Every unknown then stands alone, so a reader can tell a set of themes that
    was compacted from one that merely was not compared.
    """

    ranked_by_blocking: bool

    @classmethod
    def of(cls, report: Any) -> "UnknownSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            considered=report.considered,
            resolved=report.resolved,
            themes=report.themes,
            raised=[
                RaisedAttentionResponse(attention_item_id=str(item_id), question=question)
                for item_id, question in report.attention
            ],
            withheld=list(report.withheld),
            clustered=report.clustered,
            ranked_by_blocking=report.ranked_by_blocking,
        )


class RunActorSynthesisRequest(BaseModel):
    """Optional idempotency key for an actor-synthesis pass."""

    idempotency_key: str | None = None


class SynthesizedRoleResponse(BaseModel):
    """One role in the project's actor model, and what kind of thing it is."""

    synthesized_object_id: str
    statement: str
    kind: str
    """`project_role`, `persona`, `ai_role`, `system` or `unclassified`.

    Derived from the relation rather than stored: a human-shaped role holding no
    responsibility anywhere is a persona (doc 03 line 10).
    """


class ResponsibilityAssignmentResponse(BaseModel):
    """One cell of `Role × Subject → Responsibility`."""

    role_statement: str
    subject_key: str
    letter: str


class ActorSynthesisReportResponse(BaseModel):
    """What one actor-synthesis run concluded, including what it refused."""

    project_id: str
    replayed: bool
    considered: int
    clustered: bool
    """Always false, and sent rather than omitted (`D-121`).

    Actor descriptions are noun phrases in the project's own vocabulary, so
    embedding distance between two of them measures shared subject matter — the
    nearest pair in the golden corpus is a human and the AI product. Nothing is
    clustered, and a caller must be able to tell that from a model that was.
    """

    roles: list[SynthesizedRoleResponse]
    assignments: list[ResponsibilityAssignmentResponse]
    conflicts: list[str]
    """Second Accountable claimants. Each is also an attention item."""

    downgraded: list[str]
    """Non-human claimants of Accountable, refused and reported here only.

    A governance rule that fired correctly is not an interruption, so these do
    not enter the attention queue. Omitting them would hide that the evidence
    made the claim at all.
    """

    @classmethod
    def of(cls, report: Any) -> "ActorSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            considered=report.considered,
            clustered=report.clustered,
            roles=[
                SynthesizedRoleResponse(
                    synthesized_object_id=str(object_id), statement=statement, kind=kind.value
                )
                for object_id, statement, kind in report.roles
            ],
            assignments=[
                ResponsibilityAssignmentResponse(
                    role_statement=role_statement, subject_key=subject_key, letter=letter
                )
                for role_statement, subject_key, letter in report.assignments
            ],
            conflicts=[reason for _, reason in report.conflicts],
            downgraded=[reason for _, reason in report.downgraded],
        )


class RunDecisionSynthesisRequest(BaseModel):
    """Optional idempotency key for a decision-synthesis pass."""

    idempotency_key: str | None = None


class SynthesizedDecisionResponse(BaseModel):
    """One decision, and the reading behind the state it was stored in."""

    synthesized_object_id: str
    statement: str
    decision_class: str
    """`product_scope`, `architecture`, `governance`, `planning`, `workflow` or
    `unclassified` — derived from the wording rather than stored (`D-125`)."""

    scope: str
    """`project` or `session`. Orthogonal to the class, so *"in this session,
    skip architecture"* stays a workflow decision that binds nothing."""

    settled: bool
    """Whether a person accepted this. Wording never promotes (`D-123`)."""

    basis: str


class DecisionNoteResponse(BaseModel):
    """One decision the run has something to say about, and what it says.

    The statement travels with the reason because these reasons are about a
    rule rather than about a subject: *"nobody has accepted it"* reads the same
    for every row, so a list of reasons alone would name nothing.
    """

    statement: str
    reason: str


class DecisionSynthesisReportResponse(BaseModel):
    """What one decision-synthesis run concluded, including what it refused."""

    project_id: str
    replayed: bool
    considered: int
    decisions: list[SynthesizedDecisionResponse]

    awaiting: list[DecisionNoteResponse]
    """Decisions nobody has accepted. Sent, and deliberately not attention.

    One queue item per unaccepted decision would be the extracted-review queue
    under a new name, which is what `ADR-0007` exists to remove (`D-125`).
    """

    conflicts: list[DecisionNoteResponse]
    """Accepted decisions the project's own state contradicts.

    These are also attention items — doc 08 asks for conflict analysis rather
    than a second contradictory record.
    """

    session_scoped: list[DecisionNoteResponse]
    """Decisions refused permanence, with the reason each was refused."""

    @classmethod
    def of(cls, report: Any) -> "DecisionSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            considered=report.considered,
            decisions=[
                SynthesizedDecisionResponse(
                    synthesized_object_id=str(decision.object_id),
                    statement=decision.statement,
                    decision_class=decision.decision_class.value,
                    scope=decision.scope.value,
                    settled=decision.settled,
                    basis=decision.basis,
                )
                for decision in report.decisions
            ],
            awaiting=[
                DecisionNoteResponse(statement=statement, reason=reason)
                for statement, reason in report.awaiting
            ],
            conflicts=[
                DecisionNoteResponse(statement=statement, reason=reason)
                for statement, reason in report.conflicts
            ],
            session_scoped=[
                DecisionNoteResponse(statement=statement, reason=reason)
                for statement, reason in report.session_scoped
            ],
        )


class RunAssumptionSynthesisRequest(BaseModel):
    """Optional idempotency key for an assumption-synthesis pass."""

    idempotency_key: str | None = None


class SynthesizedAssumptionResponse(BaseModel):
    """One project assumption, and what the project loses if it is wrong."""

    synthesized_object_id: str
    statement: str
    consequence: str
    """`scope`, `architecture`, `requirements`, `cost`, `workflow`, `outcome` or
    `undetermined` — derived from the wording rather than stored (`D-136`).

    `undetermined` is a real answer and the common one: an assumption whose
    falsity KAE cannot connect to anything is doc 05's complaint, not a gap to
    fill by guessing.
    """

    settled: bool
    """Whether a person accepted this as established. Wording never promotes."""

    needs_validation: bool
    """Doc 05's *material-needs-validation* — still working, and its falsity
    reaches a named consequence. A state to sort by, never an interruption."""

    basis: str


class AssumptionNoteResponse(BaseModel):
    """One row the run has something to say about, and what it says.

    The statement travels with the reason, as `DecisionNoteResponse` does and
    for the same reason: these reasons are about a rule rather than a subject.
    """

    statement: str
    reason: str


class AssumptionSynthesisReportResponse(BaseModel):
    """What one assumption-synthesis run concluded, including what it separated."""

    project_id: str
    replayed: bool
    considered: int
    assumptions: list[SynthesizedAssumptionResponse]

    scaffolding: list[AssumptionNoteResponse]
    """Interpretation assumptions — about reading the conversation, not the project.

    Sent rather than dropped: a silent filter is indistinguishable from an
    extractor that never produced them, and doc 05's complaint is that nobody
    can see which rows are which. **No evidence role is written for them**
    (`D-136`); the role is applied through `PUT .../evidence-role` by a person.
    """

    resolved: list[AssumptionNoteResponse]
    """Assumptions the project already establishes, each naming the statement that did."""

    needing_validation: list[AssumptionNoteResponse]
    """Each material assumption and what makes it material.

    A projection of `needs_validation` above, and deliberately not the attention
    queue: one interrupt per unvalidated assumption is the review queue
    `ADR-0007` exists to remove, under a new name (`D-135`).
    """

    @classmethod
    def of(cls, report: Any) -> "AssumptionSynthesisReportResponse":
        def notes(pairs: Any) -> list[AssumptionNoteResponse]:
            return [
                AssumptionNoteResponse(statement=statement, reason=reason)
                for statement, reason in pairs
            ]

        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            considered=report.considered,
            assumptions=[
                SynthesizedAssumptionResponse(
                    synthesized_object_id=str(assumption.object_id),
                    statement=assumption.statement,
                    consequence=assumption.consequence.value,
                    settled=assumption.settled,
                    needs_validation=assumption.needs_validation,
                    basis=assumption.basis,
                )
                for assumption in report.assumptions
            ],
            scaffolding=notes(report.scaffolding),
            resolved=notes(report.resolved),
            needing_validation=notes(report.needing_validation),
        )


class StoredConstraintEffectResponse(BaseModel):
    """One stored consequence an accepted boundary imposes on one open item.

    This is the read side of the relation doc 07 says a constraint is worth
    having for: what bounds *this* question, without recomputing the whole
    constraint-by-item cross product.
    """

    constraint_statement: str
    knowledge_item_id: str
    kind: str
    basis: str


class RunConstraintSynthesisRequest(BaseModel):
    """Optional idempotency key for a constraint-synthesis pass."""

    idempotency_key: str | None = None


class SynthesizedConstraintResponse(BaseModel):
    """One boundary, and the reading behind what it was allowed to do."""

    synthesized_object_id: str
    statement: str
    family: str
    """One of doc 07's eight families, read from the wording and not stored."""

    restricts: bool
    """Whether this sentence bounds anything. A non-boundary imposes nothing."""

    accepted: bool
    """Whether a person accepted it. Only an accepted boundary propagates."""


class ConstraintEffectResponse(BaseModel):
    """One consequence an accepted boundary imposes on one open item.

    Carries no status: doc 07 offers *Add exception* and *Change scope* beside
    *Accept*, so an effect is an argument about an item, not a verdict on it.
    """

    constraint_object_id: str
    knowledge_item_id: str
    statement: str
    item_statement: str
    kind: str
    """`resolves` or `narrows` — containment versus shared subject."""

    basis: str


class ProposedConstraintEffectResponse(BaseModel):
    """What would follow if an unaccepted boundary were accepted.

    Reported and stored nowhere (`D-126`). The item travels with the constraint
    because *"it would narrow something"* names nothing a person could act on.
    """

    statement: str
    item_statement: str
    basis: str


class ConstraintSynthesisReportResponse(BaseModel):
    """What one constraint-synthesis run concluded, and what it did not apply."""

    project_id: str
    replayed: bool
    considered: int
    open_items: int
    constraints: list[SynthesizedConstraintResponse]

    effects: list[ConstraintEffectResponse]
    """What accepted boundaries bear on, and the only thing the run wrote."""

    proposed_effects: list[ProposedConstraintEffectResponse]
    """What unaccepted boundaries would bear on. Computed, never applied.

    Being wrong about a boundary silently closes a question the project still
    has, so an unaccepted one changes nothing and says what it would change.
    """

    @classmethod
    def of(cls, report: Any) -> "ConstraintSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            considered=report.considered,
            open_items=report.open_items,
            constraints=[
                SynthesizedConstraintResponse(
                    synthesized_object_id=str(constraint.object_id),
                    statement=constraint.statement,
                    family=constraint.family.value,
                    restricts=constraint.restricts,
                    accepted=constraint.accepted,
                )
                for constraint in report.constraints
            ],
            effects=[
                ConstraintEffectResponse(
                    constraint_object_id=str(effect.constraint_object_id),
                    knowledge_item_id=str(effect.knowledge_item_id),
                    statement=effect.statement,
                    item_statement=effect.item_statement,
                    kind=effect.kind,
                    basis=effect.basis,
                )
                for effect in report.effects
            ],
            proposed_effects=[
                ProposedConstraintEffectResponse(
                    statement=statement, item_statement=item_statement, basis=basis
                )
                for statement, item_statement, basis in report.proposed_effects
            ],
        )


class AddAcceptanceCriterionRequest(BaseModel):
    """One criterion a person writes against a requirement.

    Doc 06 lists *Add acceptance criteria* among the human actions, and this is
    the only way a row reaches ``acceptance_criteria``: no synthesis path writes
    one, because a criterion KAE generated would make its requirement
    implementation-ready by the act of synthesising it (`D-131`).
    """

    statement: str


class AcceptanceCriterionResponse(BaseModel):
    """One stored criterion, and the requirement it says *done* for."""

    criterion_id: str
    requirement_object_id: str
    statement: str


class RunRequirementSynthesisRequest(BaseModel):
    """Optional idempotency key for a requirement-synthesis pass."""

    idempotency_key: str | None = None


class SynthesizedRequirementResponse(BaseModel):
    """One requirement, and the reading behind whether it can be built to."""

    synthesized_object_id: str
    statement: str
    verifiability: str
    """`observable`, `compound` or `vague` — read from the wording, not stored."""

    capability_areas: list[str]
    accepted: bool
    """Whether a person accepted it. *Must* and *shall* confer nothing (`D-129`)."""

    criteria: list[str]
    """The criteria somebody wrote. Empty is the common case and the finding."""

    implementation_ready: bool
    """Derived from the other three, never stored (`D-125`)."""


class ReclassifiedStatementResponse(BaseModel):
    """A statement separated out of the requirement list, and named.

    Doc 06's mixed list is separated rather than filtered: deleting a principle
    loses a real statement, and leaving it among the requirements is the failure.
    """

    statement: str
    kind: str


class RequirementSplitResponse(BaseModel):
    """A compound requirement named in halves, applied to nothing.

    Doc 06: *web MVP with mobile later* rather than a binary Confirm/Reject.
    """

    statement: str
    first: str
    second: str
    basis: str


class RequirementSynthesisReportResponse(BaseModel):
    """What one requirement-synthesis run concluded, and what it separated out."""

    project_id: str
    replayed: bool
    considered: int
    requirements: list[SynthesizedRequirementResponse]
    reclassified: list[ReclassifiedStatementResponse]
    splits: list[RequirementSplitResponse]

    implementation_ready: int
    """How many are ready. Zero until somebody writes criteria, and that is the point."""

    @classmethod
    def of(cls, report: Any) -> "RequirementSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            considered=report.considered,
            requirements=[
                SynthesizedRequirementResponse(
                    synthesized_object_id=str(requirement.object_id),
                    statement=requirement.statement,
                    verifiability=requirement.verifiability.value,
                    capability_areas=list(requirement.capability_areas),
                    accepted=requirement.accepted,
                    criteria=list(requirement.criteria),
                    implementation_ready=requirement.implementation_ready,
                )
                for requirement in report.requirements
            ],
            reclassified=[
                ReclassifiedStatementResponse(statement=one.statement, kind=one.kind.value)
                for one in report.reclassified
            ],
            splits=[
                RequirementSplitResponse(
                    statement=split.statement,
                    first=split.first,
                    second=split.second,
                    basis=split.basis,
                )
                for split in report.splits
            ],
            implementation_ready=report.implementation_ready,
        )


class AttributeRuleRequest(BaseModel):
    """Where one rule came from, as a person states it.

    This is the only way a row reaches ``rule_attributions``: no synthesis path
    writes one, because an origin KAE attributed would make the rule active by
    the act of synthesising it (`D-132`).

    ``source_object_id`` is the synthesized object the rule leans on, when there
    is one. Naming it defers the question of acceptance to that object; omitting
    it makes this a direct assertion of provenance (`D-133`).
    """

    origin: str
    source_object_id: str | None = None


class RuleAttributionResponse(BaseModel):
    """One stored attribution, and the rule it says the origin of."""

    attribution_id: str
    rule_object_id: str
    origin: str
    source_object_id: str | None = None


class NameRuleMechanismRequest(BaseModel):
    """What enforces one rule — a check, a permission, a gate.

    The only way a row reaches ``rule_enforcement_mechanisms``: a mechanism KAE
    named would make every rule an enforceable control by the act of
    synthesising it (`D-132`).
    """

    name: str


class RuleEnforcementMechanismResponse(BaseModel):
    """One stored mechanism, and the rule it enforces."""

    mechanism_id: str
    rule_object_id: str
    name: str


class RunRuleSynthesisRequest(BaseModel):
    """Optional idempotency key for a rule-synthesis pass."""

    idempotency_key: str | None = None


class SynthesizedRuleResponse(BaseModel):
    """One rule, and everything that decides what it weighs."""

    synthesized_object_id: str
    statement: str
    family: str
    """What the rule is about. Read from the wording, and carries no weight."""

    origin: str
    """Where it came from. `unattributed` until a person says (`D-132`)."""

    authority: str
    """What it can overrule. Derived from the origin and never from the wording."""

    active: bool
    """Whether it governs anything — the source's acceptance, not its grammar."""

    enforceable: bool
    """A control rather than descriptive policy: a mechanism was named for it."""

    mechanisms: list[str]
    capability_areas: list[str]


class RuleSynthesisReportResponse(BaseModel):
    """What one rule-synthesis run concluded, and what it could not weigh."""

    project_id: str
    replayed: bool
    considered: int
    rules: list[SynthesizedRuleResponse]

    active: int
    controls: int

    unattributed: list[str]
    """The rules nobody said the origin of. Usually all of them, and that is doc 04's complaint."""

    families: list[str]
    """The families present among active rules. Empty while nothing is active."""

    @classmethod
    def of(cls, report: Any) -> "RuleSynthesisReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            considered=report.considered,
            rules=[
                SynthesizedRuleResponse(
                    synthesized_object_id=str(rule.object_id),
                    statement=rule.statement,
                    family=rule.family.value,
                    origin=rule.origin.value,
                    authority=rule.authority.value,
                    active=rule.active,
                    enforceable=rule.enforceable,
                    mechanisms=list(rule.mechanisms),
                    capability_areas=list(rule.capability_areas),
                )
                for rule in report.rules
            ],
            active=report.active,
            controls=report.controls,
            unattributed=list(report.unattributed),
            families=[family.value for family in report.families],
        )


class AffectedSectionResponse(BaseModel):
    domain: str
    item_ids: list[str]
    reasons: list[str]


class ReconciliationEdgeResponse(BaseModel):
    source_id: str
    target_id: str
    type: str
    reason: str


class ReconciliationRoleResponse(BaseModel):
    knowledge_item_id: str
    role: str


class ReconciliationReportResponse(BaseModel):
    """Result of a deterministic reconciliation pass. Not a synthesized model."""

    project_id: str
    replayed: bool
    event: ReconciliationEventResponse
    edges_written: int
    roles_written: int
    resolved_item_ids: list[str]
    affected: list[AffectedSectionResponse]
    edges: list[ReconciliationEdgeResponse]
    roles: list[ReconciliationRoleResponse]

    @classmethod
    def of(cls, report: Any) -> "ReconciliationReportResponse":
        return cls(
            project_id=str(report.project_id),
            replayed=report.replayed,
            event=ReconciliationEventResponse.of(report.event),
            edges_written=report.edges_written,
            roles_written=report.roles_written,
            resolved_item_ids=[str(item_id) for item_id in report.resolved_item_ids],
            affected=[
                AffectedSectionResponse(
                    domain=section.domain,
                    item_ids=[str(item_id) for item_id in section.item_ids],
                    reasons=list(section.reasons),
                )
                for section in report.affected
            ],
            edges=[
                ReconciliationEdgeResponse(
                    source_id=str(edge.source_id),
                    target_id=str(edge.target_id),
                    type=edge.type.value,
                    reason=edge.reason,
                )
                for edge in report.graph.edges
            ],
            roles=[
                ReconciliationRoleResponse(knowledge_item_id=str(item_id), role=role.value)
                for item_id, role in report.graph.roles
            ],
        )


class NeighborhoodNeighborResponse(BaseModel):
    knowledge_item_id: str
    score: float
    relation: str | None = None


class NeighborhoodResponse(BaseModel):
    knowledge_item_id: str
    neighbors: list[NeighborhoodNeighborResponse]
    measure: str
    """How the neighbourhood was found: ``semantic``, ``lexical`` or ``none``.

    Carried because an empty list means two different things. ``none`` says
    this deployment holds no vector for the item and stem coverage found
    nothing either — a fact about the deployment. ``semantic`` or ``lexical``
    with an empty list says nothing is related — a fact about the project.
    """

    @classmethod
    def of(cls, item_id: str, neighborhood: Any) -> "NeighborhoodResponse":
        return cls(
            knowledge_item_id=item_id,
            measure=neighborhood.measure.value,
            neighbors=[
                NeighborhoodNeighborResponse(
                    knowledge_item_id=str(neighbor.item_id),
                    score=neighbor.score,
                    relation=neighbor.relation,
                )
                for neighbor in neighborhood.neighbors
            ],
        )
