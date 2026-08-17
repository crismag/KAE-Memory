"""Synthesized model and human attention, over HTTP (ADR-0007).

Extracted knowledge stays on the existing knowledge routes. These routes are
the other two layers: the current project model, and the attention queue.
Writing extracted evidence never populates either.

**Transitional:** ``POST .../knowledge/{id}/confirm`` still confirms an
extracted row. That is not attention. Studio should move to this queue once
Phase 3 produces a model worth reviewing.
"""

from enum import StrEnum

from fastapi import APIRouter, Query, status

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.identifiers import (
    AttentionItemId,
    KnowledgeItemId,
    ProjectId,
    SynthesizedObjectId,
)
from kae_memory.domain.synthesis import (
    AttentionKind,
    AttentionStatus,
    ChangeTrigger,
    EvidenceBindingKind,
    EvidenceRole,
    SynthesizedObject,
)
from kae_memory.domain.synthesizers.rules import RuleOrigin

from ..dependencies import (
    ActorSynthesis,
    AssumptionSynthesis,
    ConstraintSynthesis,
    DecisionSynthesis,
    GoalSynthesis,
    Memory,
    Reconciliation,
    RequirementSynthesis,
    RuleSynthesis,
    Synthesis,
    UnknownSynthesis,
)
from ..errors import ApiError, not_found
from ..schemas import (
    AcceptanceCriterionResponse,
    ActorSynthesisReportResponse,
    AddAcceptanceCriterionRequest,
    AssumptionSynthesisReportResponse,
    AttentionItemResponse,
    AttributeRuleRequest,
    BindEvidenceRequest,
    ConstraintSynthesisReportResponse,
    CorrectSynthesizedObjectRequest,
    DecisionSynthesisReportResponse,
    EvidenceBindingResponse,
    EvidenceRoleResponse,
    GoalSynthesisReportResponse,
    NameRuleMechanismRequest,
    NeighborhoodResponse,
    PutAttentionRequest,
    PutSynthesizedObjectRequest,
    ReconciliationEventResponse,
    ReconciliationReportResponse,
    RecordChangeRequest,
    RequirementSynthesisReportResponse,
    ResolveAttentionRequest,
    ResponsibilityAssignmentResponse,
    RuleAttributionResponse,
    RuleEnforcementMechanismResponse,
    RuleSynthesisReportResponse,
    RunActorSynthesisRequest,
    RunAssumptionSynthesisRequest,
    RunConstraintSynthesisRequest,
    RunDecisionSynthesisRequest,
    RunGoalSynthesisRequest,
    RunReconciliationRequest,
    RunRequirementSynthesisRequest,
    RunRuleSynthesisRequest,
    RunUnknownSynthesisRequest,
    SetEvidenceRoleRequest,
    StoredConstraintEffectResponse,
    SynthesizedObjectResponse,
    UnknownSynthesisReportResponse,
)

router = APIRouter(prefix="/v1/projects/{project_id}", tags=["synthesis"])


def _project(project_id: str, memory: Memory) -> ProjectId:
    project = memory.get_project(ProjectId(project_id))
    if project is None:
        raise not_found("project", project_id)
    return project.id


def _supporting(synthesis: Synthesis, obj: SynthesizedObject) -> int:
    """How many observations one object rests on (`D-167`).

    A write answers it too, and answers it by reading: an update carries the
    bindings the object already had, so a response that assumed zero would tell
    a caller its object rests on nothing every time somebody corrected one.
    """

    return synthesis.supporting_counts([obj.id]).get(str(obj.id), 0)


def _parse[EnumT: StrEnum](enum_type: type[EnumT], value: str, field: str) -> EnumT:
    try:
        return enum_type(value)
    except ValueError as error:
        known = ", ".join(sorted(item.value for item in enum_type))
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_argument",
            f"unknown {field} {value!r}; valid values: {known}",
        ) from error


@router.get("/model", response_model=list[SynthesizedObjectResponse])
def list_model(
    project_id: str,
    memory: Memory,
    synthesis: Synthesis,
    domain: str | None = Query(default=None),
) -> list[SynthesizedObjectResponse]:
    """Return the synthesized project model. Empty until a synthesizer runs."""

    resolved = _project(project_id, memory)
    objects = synthesis.list_objects(resolved, domain)
    # One grouped count for the list, not one read per object (`D-167`).
    counts = synthesis.supporting_counts([obj.id for obj in objects])
    return [
        SynthesizedObjectResponse.of(obj, supporting_evidence=counts.get(str(obj.id), 0))
        for obj in objects
    ]


@router.post(
    "/model", response_model=SynthesizedObjectResponse, status_code=status.HTTP_201_CREATED
)
def put_model(
    project_id: str,
    body: PutSynthesizedObjectRequest,
    memory: Memory,
    synthesis: Synthesis,
) -> SynthesizedObjectResponse:
    """Create or update a working-model object. Idempotent by identity_key."""

    resolved = _project(project_id, memory)
    try:
        obj = synthesis.put_object(
            resolved, body.domain, body.identity_key, body.title, body.statement
        )
    except DomainInvariantError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid_argument", str(error)
        ) from error
    return SynthesizedObjectResponse.of(obj, supporting_evidence=_supporting(synthesis, obj))


@router.get("/model/{object_id}", response_model=SynthesizedObjectResponse)
def get_model_object(
    project_id: str, object_id: str, memory: Memory, synthesis: Synthesis
) -> SynthesizedObjectResponse:
    """Return one synthesized object and the evidence it is mapped to.

    Each evidence row carries what the extracted statement says, not only which
    row it is: a reader asking *what supports this* cannot be answered with a
    list of identifiers (`D-144`).
    """

    resolved = _project(project_id, memory)
    view = synthesis.get_object(resolved, SynthesizedObjectId(object_id))
    if view is None:
        raise not_found("synthesized_object", object_id)
    # Counted from the list this response carries, so the number and the
    # statements beneath it are the same read and cannot disagree.
    return SynthesizedObjectResponse.of(
        view.object, view.evidence, supporting_evidence=len(view.evidence)
    )


@router.post("/model/{object_id}/correct", response_model=SynthesizedObjectResponse)
def correct_model_object(
    project_id: str,
    object_id: str,
    body: CorrectSynthesizedObjectRequest,
    memory: Memory,
    synthesis: Synthesis,
) -> SynthesizedObjectResponse:
    """Record a person's wording as authoritative. Evidence is not deleted."""

    resolved = _project(project_id, memory)
    obj = synthesis.correct_object(
        resolved, SynthesizedObjectId(object_id), body.title, body.statement
    )
    return SynthesizedObjectResponse.of(obj, supporting_evidence=_supporting(synthesis, obj))


@router.post("/model/{object_id}/evidence", response_model=EvidenceBindingResponse)
def bind_model_evidence(
    project_id: str,
    object_id: str,
    body: BindEvidenceRequest,
    memory: Memory,
    synthesis: Synthesis,
) -> EvidenceBindingResponse:
    """Map a synthesized object onto an extracted row without deleting the row."""

    resolved = _project(project_id, memory)
    kind = _parse(EvidenceBindingKind, body.kind, "binding kind")
    binding = synthesis.bind_evidence(
        resolved,
        SynthesizedObjectId(object_id),
        KnowledgeItemId(body.knowledge_item_id),
        kind,
    )
    return EvidenceBindingResponse.of(binding)


@router.post(
    "/knowledge/{item_id}/evidence-role",
    response_model=EvidenceRoleResponse,
)
def set_evidence_role(
    project_id: str,
    item_id: str,
    body: SetEvidenceRoleRequest,
    memory: Memory,
    synthesis: Synthesis,
) -> EvidenceRoleResponse:
    """Set how an extracted row participates in reasoning. The row stays."""

    resolved = _project(project_id, memory)
    role = _parse(EvidenceRole, body.role, "evidence role")
    record = synthesis.set_evidence_role(resolved, KnowledgeItemId(item_id), role)
    return EvidenceRoleResponse.of(str(record.knowledge_item_id), record.role)


@router.get("/attention", response_model=list[AttentionItemResponse])
def list_attention(
    project_id: str,
    memory: Memory,
    synthesis: Synthesis,
    open_only: bool = Query(default=True),
    include_deferred: bool = Query(default=False),
) -> list[AttentionItemResponse]:
    """Return the human-attention queue. Unconfirmed extraction is not this list.

    Deferred items are owed and are not recommended, so they are out of the
    default read and `include_deferred` asks for them.
    """

    resolved = _project(project_id, memory)
    return [
        AttentionItemResponse.of(item)
        for item in synthesis.list_attention(
            resolved, open_only=open_only, include_deferred=include_deferred
        )
    ]


@router.post(
    "/attention",
    response_model=AttentionItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def put_attention(
    project_id: str, body: PutAttentionRequest, memory: Memory, synthesis: Synthesis
) -> AttentionItemResponse:
    """Create an attention item. Extraction must not call this."""

    resolved = _project(project_id, memory)
    kind = _parse(AttentionKind, body.kind, "attention kind")
    object_id = (
        None
        if body.synthesized_object_id is None
        else SynthesizedObjectId(body.synthesized_object_id)
    )
    item = synthesis.put_attention(
        resolved,
        kind,
        body.title,
        body.explanation,
        identity_key=body.identity_key,
        recommendation=body.recommendation,
        synthesized_object_id=object_id,
        priority=body.priority,
        actions=tuple(body.actions),
    )
    return AttentionItemResponse.of(item)


@router.post("/attention/{item_id}/resolve", response_model=AttentionItemResponse)
def resolve_attention(
    project_id: str,
    item_id: str,
    body: ResolveAttentionRequest,
    memory: Memory,
    synthesis: Synthesis,
) -> AttentionItemResponse:
    """Close an attention item. Resolved items leave the queue with provenance."""

    resolved = _project(project_id, memory)
    status_value = _parse(AttentionStatus, body.status, "attention status")
    item = synthesis.resolve_attention(resolved, AttentionItemId(item_id), status_value)
    return AttentionItemResponse.of(item)


@router.post("/attention/{item_id}/defer", response_model=AttentionItemResponse)
def defer_attention(
    project_id: str, item_id: str, memory: Memory, synthesis: Synthesis
) -> AttentionItemResponse:
    """Postpone an item. It stays owed; it stops being recommended."""

    resolved = _project(project_id, memory)
    item = synthesis.defer_attention(resolved, AttentionItemId(item_id))
    return AttentionItemResponse.of(item)


@router.post("/attention/{item_id}/reopen", response_model=AttentionItemResponse)
def reopen_attention(
    project_id: str, item_id: str, memory: Memory, synthesis: Synthesis
) -> AttentionItemResponse:
    """Return a deferred item to the live queue."""

    resolved = _project(project_id, memory)
    item = synthesis.reopen_attention(resolved, AttentionItemId(item_id))
    return AttentionItemResponse.of(item)


@router.post(
    "/reconciliation/events",
    response_model=ReconciliationEventResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_change(
    project_id: str, body: RecordChangeRequest, memory: Memory, synthesis: Synthesis
) -> ReconciliationEventResponse:
    """Record a change event, or return the one already stored under this key."""

    resolved = _project(project_id, memory)
    trigger = _parse(ChangeTrigger, body.trigger, "change trigger")
    event = synthesis.record_change(resolved, body.idempotency_key, trigger, body.summary)
    return ReconciliationEventResponse.of(event)


@router.get("/reconciliation/events", response_model=list[ReconciliationEventResponse])
def list_changes(
    project_id: str, memory: Memory, synthesis: Synthesis
) -> list[ReconciliationEventResponse]:
    """Return recorded reconciliation/change events."""

    resolved = _project(project_id, memory)
    return [ReconciliationEventResponse.of(event) for event in synthesis.list_changes(resolved)]


@router.post("/model/goals/runs", response_model=GoalSynthesisReportResponse)
def run_goal_synthesis(
    project_id: str,
    body: RunGoalSynthesisRequest,
    memory: Memory,
    goals: GoalSynthesis,
) -> GoalSynthesisReportResponse:
    """Cluster goal evidence into the project's goal model.

    Rerunning unchanged evidence writes nothing new: the same clusters produce
    the same identity keys, so `put_object` returns what is already there.

    Returns what was **withheld** as well as what was promoted. A synthesizer
    that reported only its output would make its own exclusions unauditable, and
    the first question anybody asks about a model this small is what is not in
    it.
    """

    resolved = _project(project_id, memory)
    return GoalSynthesisReportResponse.of(
        goals.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post("/model/unknowns/runs", response_model=UnknownSynthesisReportResponse)
def run_unknown_synthesis(
    project_id: str,
    body: RunUnknownSynthesisRequest,
    memory: Memory,
    unknowns: UnknownSynthesis,
) -> UnknownSynthesisReportResponse:
    """Turn current unknowns into themes, and the material few into attention.

    The only route that *produces* the attention queue. `GET /attention` reads
    it and `POST /attention` writes one item by hand; until this existed the
    queue could be filled only by calling the service in-process.

    Rerunning unchanged unknowns writes nothing new — themes carry the same
    identity keys, so `put_object` and `put_attention` return what is there.
    """

    resolved = _project(project_id, memory)
    return UnknownSynthesisReportResponse.of(
        unknowns.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post("/model/actors/runs", response_model=ActorSynthesisReportResponse)
def run_actor_synthesis(
    project_id: str,
    body: RunActorSynthesisRequest,
    memory: Memory,
    actors: ActorSynthesis,
) -> ActorSynthesisReportResponse:
    """Turn actor evidence into roles and the responsibilities they hold.

    The response separates the cast list from the model: every candidate is
    returned with the kind the **relation** gave it, so a reader can see that a
    human-shaped row holding nothing anywhere is a persona rather than a project
    role — doc 03 line 10, and the discriminator `D-119` refused to defer.

    Returns what was **refused** as well as what was written. Conflicts are the
    subjects two parties claim to answer for, and are also attention items.
    Downgrades are non-human claimants of Accountable, which are refused and
    reported here only: a governance rule that fired correctly is not somebody's
    interruption.

    Rerunning unchanged evidence writes nothing new — identity is the normalised
    statement, so `put_object` and `assign_responsibility` return what is there.
    """

    resolved = _project(project_id, memory)
    return ActorSynthesisReportResponse.of(
        actors.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post("/model/constraints/runs", response_model=ConstraintSynthesisReportResponse)
def run_constraint_synthesis(
    project_id: str,
    body: RunConstraintSynthesisRequest,
    memory: Memory,
    constraints: ConstraintSynthesis,
) -> ConstraintSynthesisReportResponse:
    """Turn constraint evidence into the project's boundaries and their effects.

    The boundaries themselves are read back through
    `GET /model?domain=constraint`. What the run adds beyond them is the
    relation doc 07 says a constraint is worth having for: `effects` are the
    open unknowns and assumptions an **accepted** boundary bears on, stored as
    rows a later reader can query.

    `proposed_effects` are what would follow from the boundaries nobody has
    accepted. They are computed, reported, and written nowhere (`D-126`) —
    applying them would silently close questions the project still has on the
    strength of a sentence somebody merely said.

    Nothing here raises attention. Doc 07 offers *Add exception* and *Change
    scope* beside *Accept*, so an effect is an argument about an item rather
    than a task, and an unaccepted boundary is not an interruption.

    Rerunning unchanged evidence writes nothing new — identity is the normalised
    statement for a boundary and the pair for an effect.
    """

    resolved = _project(project_id, memory)
    return ConstraintSynthesisReportResponse.of(
        constraints.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post("/model/requirements/runs", response_model=RequirementSynthesisReportResponse)
def run_requirement_synthesis(
    project_id: str,
    body: RunRequirementSynthesisRequest,
    memory: Memory,
    requirements: RequirementSynthesis,
) -> RequirementSynthesisReportResponse:
    """Turn requirement-like evidence into the project's requirement model.

    The requirements themselves are read back through
    `GET /model?domain=requirement`. What the run adds beyond them is doc 06's
    two separations: `reclassified` names the statements that are not
    requirements at all — principles, positioning, governance, capability
    headings — and `splits` names the compound ones in halves.

    Neither is applied. A reclassified statement is reported rather than
    deleted, because deleting it loses a real sentence, and a split is a
    proposal rather than a verdict — doc 06 says in those words that *web MVP
    with mobile later* must not be forced into binary Confirm/Reject.

    **`implementation_ready` is usually zero, and that is the finding.** A
    requirement is ready when it is observable, accepted, and carries at least
    one acceptance criterion, and KAE writes no criteria: one it generated would
    make the requirement ready by the act of synthesising it (`D-131`). Criteria
    arrive through `POST /model/requirements/{id}/criteria`, from a person.

    Nothing here raises attention — an unready requirement is a state of the
    model, not an interruption.

    Rerunning unchanged evidence writes nothing new; identity is the normalised
    statement.
    """

    resolved = _project(project_id, memory)
    return RequirementSynthesisReportResponse.of(
        requirements.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post("/model/rules/runs", response_model=RuleSynthesisReportResponse)
def run_rule_synthesis(
    project_id: str,
    body: RunRuleSynthesisRequest,
    memory: Memory,
    rules: RuleSynthesis,
) -> RuleSynthesisReportResponse:
    """Turn rule evidence into a rule model that says what each rule weighs.

    The rules themselves are read back through `GET /model?domain=rule`. What
    the run adds is the reading doc 04 asks for: the `family` a rule belongs to,
    the `authority` it carries, whether it is `active`, and whether a mechanism
    makes it a control.

    **`authority` comes from the origin and never from the wording.** *Must
    never* is the grammar of the sentence somebody wrote down, so a preference
    worded as an absolute stays a preference (`D-132`). The origin is attributed
    through `POST /model/rules/{id}/attribution`, by a person.

    **`unattributed` is usually every rule, and that is doc 04's complaint
    measured** — rules recorded without where they came from are interchangeable
    rows. Nothing here raises attention: one interrupt per unattributed rule is
    the review queue `ADR-0007` exists to remove, under a new name.

    Rerunning unchanged evidence writes nothing new — identity is the normalised
    statement.
    """

    resolved = _project(project_id, memory)
    return RuleSynthesisReportResponse.of(
        rules.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post(
    "/model/rules/{object_id}/attribution",
    response_model=RuleAttributionResponse,
    status_code=status.HTTP_201_CREATED,
)
def attribute_rule(
    project_id: str,
    object_id: str,
    body: AttributeRuleRequest,
    memory: Memory,
    rules: RuleSynthesis,
) -> RuleAttributionResponse:
    """Record where one rule came from.

    This is the **only** way an attribution is created. No synthesis path writes
    one, because an origin KAE attributed would make the rule active by the act
    of synthesising it (`D-132`).

    Naming `source_object_id` defers acceptance to that object: the rule governs
    only while the source is authoritative, because deriving a control from a
    proposal launders a proposal into a control (`D-126`). Omitting it makes
    this a direct assertion, which is active on the strength of the assertion.

    Idempotent by rule — a rule has one origin, so re-attributing replaces it.
    `404` if the object is not this project's, or is not a rule.
    """

    resolved = _project(project_id, memory)
    record = rules.record_attribution(
        resolved,
        SynthesizedObjectId(object_id),
        RuleOrigin(body.origin),
        None if body.source_object_id is None else SynthesizedObjectId(body.source_object_id),
    )
    return RuleAttributionResponse(
        attribution_id=str(record.id),
        rule_object_id=str(record.rule_object_id),
        origin=record.origin,
        source_object_id=(
            None if record.source_object_id is None else str(record.source_object_id)
        ),
    )


@router.get("/model/rules/attributions", response_model=list[RuleAttributionResponse])
def list_rule_attributions(
    project_id: str,
    memory: Memory,
    rules: RuleSynthesis,
    object_id: str | None = Query(default=None),
) -> list[RuleAttributionResponse]:
    """The project's rule attributions, optionally for one rule.

    Empty is the ordinary answer and doc 04's opening complaint: a project that
    never recorded where its rules came from cannot tell a law from a habit.
    """

    resolved = _project(project_id, memory)
    rule = None if object_id is None else SynthesizedObjectId(object_id)
    return [
        RuleAttributionResponse(
            attribution_id=str(record.id),
            rule_object_id=str(record.rule_object_id),
            origin=record.origin,
            source_object_id=(
                None if record.source_object_id is None else str(record.source_object_id)
            ),
        )
        for record in rules.list_attributions(resolved, rule)
    ]


@router.post(
    "/model/rules/{object_id}/mechanisms",
    response_model=RuleEnforcementMechanismResponse,
    status_code=status.HTTP_201_CREATED,
)
def name_rule_mechanism(
    project_id: str,
    object_id: str,
    body: NameRuleMechanismRequest,
    memory: Memory,
    rules: RuleSynthesis,
) -> RuleEnforcementMechanismResponse:
    """Record what enforces one rule.

    The **only** way a mechanism is named. A mechanism KAE named would make
    every rule an enforceable control by the act of synthesising it (`D-132`),
    so a rule is a control exactly when a person said what enforces it.

    Idempotent by wording. `404` if the object is not this project's rule.
    """

    resolved = _project(project_id, memory)
    record = rules.record_mechanism(resolved, SynthesizedObjectId(object_id), body.name)
    return RuleEnforcementMechanismResponse(
        mechanism_id=str(record.id),
        rule_object_id=str(record.rule_object_id),
        name=record.name,
    )


@router.get("/model/rules/mechanisms", response_model=list[RuleEnforcementMechanismResponse])
def list_rule_mechanisms(
    project_id: str,
    memory: Memory,
    rules: RuleSynthesis,
    object_id: str | None = Query(default=None),
) -> list[RuleEnforcementMechanismResponse]:
    """The mechanisms named in this project, optionally for one rule.

    Empty means the project has no enforceable controls — a finding about the
    project rather than about its rules.
    """

    resolved = _project(project_id, memory)
    rule = None if object_id is None else SynthesizedObjectId(object_id)
    return [
        RuleEnforcementMechanismResponse(
            mechanism_id=str(record.id),
            rule_object_id=str(record.rule_object_id),
            name=record.name,
        )
        for record in rules.list_mechanisms(resolved, rule)
    ]


@router.post("/model/decisions/runs", response_model=DecisionSynthesisReportResponse)
def run_decision_synthesis(
    project_id: str,
    body: RunDecisionSynthesisRequest,
    memory: Memory,
    decisions: DecisionSynthesis,
) -> DecisionSynthesisReportResponse:
    """Turn decision evidence into the project's proposals and settled choices.

    The decisions themselves are read back through `GET /model?domain=decision`,
    because a decision is stored as the synthesized object it is: its lifecycle
    and authority *are* its state, and a second collection holding the same
    answer is the pathology doc 08 names (`D-125`).

    What this response adds is the reading behind that state — the class, the
    effective scope and the basis, all derived from the wording rather than
    stored — together with what the run **refused**. `awaiting` is every
    decision nobody accepted and is deliberately not the attention queue: one
    interrupt per unaccepted decision would be the extracted-review queue under
    a new name. `session_scoped` is what was refused permanence, and `conflicts`
    is the one thing here that does raise attention.

    Rerunning unchanged evidence writes nothing new — identity is the normalised
    statement, so `put_object` returns what is there and a settled decision is
    already authoritative.
    """

    resolved = _project(project_id, memory)
    return DecisionSynthesisReportResponse.of(
        decisions.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.post("/model/assumptions/runs", response_model=AssumptionSynthesisReportResponse)
def run_assumption_synthesis(
    project_id: str,
    body: RunAssumptionSynthesisRequest,
    memory: Memory,
    assumptions: AssumptionSynthesis,
) -> AssumptionSynthesisReportResponse:
    """Turn assumption evidence into project beliefs and what each costs if wrong.

    The assumptions themselves are read back through `GET /model?domain=assumption`,
    because there is no assumption table: doc 05's lifecycle is the object's own
    `(lifecycle, authority)` pair, and the consequence domain is a pure function
    of the statement (`D-136`).

    What this response adds is the reading behind that state, and everything the
    run **separated**. `scaffolding` is the rows about reading the conversation
    rather than about the project — doc 05's own complaint — and they are sent
    by name because a silent filter is indistinguishable from an extractor that
    never produced them. **No evidence role is written for them**: the role store
    records no author and `noise` is sticky against reconciliation, so a run
    could never correct its own write.

    `needing_validation` is a state a reader sorts by and is deliberately not the
    attention queue. A run raises no attention items at all — one interrupt per
    unvalidated assumption is the review queue `ADR-0007` exists to remove.

    Rerunning unchanged evidence writes nothing new: identity is the normalised
    statement.
    """

    resolved = _project(project_id, memory)
    return AssumptionSynthesisReportResponse.of(
        assumptions.synthesize(resolved, idempotency_key=body.idempotency_key)
    )


@router.get(
    "/model/actors/responsibilities",
    response_model=list[ResponsibilityAssignmentResponse],
)
def list_responsibilities(
    project_id: str,
    memory: Memory,
    synthesis: Synthesis,
    subject_key: str | None = Query(default=None),
) -> list[ResponsibilityAssignmentResponse]:
    """The stored responsibility matrix, optionally one subject's column.

    Empty is a real answer and not an error: doc 03 keeps an unowned subject a
    legitimate finding rather than filling it with a guessed owner.
    """

    resolved = _project(project_id, memory)
    statement_of = {obj.id: obj.statement for obj in synthesis.list_objects(resolved)}
    return [
        ResponsibilityAssignmentResponse(
            role_statement=statement_of[record.role_object_id],
            subject_key=record.subject_key,
            letter=record.letter,
        )
        for record in synthesis.list_assignments(resolved, subject_key)
    ]


@router.post(
    "/model/requirements/{object_id}/criteria",
    response_model=AcceptanceCriterionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_acceptance_criterion(
    project_id: str,
    object_id: str,
    body: AddAcceptanceCriterionRequest,
    memory: Memory,
    requirements: RequirementSynthesis,
) -> AcceptanceCriterionResponse:
    """Record what a person says *done* looks like for one requirement.

    This is the **only** way a criterion is created. No synthesis path writes
    one, because a criterion KAE generated would make its requirement
    implementation-ready by the act of synthesising it — `ADR-0008`'s objection
    in one line (`D-131`). Doc 06 lists *Add acceptance criteria* among the
    human actions, and this is that action.

    Idempotent by wording: re-adding the same criterion updates it rather than
    stacking a second. `404` if the object is not this project's, or is not a
    requirement.
    """

    resolved = _project(project_id, memory)
    record = requirements.record_criterion(resolved, SynthesizedObjectId(object_id), body.statement)
    return AcceptanceCriterionResponse(
        criterion_id=str(record.id),
        requirement_object_id=str(record.requirement_object_id),
        statement=record.statement,
    )


@router.get("/model/requirements/criteria", response_model=list[AcceptanceCriterionResponse])
def list_acceptance_criteria(
    project_id: str,
    memory: Memory,
    requirements: RequirementSynthesis,
    object_id: str | None = Query(default=None),
) -> list[AcceptanceCriterionResponse]:
    """The project's acceptance criteria, optionally for one requirement.

    Empty is the ordinary answer and doc 06's finding: a requirement nobody has
    said *done* for is a candidate, not something to build to.
    """

    resolved = _project(project_id, memory)
    requirement = None if object_id is None else SynthesizedObjectId(object_id)
    return [
        AcceptanceCriterionResponse(
            criterion_id=str(record.id),
            requirement_object_id=str(record.requirement_object_id),
            statement=record.statement,
        )
        for record in requirements.list_criteria(resolved, requirement)
    ]


@router.get(
    "/model/constraints/effects",
    response_model=list[StoredConstraintEffectResponse],
)
def list_constraint_effects(
    project_id: str,
    memory: Memory,
    synthesis: Synthesis,
    knowledge_item_id: str | None = Query(default=None),
) -> list[StoredConstraintEffectResponse]:
    """What the project's accepted boundaries bear on, optionally for one item.

    Empty is a real answer: doc 07 calls a constraint nothing depends on an
    isolated duplicate sentence, and a project whose boundaries nobody has
    accepted yet imposes nothing (`D-126`).
    """

    resolved = _project(project_id, memory)
    item = None if knowledge_item_id is None else KnowledgeItemId(knowledge_item_id)
    statement_of = {obj.id: obj.statement for obj in synthesis.list_objects(resolved)}
    return [
        StoredConstraintEffectResponse(
            constraint_statement=statement_of[record.constraint_object_id],
            knowledge_item_id=str(record.knowledge_item_id),
            kind=record.kind,
            basis=record.basis,
        )
        for record in synthesis.list_constraint_effects(resolved, item)
    ]


@router.post("/reconciliation/runs", response_model=ReconciliationReportResponse)
def run_reconciliation(
    project_id: str,
    body: RunReconciliationRequest,
    memory: Memory,
    reconciliation: Reconciliation,
) -> ReconciliationReportResponse:
    """Run deterministic evidence-graph reconciliation. Does not mint a model."""

    resolved = _project(project_id, memory)
    item_ids = [KnowledgeItemId(item_id) for item_id in body.item_ids] or None
    report = reconciliation.reconcile(
        resolved, idempotency_key=body.idempotency_key, item_ids=item_ids
    )
    return ReconciliationReportResponse.of(report)


@router.get(
    "/reconciliation/neighborhoods/{item_id}",
    response_model=NeighborhoodResponse,
)
def get_neighborhood(
    project_id: str,
    item_id: str,
    memory: Memory,
    reconciliation: Reconciliation,
    limit: int = Query(default=12, ge=1, le=50),
) -> NeighborhoodResponse:
    """Return bounded related evidence for later LLM context. Not attention."""

    resolved = _project(project_id, memory)
    neighbors = reconciliation.neighborhood(resolved, KnowledgeItemId(item_id), limit=limit)
    return NeighborhoodResponse.of(item_id, neighbors)
