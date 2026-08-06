"""Tool implementations.

Each function delegates to an application service and returns a plain dict.
None of them touches persistence, builds SQL, or holds a connection string.

Two honesty rules run through the whole module, both from ADR-0018:

* A response never claims more than it can support. Search names the embedder
  in use and states plainly when its ranking is not semantic. Readiness names
  the scope it actually computed.
* A missing capability is reported as a structured gap, never fabricated.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from kae_memory.agents.provider import ranks_by_meaning
from kae_memory.application.assembly_service import (
    AssembledStatement,
    AssemblyPurpose,
    AssemblyService,
    ContextAssembly,
    describe_package,
)
from kae_memory.application.assumption_service import AssumptionNotFoundError, AssumptionService
from kae_memory.application.blueprint_service import Blueprint, BlueprintService
from kae_memory.application.clarification_service import ClarificationService, OpenQuestion
from kae_memory.application.classification_service import (
    ClassificationService,
    OperationalRecordNotFoundError,
)
from kae_memory.application.deliverable_service import DeliverableService
from kae_memory.application.ingestion_service import (
    IngestionPolicy,
    IngestionResult,
    IngestionService,
)
from kae_memory.application.memory_service import MemoryService
from kae_memory.application.module_service import ModuleNotFoundError, ModuleService
from kae_memory.application.preliminary_context_service import (
    PreliminaryContext,
    PreliminaryContextService,
    UnknownEntry,
)
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import (
    MAX_DISTANCE,
    RetrievalService,
    SearchHit,
    SearchMode,
)
from kae_memory.application.review_service import Finding, ReviewService
from kae_memory.domain.assumptions import (
    AssumptionOrigin,
    Consequence,
    InvalidAssumptionTransitionError,
    RevisitTrigger,
)
from kae_memory.domain.chunks import strip_metadata_prefix
from kae_memory.domain.dispositions import Disposition, DispositionError, settles
from kae_memory.domain.errors import (
    AlreadyAnsweredError,
    DomainInvariantError,
    InvalidLifecycleTransitionError,
    StaleVersionError,
)
from kae_memory.domain.errors import KnowledgeNotFoundError as DomainKnowledgeNotFound
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.generation_policy import from_mapping as resolve_generation_policy
from kae_memory.domain.identifiers import KnowledgeItemId, MessageId, ProjectId, SessionId
from kae_memory.domain.knowledge_review import RejectionReason
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.modules import CyclicModuleGraphError, DuplicateOwnershipError
from kae_memory.domain.observation import (
    ACTIVE_STATES,
    InvalidOperationalTransitionError,
    OperationalState,
    RetentionTier,
)
from kae_memory.domain.readiness import AreaResult, ReadinessSnapshot
from kae_memory.domain.relationships import ModuleRelation
from kae_memory.domain.relationships import resolve as resolve_relation
from kae_memory.domain.workspace import ActorType, MessageType, SessionType
from kae_memory.mcp import response_policy
from kae_memory.mcp.errors import (
    CapabilityUnavailableError,
    ConflictError,
    InvalidArgumentError,
    InvalidStateTransitionError,
    KnowledgeNotFoundError,
    ProjectNotFoundError,
    VersionConflictError,
)
from kae_memory.mcp.response_policy import PROFILES, ResponsePolicy, ResponseProfile


class ToolContext:
    """The application services a tool call may use.

    Constructed once per process. Holding the services here rather than
    reaching for a session factory inside a tool is what keeps the dependency
    direction one-way.
    """

    def __init__(
        self,
        memory: MemoryService,
        blueprint: BlueprintService,
        readiness: ReadinessService,
        review: ReviewService,
        retrieval: RetrievalService | None = None,
        embedder_name: str = "deterministic",
        response_policy: ResponsePolicy | None = None,
        clarification: ClarificationService | None = None,
        ingestion: IngestionService | None = None,
        assembly: AssemblyService | None = None,
        classification: ClassificationService | None = None,
        modules: ModuleService | None = None,
        deliverables: DeliverableService | None = None,
        assumptions: AssumptionService | None = None,
        preliminary: PreliminaryContextService | None = None,
    ) -> None:
        self.memory = memory
        self.blueprint = blueprint
        self.readiness = readiness
        self.review = review
        self.retrieval = retrieval
        self.clarification = clarification
        self.ingestion = ingestion
        self.assembly = assembly
        self.classification = classification
        self.modules = modules
        self.deliverables = deliverables
        self.assumptions = assumptions
        self.preliminary = preliminary
        self.embedder_name = embedder_name
        # The deployment default. A per-call override resolves against it in
        # `dispatch`, so a tool never reads configuration itself.
        self.response_policy = response_policy or PROFILES[ResponseProfile.REGULAR]

    @property
    def semantic_ranking(self) -> bool:
        """Whether the active embedder ranks by meaning.

        Asks the provider registry rather than comparing to a string, so
        adding a provider cannot accidentally advertise semantics it lacks: a
        new name is non-semantic until it is listed as one.
        """

        return ranks_by_meaning(self.embedder_name)


_UUID_FORM = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.I)
"""Whether a caller-supplied string is shaped like an id or like a key.

Shape, not a database lookup: a key that happened to look like a UUID would be
ambiguous no matter how it were resolved, and project keys are derived from
names (`KAE-Memory` -> `kae-memory`), so none can take this form.
"""


def _available_keys(context: ToolContext) -> str:
    """The keys this environment holds, for an error that helps rather than scolds.

    A caller who named the wrong project is one lookup away from the right one,
    and that lookup is the hop T25.2 exists to remove.
    """

    keys = sorted(project.key for project in context.memory.list_projects() if project.key)
    return ", ".join(keys[:10])


def resolve_project(context: ToolContext, project_id: str, project_key: str | None = None) -> Any:
    """Resolve a project from an id, a key, or a key passed as the id (T25.2).

    The UUID is the friction. An agent that must call `kae_list_projects`,
    read the response, and pick an id before it can ask anything will often
    skip the routing and answer from its own context instead — which is how a
    tool with correct isolation still produces an answer about the wrong
    project. A key removes the hop without adding state.

    Nothing here is an authorisation boundary. Resolution decides *which*
    project a caller named; it never decides whether they may read it.
    """

    named = (project_id or "").strip()
    keyed = (project_key or "").strip()

    if not named and not keyed:
        available = _available_keys(context)
        raise InvalidArgumentError(
            "project_id or project_key is required"
            + (f"; this environment holds: {available}" if available else "")
        )

    if named and _UUID_FORM.match(named):
        project = context.memory.get_project(ProjectId(named))
        if project is None:
            raise ProjectNotFoundError(f"no project with id {named!r}")
        if keyed and project.key != keyed:
            # Two arguments naming two projects is a caller bug, and picking
            # one would answer about a project they did not intend. Which of
            # the two was meant is not knowable from here.
            raise InvalidArgumentError(
                f"project_id {named!r} is {project.key!r}, not {keyed!r}; pass one or the other"
            )
        return project

    # A non-UUID `project_id` is a key. Refusing it would be technically
    # defensible and would send the caller back to the lookup hop this exists
    # to remove.
    key = named or keyed
    project = context.memory.find_project_by_key(key)
    if project is None:
        available = _available_keys(context)
        raise ProjectNotFoundError(
            f"no project with key {key!r}"
            + (f"; this environment holds: {available}" if available else "")
        )
    return project


def project_scope(project: Any, project_id: str, project_key: str | None = None) -> dict[str, Any]:
    """State which project answered, and how that was decided.

    A response resolved from a key must say so. The rule the response policy
    applies elsewhere holds here too: a response may reduce what it says, never
    what it admits.
    """

    named = (project_id or "").strip()
    resolved_from = (
        "project_id"
        if named and _UUID_FORM.match(named)
        else "project_key"
        if named or project_key
        else "unresolved"
    )
    return {
        "project_id": str(project.id),
        "project_key": project.key,
        "resolved_from": resolved_from,
    }


def kae_list_projects(
    context: ToolContext, limit: int | None = None, cursor: str | None = None
) -> dict[str, Any]:
    """Identify the projects this environment can read."""

    projects = context.memory.list_projects()
    return response_policy.paginate(
        [
            {
                "project_id": str(project.id),
                "name": project.name,
                "key": project.key,
                "status": project.status.value,
            }
            for project in projects
        ],
        limit=limit,
        cursor=cursor,
    )


def kae_create_project(
    context: ToolContext,
    name: str,
    key: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a project, or return the one that already has this key.

    ``name`` is the only thing a caller must supply. The key is derived from it
    — "KAE-Memory" becomes "kae-memory" — because a generated suffix is not
    something anyone can read back later.

    Idempotent by key. Creating twice returns the same project with
    ``created: false`` rather than an error, so an agent that loses its response
    can retry without first checking whether it succeeded.

    This is the one write that brings a subject into being rather than adding
    evidence about one, so it says plainly that the project starts empty. A
    caller that reads ``created: true`` and assumes knowledge is present would
    be planning against nothing.
    """

    if not name or not name.strip():
        raise InvalidArgumentError("name is required")
    if key is not None and not key.strip():
        raise InvalidArgumentError("key must not be blank; omit it to derive one from the name")

    project, created = context.memory.ensure_project(
        name.strip(), key.strip() if key else None, description
    )
    return {
        "project_id": str(project.id),
        "name": project.name,
        "key": project.key,
        "description": project.description,
        "status": project.status.value,
        "created": created,
        "knowledge_statements": 0 if created else None,
        "next_steps": [
            "Record what the project knows: kae_submit_observation.",
            "Confirmation is a human act, so submitted observations stay proposed "
            "until a person accepts them.",
        ]
        if created
        else ["This project already existed; nothing was changed."],
    }


_STATUS_LABELS = {
    "not_started": "Not started",
    "discovering": "In discovery",
    "draft_ready": "Requirements draft ready",
    "blocked": "Blocked",
    "blueprint_ready": "Implementation ready",
    "stale": "Stale — knowledge changed since the last calculation",
}
"""Human wording for each readiness status. The machine value ships alongside."""


def _readiness_explanation(snapshot: ReadinessSnapshot) -> dict[str, Any]:
    """Show the arithmetic behind the percentage.

    A bare number invites the reader to guess how it was reached. Every area
    already carries a weight and a credit, so the figure can be shown as the sum
    it is — which also makes it obvious which missing area costs the most.
    """

    applicable = [area for area in snapshot.areas if area.state.value != "not_applicable"]
    earned = sum(area.credit * area.weight for area in applicable)
    total = sum(area.weight for area in applicable)

    def described(area: AreaResult) -> dict[str, Any]:
        return {
            "area": area.key,
            "name": area.name,
            "state": area.state.value,
            "weight": area.weight,
            "credit": area.credit,
            # A partial area contributes and still owes: half credit for a
            # requirement area worth 2.0 leaves 1.0 on the table, which is
            # invisible if only earned weight is reported.
            "weight_outstanding": round(area.weight * (1.0 - area.credit), 2),
            "mandatory": area.mandatory,
            "confirmed_statements": area.confirmed_count,
            "awaiting_review": area.proposed_count,
            "confirmed_needed": area.minimum_confirmed,
        }

    return {
        "method": (
            "Credit-weighted share of applicable areas. An area is worth full "
            "credit when sufficient, half when partial, none when missing."
        ),
        "earned_weight": round(earned, 2),
        "applicable_weight": round(total, 2),
        # One list, keyed on ``state``. This previously rendered fifteen area
        # objects for ten areas across three lists — contributing, missing, and
        # incomplete — where incomplete duplicated missing entirely unless an
        # area was partial. Every row survives; the repetition does not.
        "areas": [described(a) for a in applicable],
    }


def _readiness_projection(snapshot: ReadinessSnapshot) -> dict[str, Any]:
    """Compute the percentage that resolving every missing mandatory area gives.

    Arithmetic over the same weights, not a forecast: it states what the score
    *would* be, and deliberately says nothing about how hard the work is or how
    long it takes.
    """

    applicable = [area for area in snapshot.areas if area.state.value != "not_applicable"]
    total = sum(area.weight for area in applicable)
    if not total:  # pragma: no cover - a template always defines applicable areas
        return {"percentage_if_mandatory_areas_resolved": snapshot.percentage, "requires": []}

    outstanding = [a for a in applicable if a.mandatory and a.credit < 1.0]
    projected = sum(area.weight * (1.0 if area.mandatory else area.credit) for area in applicable)
    return {
        "percentage_if_mandatory_areas_resolved": round(projected / total * 100),
        "requires": [{"area": a.key, "name": a.name, "weight": a.weight} for a in outstanding],
        "note": (
            "Arithmetic on the current weights, not an estimate of effort. "
            "Optional areas are left at their present state."
        ),
    }


def _knowledge_health(
    blueprint: Blueprint, findings: Sequence[Finding], snapshot: ReadinessSnapshot
) -> dict[str, Any]:
    """Count what the project knows, and how firmly it knows it.

    Counts come from the statements and findings themselves rather than from the
    knowledge revision, which is a version counter and not a quantity of
    anything.
    """

    labels: dict[str, int] = {}
    for section in blueprint.sections:
        for statement in section.statements:
            labels[statement.label.value] = labels.get(statement.label.value, 0) + 1

    def ids_for(kind: str) -> int:
        return sum(len(f.knowledge_item_ids) for f in findings if f.kind.value == kind)

    return {
        "confirmed_statements": blueprint.statement_count,
        "grounded": labels.get("grounded", 0),
        "derived": labels.get("derived", 0),
        "assumptions": labels.get("assumption", 0),
        "open_questions": len(blueprint.open_questions),
        "awaiting_review": ids_for("unconfirmed_knowledge"),
        "unclassified": ids_for("unclassified_knowledge"),
        "contradictions": sum(1 for f in findings if f.kind.value == "unresolved_contradiction"),
        "coverage_percentage": snapshot.percentage,
    }


def kae_get_project_briefing(
    context: ToolContext, project_id: str, tiers: Sequence[str] | None = None
) -> dict[str, Any]:
    """Return the current concise understanding of one project.

    Composes the blueprint with readiness, because the blueprint needs the
    readiness figures to state its own limits honestly.

    Everything here is counted or computed from confirmed knowledge. The
    response adds no narrative and no purpose statement: summarising a project
    in words nobody confirmed would put an unattributable claim in the one tool
    whose value is that it never makes them.

    ``tiers`` selects retention tiers (T24.4). The default is durable knowledge
    plus active operational state; evidence is never included, because personal
    commentary and session notes are not claims about the project. A caller who
    wants them asks for them, and gets them labelled.

    Tier filters and detail levels are orthogonal and must stay that way: a
    tier decides *which kinds of thing* are eligible, a detail level decides
    *how much* of what is eligible gets rendered. Collapsing them into one
    control would make "brief" and "durable only" the same word.
    """

    project = resolve_project(context, project_id)
    snapshot = context.readiness.latest(project.id) or context.readiness.calculate(project.id)
    blueprint = context.blueprint.generate(
        project.id,
        project.name,
        snapshot.percentage,
        snapshot.draft_eligible,
        snapshot.implementation_eligible,
        snapshot.missing_mandatory_areas,
    )
    findings = context.review.findings(project.id)
    by_area = {area.key: area.name for area in snapshot.areas}
    requested = _requested_tiers(tiers)

    payload: dict[str, Any] = {
        "project": {"project_id": str(project.id), "name": project.name, "key": project.key},
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "readiness": {
            "scope": "project",
            "percentage": snapshot.percentage,
            "status": snapshot.status.value,
            "status_label": _STATUS_LABELS.get(snapshot.status.value, snapshot.status.value),
            "draft_eligible": snapshot.draft_eligible,
            "implementation_eligible": snapshot.implementation_eligible,
            "ready_for": {
                "Requirements draft": snapshot.draft_eligible,
                "Implementation": snapshot.implementation_eligible,
            },
            "missing_mandatory_areas": [
                {"area": key, "name": by_area.get(key, key)}
                for key in snapshot.missing_mandatory_areas
            ],
            "explanation": _readiness_explanation(snapshot),
            "projection": _readiness_projection(snapshot),
        },
        "knowledge_health": _knowledge_health(blueprint, findings, snapshot),
        "sections": [
            {
                "area": section.area_key,
                "name": section.area_name,
                "statements": [
                    {
                        "id": s.id,
                        "text": s.text,
                        "label": s.label.value,
                        "kind": s.kind,
                        "knowledge_id": str(s.knowledge_item_id),
                    }
                    for s in section.statements
                ],
            }
            for section in blueprint.sections
        ],
        "statement_count": blueprint.statement_count,
        "open_questions": list(blueprint.open_questions),
        # Every finding, at its own severity, ordered most severe first. The
        # single authoritative rendering: severity, summary, and the recommended
        # action all live here and are not repeated elsewhere.
        "findings": [
            {
                "kind": f.kind.value,
                "severity": f.severity.value,
                "summary": f.summary,
                "recommended_action": f.recommended_action,
                "area": f.area_key,
                "knowledge_ids": [str(i) for i in f.knowledge_item_ids],
            }
            for f in findings
        ],
        # findings_by_severity and recommended_next_steps are gone. Both
        # restated values already carried by ``findings``, which is severity
        # ordered and holds both the summary and the recommended action.
        "complete": blueprint.complete,
        "unassigned_confirmed_count": blueprint.unassigned_confirmed_count,
    }
    payload["tiers"] = _tier_report(context, project, requested)
    return payload


DEFAULT_BRIEFING_TIERS: tuple[RetentionTier, ...] = (
    RetentionTier.DURABLE,
    RetentionTier.OPERATIONAL,
)
"""What a standard briefing shows (T24.4).

Evidence is excluded by default and not by accident. Personal commentary,
greetings, and session notes are preserved as evidence and stay searchable in
history; what they must not do is appear in a briefing as though they described
the project. Classification decides project *relevance*, not worth.
"""


def _requested_tiers(tiers: Sequence[str] | None) -> tuple[RetentionTier, ...]:
    """Resolve a caller's tier selection, refusing names that mean nothing."""

    if not tiers:
        return DEFAULT_BRIEFING_TIERS
    resolved: list[RetentionTier] = []
    for name in tiers:
        try:
            resolved.append(RetentionTier(str(name).strip().lower()))
        except ValueError:
            valid = ", ".join(tier.value for tier in RetentionTier)
            raise InvalidArgumentError(
                f"unknown retention tier {name!r}; expected one of {valid}"
            ) from None
    return tuple(dict.fromkeys(resolved))


def _tier_report(
    context: ToolContext, project: Any, requested: Sequence[RetentionTier]
) -> dict[str, Any]:
    """Describe which tiers this briefing carries, and what that left out.

    An excluded tier is named rather than silently absent. A briefing that
    simply omitted operational state would be indistinguishable from one whose
    project had none, and the caller would have no way to tell which.
    """

    included = [tier.value for tier in requested]
    excluded = [tier.value for tier in RetentionTier if tier not in requested]
    report: dict[str, Any] = {
        "included": included,
        "excluded": excluded,
        "note": (
            "Evidence-tier text is preserved and searchable; it is excluded here "
            "because it is not a claim about the project."
        ),
    }

    if context.classification is None:
        report["operational_state"] = {
            "available": False,
            "reason": "no classifier is configured for this server",
        }
        return report

    if RetentionTier.OPERATIONAL in requested:
        records = context.classification.operational_state(project.id)
        report["operational_state"] = [
            {
                "kind": record.kind,
                "subject": record.subject,
                "reported_status": record.reported_status,
                "current_status": record.current_status,
                "transition_type": record.transition_type,
                # The field that keeps a sentence from completing a milestone.
                "authority": record.authority,
                "state": record.state,
                "verification": record.verification,
                "effective_date": record.effective_date,
                "date_role": record.date_role,
            }
            for record in records
        ]
        report["operational_note"] = (
            "Reported, not verified. A milestone is never completed because a "
            "sentence said so; these are proposed transitions."
        )

    if RetentionTier.EVIDENCE in requested:
        report["evidence"] = [
            {
                "classification": row["classification"],
                "text": row["normalized_text"],
                "confidence": row["confidence"],
            }
            for row in context.classification.classifications(project.id, [RetentionTier.EVIDENCE])
        ]

    return report


def kae_record_assumption(
    context: ToolContext,
    project_id: str,
    subject: str,
    assumed_value: str,
    reason: str,
    consequence: str = "rework",
    confidence: float = 0.5,
    reversible: bool = True,
    revisit: str = "on_request",
    evidence: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Record what KAE proceeded on in place of information nobody supplied.

    An assumption is how "I do not know yet, choose something reasonable"
    becomes a durable record rather than a sentence in a conversation. It is
    **proposed**, whoever asked: acceptance is a person taking responsibility,
    and a caller that could record one already accepted would be recording a
    decision nobody made.

    Nothing here creates knowledge. The assumption service holds no reference
    to `MemoryService` and exposes no confirm, so the promotion FR-005 forbids
    is prevented by what this path cannot reach rather than by what it declines
    to do.
    """

    project = resolve_project(context, project_id)
    if context.assumptions is None:
        raise CapabilityUnavailableError(
            capability="assumptions",
            missing=["an assumption service is not configured for this server"],
        )
    try:
        recorded = context.assumptions.record(
            project.id,
            subject=subject,
            assumed_value=assumed_value,
            reason=reason,
            origin=AssumptionOrigin.KAE_RECOMMENDED_ACCEPTED
            if evidence
            else AssumptionOrigin.KAE_INFERRED,
            consequence=Consequence(consequence),
            confidence=confidence,
            reversible=reversible,
            revisit=RevisitTrigger(revisit),
            evidence=evidence,
        )
    except ValueError as error:
        raise InvalidArgumentError(str(error)) from error
    except DomainInvariantError as error:
        raise InvalidArgumentError(str(error)) from error

    return {
        "project_id": str(project.id),
        **_assumption_payload(recorded),
        "knowledge_changed": False,
        "note": (
            "Recorded as a proposed assumption. It is not knowledge and does not "
            "move readiness; a person accepts responsibility for it, or answers "
            "the question it stands in for."
        ),
    }


def kae_list_assumptions(
    context: ToolContext,
    project_id: str,
    active_only: bool = True,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List what this project is currently proceeding on without knowing."""

    project = resolve_project(context, project_id)
    if context.assumptions is None:
        raise CapabilityUnavailableError(
            capability="assumptions",
            missing=["an assumption service is not configured for this server"],
        )

    records = context.assumptions.list_for_project(project.id, active_only=active_only)
    page = response_policy.paginate(
        [_assumption_payload(record) for record in records], limit=limit, cursor=cursor
    )
    return {
        "project_id": str(project.id),
        **page,
        "material_count": sum(1 for record in records if record.material),
        "knowledge_changed": False,
        "note": (
            "Assumptions are not knowledge. A material one must be disclosed "
            "wherever the output it shaped is disclosed."
        ),
    }


def kae_accept_assumption(
    context: ToolContext,
    project_id: str,
    assumption_id: str,
    actor: str,
) -> dict[str, Any]:
    """Relay a person taking responsibility for proceeding on an assumption.

    Accepting is not confirming. It records that someone is willing to build on
    a guess, which is a weaker and more honest claim than believing it true, and
    the assumption stays revisitable.
    """

    project = resolve_project(context, project_id)
    if context.assumptions is None:
        raise CapabilityUnavailableError(
            capability="assumptions",
            missing=["an assumption service is not configured for this server"],
        )
    try:
        accepted = context.assumptions.accept(project.id, assumption_id, actor)
    except AssumptionNotFoundError as error:
        raise KnowledgeNotFoundError(str(error)) from error
    except InvalidAssumptionTransitionError as error:
        raise InvalidStateTransitionError(str(error)) from error
    except ValueError as error:
        raise InvalidArgumentError(str(error)) from error

    return {
        "project_id": str(project.id),
        **_assumption_payload(accepted),
        "knowledge_changed": False,
        "note": (
            "Accepted, not confirmed. A person took responsibility for proceeding "
            "on this; it did not become project knowledge."
        ),
    }


def _assumption_payload(assumption: Any) -> dict[str, Any]:
    return {
        "assumption_id": str(assumption.id),
        "subject": assumption.subject,
        "assumed_value": assumption.assumed_value,
        "reason": assumption.reason,
        "origin": assumption.origin.value,
        "consequence": assumption.consequence.value,
        "material": assumption.material,
        "confidence": round(assumption.confidence, 2),
        "reversible": assumption.reversible,
        "revisit": assumption.revisit.value,
        "state": assumption.state.value,
        "accepted_by": assumption.accepted_by,
        "evidence": list(assumption.evidence),
    }


def kae_define_module(
    context: ToolContext,
    project_id: str,
    key: str,
    name: str,
    summary: str = "",
) -> dict[str, Any]:
    """Register a module. Idempotent by key.

    A module is *proposed* when defined. Nothing here confirms that it belongs
    in the system — that is a person's call, the same as for knowledge, and for
    the same reason: an agent that could confirm its own proposals would make
    the review model decorative.
    """

    project = resolve_project(context, project_id)
    if context.modules is None:
        raise CapabilityUnavailableError(
            capability="modules",
            missing=["a module service is not configured for this server"],
        )
    if not key or not key.strip() or not name or not name.strip():
        raise InvalidArgumentError("a module needs a key and a name")

    module = context.modules.define(project.id, key, name, summary)
    return {
        "project_id": str(project.id),
        "module": {
            "key": module.key,
            "name": module.name,
            "summary": module.summary,
            "status": module.status.value,
        },
        "knowledge_changed": False,
        "note": (
            "Recorded as a proposed module. A person confirms what becomes part "
            "of the system definition."
        ),
    }


def kae_relate_modules(
    context: ToolContext,
    project_id: str,
    source: str,
    relation: str,
    target: str | None = None,
    knowledge_id: str | None = None,
) -> dict[str, Any]:
    """Record one structural edge between modules, or from a module to knowledge.

    The vocabulary is fixed (ADR-0025) and a retired name raises with what
    replaced it. Cycles in `depends_on` and `owns` are refused here rather than
    detected later: a graph checked only when traversed stores state it cannot
    answer from.
    """

    project = resolve_project(context, project_id)
    if context.modules is None:
        raise CapabilityUnavailableError(
            capability="modules",
            missing=["a module service is not configured for this server"],
        )

    try:
        resolved = resolve_relation(relation)
    except DomainInvariantError as error:
        raise InvalidArgumentError(str(error)) from error
    if not isinstance(resolved, ModuleRelation):
        raise InvalidArgumentError(
            f"{relation!r} relates two statements, not two modules. Structural "
            f"relations are: {', '.join(r.value for r in ModuleRelation)}"
        )

    try:
        edge = context.modules.relate(project.id, source, resolved, target, knowledge_id)
    except ModuleNotFoundError as error:
        raise KnowledgeNotFoundError(str(error)) from error
    except (CyclicModuleGraphError, DuplicateOwnershipError) as error:
        raise InvalidStateTransitionError(str(error)) from error
    except DomainInvariantError as error:
        raise InvalidArgumentError(str(error)) from error

    return {
        "project_id": str(project.id),
        "source": source,
        "relation": edge.relation.value,
        "target": target or knowledge_id,
        "knowledge_changed": False,
    }


def kae_get_module_graph(context: ToolContext, project_id: str) -> dict[str, Any]:
    """Return every module and the order they can be built in.

    Build order is the question a dependency graph exists to answer. Ties break
    by identifier so the answer is stable — an order that varies between calls
    cannot be compared to the previous one, which is most of what it is for.
    """

    project = resolve_project(context, project_id)
    if context.modules is None:
        raise CapabilityUnavailableError(
            capability="modules",
            missing=["a module service is not configured for this server"],
        )

    modules = context.modules.list_modules(project.id)
    ordered = context.modules.build_order(project.id)
    return {
        "project_id": str(project.id),
        "modules": [{"key": m.key, "name": m.name, "status": m.status.value} for m in modules],
        "build_order": [m.key for m in ordered],
        "note": (
            "Build order follows depends_on only. A module with no dependencies "
            "may still need knowledge that is not yet confirmed."
        ),
    }


def kae_record_deliverable(
    context: ToolContext,
    project_id: str,
    purpose: str = "implementation",
    include_proposed: bool = False,
    recorded_by: str | None = None,
) -> dict[str, Any]:
    """Record what an assembly produced, as a durable deliverable (N20).

    Assembling produces a description and forgets it: `package_id` is fresh per
    call, because an assembly is a computation. This is the other thing — a
    durable record that this project produced this output at this revision.

    Idempotent by content. Recording the same output twice returns the same
    deliverable, because two identical outputs are one deliverable recorded
    twice; a second id would report a change the project did not make.

    **Nothing is rendered, stored, or published.** The record holds the
    manifest, the hashes, and what each artifact would contain. Writing bytes
    to a destination belongs to whoever owns the destination.
    """

    project = resolve_project(context, project_id)
    if context.deliverables is None or context.assembly is None:
        raise CapabilityUnavailableError(
            capability="deliverables",
            missing=["a deliverable or assembly service is not configured for this server"],
        )
    try:
        selected = AssemblyPurpose(purpose)
    except ValueError:
        valid = ", ".join(p.value for p in AssemblyPurpose)
        raise InvalidArgumentError(
            f"unknown purpose {purpose!r}; expected one of {valid}"
        ) from None

    assembly = context.assembly.assemble(project.id, selected, include_proposed=include_proposed)
    deliverable, created = context.deliverables.record(project.id, assembly, recorded_by)
    payload = _deliverable_payload(deliverable, context.readiness.knowledge_revision(project.id))
    payload["recorded"] = created
    payload["idempotent_replay"] = not created
    payload["note"] = (
        "Recorded as a durable output. Nothing was rendered, stored, or published: "
        "this is the record that an output existed, not the output itself."
    )
    return payload


def kae_list_deliverables(
    context: ToolContext,
    project_id: str,
    states: Sequence[str] | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List a project's recorded deliverables, newest first."""

    project = resolve_project(context, project_id)
    if context.deliverables is None:
        raise CapabilityUnavailableError(
            capability="deliverables",
            missing=["a deliverable service is not configured for this server"],
        )

    revision = context.readiness.knowledge_revision(project.id)
    records = context.deliverables.list_for_project(project.id, states)
    page = response_policy.paginate(
        [_deliverable_payload(record, revision) for record in records],
        limit=limit,
        cursor=cursor,
    )
    return {
        "project_id": str(project.id),
        **page,
        "knowledge_revision": revision,
        "note": (
            "A stale deliverable is one recorded before the project moved. It is "
            "still what was produced; it is no longer what the project now says."
        ),
    }


def _deliverable_payload(deliverable: Any, current_revision: int) -> dict[str, Any]:
    """Render one deliverable, including whether the project has moved past it."""

    return {
        "deliverable_id": str(deliverable.id),
        "purpose": deliverable.purpose,
        "scope": deliverable.scope,
        "module": deliverable.module_key,
        "state": deliverable.state.value,
        "knowledge_revision": deliverable.knowledge_revision,
        "content_hash": deliverable.content_hash,
        # Derived, never stored. A stored staleness flag is true until something
        # remembers to update it, and the write most likely to forget is the one
        # that made it false.
        "stale": deliverable.is_stale_against(current_revision),
        "artifacts": [
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
        "source_knowledge": list(deliverable.source_knowledge),
        "recorded_by": deliverable.recorded_by,
        "superseded_by": deliverable.superseded_by,
        "rendered": False,
        "published": False,
        # N20.1. Eligibility says the inputs exist to attempt reproduction; the
        # artifact hashes remain the only thing that can say the attempt
        # succeeded.
        "publication_eligible": deliverable.publication_eligible,
        "ineligibility_reason": deliverable.ineligibility_reason,
        "statement_pins": [
            {"knowledge_id": pin.knowledge_id, "version": pin.version}
            for pin in deliverable.statement_pins
        ],
        "render_inputs": (
            deliverable.render_inputs.as_dict() if deliverable.render_inputs else None
        ),
        # N20.2. What this rested on, not only what it rendered. Statement pins
        # make a package reproduce the same bytes; this makes it reproduce the
        # same claim, which is weaker than the bytes look once the questions it
        # was generated under have been answered.
        "provisional_context": (
            deliverable.provisional_context.as_dict() if deliverable.provisional_context else None
        ),
        "rested_on_uncertainty": (
            deliverable.provisional_context.rested_on_uncertainty
            if deliverable.provisional_context
            else None
        ),
        # Separate from publication_eligible on purpose. A pre-N20.2 record can
        # still be re-rendered byte for byte; what it cannot do is say how much
        # of itself was guesswork, and refusing to publish it would withdraw a
        # capability it genuinely has.
        "reproduces_uncertainty": deliverable.reproduces_uncertainty,
        "uncertainty_gap_reason": deliverable.uncertainty_gap_reason,
        # What this was produced *for*, alongside what was produced (N38).
        # Absent on deliverables recorded before qualification existed, and not
        # invented for them: describing a package nobody described would be a
        # claim rather than a record.
        "qualification": deliverable.qualification,
    }


def _project_knowledge_named(context: ToolContext, project: Any, module: str) -> dict[str, Any]:
    """Report project knowledge whose wording matches a requested module name.

    This is offered *instead of* module context, never as it. Matching the words
    "approval workflow" tells you a statement mentions those words; it does not
    tell you the statement belongs to an approval module, because nothing in
    this version records module membership. The caveat travels with the data so
    a reader cannot pick up the statements without it.
    """

    offer: dict[str, Any] = {
        "scope": "project",
        "module_scope_available": False,
        "match_type": "name_terms",
        "caveat": (
            "These statements match the wording of the requested name. That is a "
            "term match, not module membership — no record of which knowledge "
            "belongs to this module exists in this version."
        ),
    }
    if context.retrieval is None:
        offer["available"] = False
        offer["reason"] = "retrieval_service_not_configured"
        offer["statements"] = []
        offer["count"] = 0
        return offer

    status = context.retrieval.indexing_status(project.id)
    if status.unindexed:
        # Knowledge exists and none of it is reachable. Returning an empty list
        # here would read as "this project knows nothing about that", which is a
        # different and wrong answer.
        offer["available"] = False
        offer["reason"] = "project_knowledge_not_indexed"
        offer["knowledge_items"] = status.knowledge_items
        offer["searchable_chunks"] = status.chunks
        offer["detail"] = (
            "This project holds knowledge that has never been indexed, so no "
            "search can reach it. The empty result below reflects the index, "
            "not the project."
        )
        offer["statements"] = []
        offer["count"] = 0
        return offer

    hits = context.retrieval.find(project.id, module, limit=20)
    offer["available"] = True
    offer["statements"] = [
        {
            "knowledge_id": str(hit.knowledge_id),
            "kind": hit.kind.value,
            "text": strip_metadata_prefix(hit.text),
            "state": hit.lifecycle.value,
            "authoritative": hit.authoritative,
            "matched_terms": list(hit.matched_terms),
        }
        for hit in hits
    ]
    offer["count"] = len(hits)
    return offer


def kae_get_module_context(context: ToolContext, project_id: str, module: str) -> dict[str, Any]:
    """Return what one module needs to be implemented without reading the project.

    The capability this reported as unavailable through T1-T25 (N19). What made
    it unavailable was never the assembly — it was that modules had no model, no
    edges, and no traversal. N16 settled the vocabulary, N17 built the model,
    N18 the traversal; this composes them.

    A module that is not registered still gets an honest answer rather than an
    invented one, and the two are distinguishable: an unknown module names the
    modules that exist, where an unavailable capability named what was missing.
    """

    project = resolve_project(context, project_id)
    if not module or not module.strip():
        raise InvalidArgumentError("module is required")

    if context.modules is not None:
        try:
            neighbourhood = context.modules.neighbourhood(project.id, module.strip())
        except ModuleNotFoundError:
            registered = [m.key for m in context.modules.list_modules(project.id)]
            if registered:
                # A wrong name and an unmodelled project are different answers.
                # Falling back to a term match here would hand back statements
                # that merely mention the word, in a project that can say better.
                raise KnowledgeNotFoundError(
                    f"no module {module.strip()!r} in this project; "
                    f"registered: {', '.join(registered)}"
                ) from None
        else:
            return _module_context_payload(context, project, neighbourhood)

    # No modules registered, or no module service configured. Module scope is
    # genuinely unavailable *for this project*, and the original gap payload —
    # which named its subject, offered a labelled substitute, and refused to
    # promise a workaround — is still the right answer. What changed is that a
    # project which has modelled its modules no longer reaches it.
    raise CapabilityUnavailableError(
        capability="module context",
        missing=["no modules are registered in this project"],
        use_instead=[
            "kae_define_module to register one, then kae_relate_modules to place it",
            "kae_get_project_briefing for current project understanding",
            "kae_search_knowledge to locate knowledge related to this module",
        ],
        subject={
            "module": module,
            "project": project.name,
            "status": "not_registered",
            "detail": (
                "No module of this name is recorded. Modules are modelled in this "
                "version, so this name is lookable — there is simply nothing to "
                "look up until one is registered."
            ),
        },
        available_now=_project_knowledge_named(context, project, module),
        next_steps=[
            "Register the module and relate it to the knowledge it satisfies.",
            "Read the project briefing for the confirmed knowledge that does exist.",
            "Resolve the open decisions that would block this module's requirements.",
        ],
    )


def _module_context_payload(
    context: ToolContext, project: Any, neighbourhood: Any
) -> dict[str, Any]:
    """Render one module's bounded context.

    Dependencies arrive as **stubs** — key, name, summary — rather than as their
    full context. An implementer needs to know what a dependency offers, not how
    it is built; expanding them would reproduce the whole project one edge at a
    time, which is the thing a module scope exists to prevent.
    """

    module = neighbourhood.module
    statements = _module_statements(context, project, neighbourhood)

    return {
        "project_id": str(project.id),
        "scope": "module",
        "module_scope_available": True,
        "module": {
            "key": module.key,
            "name": module.name,
            "summary": module.summary,
            "status": module.status.value,
        },
        "depends_on": [_stub(m) for m in neighbourhood.depends_on],
        "dependents": [_stub(m) for m in neighbourhood.dependents],
        "exposes": [_stub(m) for m in neighbourhood.exposes],
        "consumes": [_stub(m) for m in neighbourhood.consumes],
        "owns": [_stub(m) for m in neighbourhood.owns],
        "owned_by": _stub(neighbourhood.owned_by) if neighbourhood.owned_by else None,
        "statements": statements,
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "note": (
            "Dependencies are summarised, not expanded. What a dependency offers is "
            "what an implementer needs; how it is built is its own context."
        ),
        "guidance": [
            "Statements labelled proposed are candidates, not decisions.",
            "This is one module's scope. Knowledge outside it was not read and is "
            "not implied to be absent.",
        ],
    }


def _stub(module: Any) -> dict[str, Any]:
    return {"key": module.key, "name": module.name, "summary": module.summary}


def _module_statements(
    context: ToolContext, project: Any, neighbourhood: Any
) -> list[dict[str, Any]]:
    """The statements this module satisfies or is verified by.

    Resolved from edges rather than from a term match. The difference is the
    whole point of N17: "these statements mention the word approval" and "this
    module satisfies these requirements" are different claims, and the old
    behaviour could only make the first.
    """

    wanted = {
        **{knowledge_id: "satisfies" for knowledge_id in neighbourhood.satisfies},
        **{knowledge_id: "verified_by" for knowledge_id in neighbourhood.verified_by},
    }
    if not wanted:
        return []

    items = context.memory.retrieve_knowledge(project.id, lifecycle=None)
    resolved: list[dict[str, Any]] = []
    for item in items:
        relation = wanted.get(str(item.id))
        if relation is None:
            continue
        resolved.append(
            {
                "knowledge_id": str(item.id),
                "relation": relation,
                "kind": item.kind.value if hasattr(item.kind, "value") else str(item.kind),
                "text": item.current_version.content,
                "lifecycle": item.lifecycle.value,
                "label": "confirmed" if item.lifecycle is LifecycleState.VALIDATED else "proposed",
            }
        )

    missing = sorted(set(wanted) - {row["knowledge_id"] for row in resolved})
    if missing:
        # An edge pointing at a statement that no longer exists is a real state
        # and reporting it as an empty list would hide it.
        resolved.append(
            {
                "knowledge_id": None,
                "relation": "unresolved_edges",
                "text": f"{len(missing)} linked statements could not be resolved",
                "lifecycle": "unknown",
                "label": "unresolved",
            }
        )
    return resolved


_SEARCH_MODES = ("auto", "lexical", "semantic")

_STRONG_DISTANCE = 0.35
"""Below this, a vector hit is close enough to call a strong match."""


def _relevance(hit: SearchHit) -> str:
    """Describe how well a hit answered the query, in words a caller can act on.

    A cosine distance is a fact about two vectors, not an answer to "should I
    read this". Callers were reading raw distances as confidence and getting it
    wrong, because the meaningful range differs per model.
    """

    if hit.mode is SearchMode.LEXICAL:
        return "strong" if hit.coverage and hit.coverage >= 1.0 else "partial"
    if hit.distance is None:  # pragma: no cover - semantic hits always carry one
        return "unknown"
    return "strong" if hit.distance <= _STRONG_DISTANCE else "moderate"


def kae_search_knowledge(
    context: ToolContext,
    project_id: str,
    query: str,
    limit: int = 8,
    kinds: list[str] | None = None,
    mode: str = "auto",
    diagnostics: bool = False,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Search project knowledge without loading the whole project.

    Two retrieval paths, and the response always names which one ran. Lexical
    matching answers term queries with no model involved; semantic matching
    answers conceptual ones and needs a real embedder. ``auto`` picks lexical
    while the active embedder cannot rank meaning, because a hash-derived
    ordering presented as relevance is worse than no ranking at all.

    Vector internals stay out of the normal result. ``diagnostics=True`` returns
    them for development and for anyone who wants the underlying evidence.
    """

    project = resolve_project(context, project_id)
    if not query or not query.strip():
        raise InvalidArgumentError("query is required")
    if limit < 1 or limit > 50:
        raise InvalidArgumentError("limit must be between 1 and 50")
    if mode not in _SEARCH_MODES:
        raise InvalidArgumentError(f"mode must be one of: {', '.join(_SEARCH_MODES)}")
    if context.retrieval is None:
        raise CapabilityUnavailableError(
            capability="knowledge search",
            missing=["a retrieval service is not configured in this environment"],
            use_instead=["kae_get_project_briefing"],
        )

    parsed_kinds = None
    if kinds:
        valid = {k.value for k in KnowledgeKind}
        unknown = [k for k in kinds if k not in valid]
        if unknown:
            raise InvalidArgumentError(
                f"unknown knowledge kinds: {', '.join(sorted(unknown))}. "
                f"Valid kinds: {', '.join(sorted(valid))}"
            )
        parsed_kinds = [KnowledgeKind(k) for k in kinds]

    warnings: list[str] = []
    resolved = mode
    if mode == "auto":
        resolved = "semantic" if context.semantic_ranking else "lexical"
        if not context.semantic_ranking:
            warnings.append(
                "Semantic ranking is unavailable because no semantic embedding model "
                "is configured. Matched on query terms instead, so conceptual queries "
                "that share no wording with the stored text will not be found."
            )
    elif mode == "semantic" and not context.semantic_ranking:
        warnings.append(
            "Semantic mode was requested but the active embedder is hash-derived. "
            "The ordering below carries no meaning and must not be read as relevance."
        )

    if resolved == "lexical":
        hits = context.retrieval.find(project.id, query, limit=limit, kinds=parsed_kinds)
    else:
        hits = context.retrieval.search(project.id, query, limit=limit, kinds=parsed_kinds)

    status = context.retrieval.indexing_status(project.id)
    if not hits and status.unindexed:
        # An unindexed project cannot answer any query. Saying "nothing matched"
        # would report a fact about the index as a fact about the project.
        warnings.append(
            f"This project holds {status.knowledge_items} knowledge item(s) and "
            "none are indexed, so no search can reach them. This empty result "
            "reflects the index, not the project."
        )
    elif not hits:
        warnings.append(
            "Nothing matched. This is a result, not a failure: no stored knowledge "
            "met the relevance threshold for this query."
        )
    if status.embedding_pending and resolved == "semantic":
        warnings.append(
            f"{status.embedding_pending} chunk(s) are awaiting an embedding and "
            "cannot be reached by semantic search yet."
        )

    page = response_policy.paginate(
        [
            {
                "knowledge_id": str(hit.knowledge_id),
                "kind": hit.kind.value,
                "text": strip_metadata_prefix(hit.text),
                "state": hit.lifecycle.value,
                "authoritative": hit.authoritative,
                "relevance": _relevance(hit),
                "matched_terms": list(hit.matched_terms),
                "why": hit.why,
            }
            for hit in hits
        ],
        limit=None,
        cursor=cursor,
    )

    payload: dict[str, Any] = {
        "query": query,
        "search_mode": resolved,
        **page,
        "semantic_search_available": context.semantic_ranking,
        "ranking": {
            "lexical": resolved == "lexical",
            "semantic": resolved == "semantic",
            "metadata_filtered": parsed_kinds is not None,
        },
        # `count` split in two (ADR-0021 rule 5): one number could not say
        # whether three hits came from three statements or three spans of one.
        "matched_chunks": len(hits),
        "matched_knowledge_items": len({str(hit.knowledge_id) for hit in hits}),
        "indexing": {
            "knowledge_items": status.knowledge_items,
            "searchable_chunks": status.chunks,
            "embedded_chunks": status.embedded_chunks,
            "lexically_searchable": status.lexically_searchable,
        },
        "warnings": warnings,
    }

    if diagnostics:
        payload["diagnostics"] = {
            "embedder": context.embedder_name,
            "semantic_relevance": context.semantic_ranking,
            "max_distance": MAX_DISTANCE if resolved == "semantic" else None,
            "hits": [
                {
                    "knowledge_id": str(hit.knowledge_id),
                    "chunk_id": str(hit.chunk_id),
                    "distance": hit.distance,
                    "coverage": hit.coverage,
                    "embedded_text": hit.text,
                }
                for hit in hits
            ],
        }
    return payload


def kae_get_open_decisions(
    context: ToolContext,
    project_id: str,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return what is unresolved and could affect an agent's work.

    Paginated, and ``total`` counts everything unresolved rather than the page.
    A caller that read twenty of forty open decisions and believed it had seen
    them all would plan around a project it has only partly understood.
    """

    project = resolve_project(context, project_id)
    everything = context.memory.retrieve_knowledge(project.id, lifecycle=None)
    unknowns = tuple(item for item in everything if item.kind == KnowledgeKind.UNKNOWN.value)
    findings = context.review.findings(project.id)
    blocking = [
        f
        for f in findings
        if f.kind.value in {"open_question", "unresolved_contradiction", "open_blocker"}
    ]

    return {
        "project_id": str(project.id),
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        **response_policy.paginate(
            [
                {
                    "knowledge_id": str(item.id),
                    "text": item.current_version.content,
                    "lifecycle": item.lifecycle.value,
                    "source": "open_knowledge",
                }
                for item in unknowns
            ]
            + [
                {
                    "kind": f.kind.value,
                    "severity": f.severity.value,
                    "summary": f.summary,
                    "source": "finding",
                }
                for f in blocking
            ],
            limit=limit,
            cursor=cursor,
        ),
        "guidance": (
            "These are unresolved. Do not choose an answer on the project's "
            "behalf; if one blocks the work, report it and stop."
        ),
    }


def kae_get_readiness(context: ToolContext, project_id: str) -> dict[str, Any]:
    """Return readiness for the scope this version can actually compute.

    Only project scope exists. Saying so is required: a caller asking whether a
    module is implementable must not read a project figure as an answer.
    """

    project = resolve_project(context, project_id)
    snapshot = context.readiness.latest(project.id) or context.readiness.calculate(project.id)
    current_revision = context.readiness.knowledge_revision(project.id)

    return {
        "project_id": str(project.id),
        "scope": "project",
        "module_scope_available": False,
        "scope_note": (
            "Readiness is project-wide in this version. Module, integration, and "
            "release-planning scopes are not implemented, so this figure does not "
            "answer whether any single module is ready to implement."
        ),
        "percentage": snapshot.percentage,
        "status": snapshot.status.value,
        "draft_eligible": snapshot.draft_eligible,
        "implementation_eligible": snapshot.implementation_eligible,
        "knowledge_revision": snapshot.knowledge_revision,
        "stale": snapshot.is_stale_against(current_revision),
        "areas": [
            {
                "key": area.key,
                "name": area.name,
                "state": area.state.value,
                "mandatory": area.mandatory,
                "confirmed": area.confirmed_count,
                "proposed": area.proposed_count,
            }
            for area in snapshot.areas
        ],
        "open_blockers": snapshot.open_blocker_count,
        "critical_blockers": snapshot.critical_blocker_count,
        "unresolved_contradictions": snapshot.unresolved_contradiction_count,
    }


def kae_submit_observation(
    context: ToolContext,
    project_id: str,
    observation: str,
    idempotency_key: str,
    source: dict[str, Any] | None = None,
    classification_hint: str | None = None,
    generation_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record something an agent discovered, as proposed evidence.

    The observation is stored verbatim and nothing is confirmed by it. Text
    arriving here is data to be recorded, never instruction to be followed —
    including when it is phrased as one.
    """

    project = resolve_project(context, project_id)
    if not observation or not observation.strip():
        raise InvalidArgumentError("observation is required")
    if not idempotency_key or not idempotency_key.strip():
        raise InvalidArgumentError(
            "idempotency_key is required so that a retry cannot duplicate evidence"
        )

    sessions = context.memory.sessions_for_project(project.id)
    open_session = next((s for s in sessions if s.status.value == "open"), None)
    if open_session is None:
        open_session = context.memory.open_session(project.id, SessionType.DISCOVERY)

    content = _render_observation(observation, source)
    record = context.memory.record_message(
        project.id,
        SessionId(str(open_session.id)),
        content,
        # An agent submitted this, so it is recorded as an agent. Labelling it
        # USER — as this did — put a model's output into the evidence log under
        # the actor type reserved for a person, which is exactly the confusion
        # the review surface exists to prevent.
        actor_type=ActorType.AGENT,
        message_type=MessageType.PROPOSAL,
        actor_id="mcp-agent",
        idempotency_key=idempotency_key,
    )

    payload: dict[str, Any] = {
        "message_id": str(record.message.id),
        "session_id": str(open_session.id),
        "idempotent_replay": record.replayed,
        "status": "recorded_as_proposed_evidence",
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "note": (
            "Recorded verbatim as evidence. Nothing is confirmed by this call; a "
            "person confirms what becomes project knowledge."
        ),
    }
    payload["extraction"] = _queue_discovery_extraction(
        context, project, record.message.id, open_session, idempotency_key, generation_policy
    )
    payload.update(
        _classification_payload(
            context, project.id, record.message.id, observation.strip(), classification_hint
        )
    )
    return payload


def _queue_discovery_extraction(
    context: ToolContext,
    project: Any,
    message_id: MessageId,
    session: Any,
    idempotency_key: str,
    generation_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enqueue interpretation of this observation, and say plainly whether it ran (N42).

    The missing edge. Extraction was reachable from documents and from
    clarification answers and from nothing else, so a conversational statement
    could be stored perfectly and never become a candidate — which is how a
    project built from one sentence assembled to nothing while every subsystem
    behaved correctly.

    Three outcomes, and a caller must be able to tell them apart without
    inferring from silence: queued, skipped because the caller asked for it to
    be, and unavailable because this deployment cannot. Reporting the last two
    identically would make a policy choice indistinguishable from a broken
    server.

    Nothing here confirms anything. What the run produces is proposed, reviewed
    by a person, and counted toward readiness only then.
    """

    try:
        policy = resolve_generation_policy(generation_policy)
    except DomainInvariantError as error:
        raise InvalidArgumentError(str(error)) from error

    if not policy.extracts_on_submission:
        return {
            "queued": False,
            "reason": "generation_policy.discovery_extraction is disabled",
            "generation_policy": policy.as_dict(),
        }

    run = context.memory.enqueue_run(
        project.id,
        # Discovery, not requirements (N46). `requirements.v1` is disciplined
        # about not inventing requirements nobody expressed, which is correct
        # for a specification and reads an early description almost to nothing.
        AgentRole.DISCOVERY,
        # Derived from the caller's key, so a retried submission reuses the run
        # rather than paying for a second model call or producing a second set
        # of candidates.
        idempotency_key=f"observe:{idempotency_key}",
        session_id=SessionId(str(session.id)),
        input_context={"message_id": str(message_id), "source": "observation"},
    )
    return {
        "queued": True,
        "run_id": str(run.id),
        "status": run.status.value,
        "generation_policy": policy.as_dict(),
        "note": (
            "Queued, not finished. A worker reads the observation and proposes "
            "candidates; a person confirms what becomes project knowledge."
        ),
    }


def _classification_payload(
    context: ToolContext,
    project_id: ProjectId,
    message_id: MessageId,
    text: str,
    hint: str | None,
) -> dict[str, Any]:
    """Classify a recorded observation and describe what that did (T24).

    Classification runs *after* the observation is durable, and its failure is
    reported rather than raised. Evidence capture must not depend on a
    classifier being reachable, and a submission that failed because the
    classifier did would lose the text it was trying to keep.
    """

    if context.classification is None:
        return {
            "classification": {
                "available": False,
                "reason": "no classifier is configured for this server",
                "note": "The observation is recorded. Nothing was classified or routed.",
            }
        }

    outcome = context.classification.classify(project_id, message_id, text, hint)
    if outcome.failed:
        return {
            "classification": {
                "available": True,
                "classified": False,
                "reason": outcome.failure_reason,
                "note": (
                    "The observation is recorded and classification failed. It can "
                    "be retried; nothing was routed."
                ),
            }
        }

    durable = outcome.by_tier(RetentionTier.DURABLE)
    operational = outcome.by_tier(RetentionTier.OPERATIONAL)
    evidence = outcome.by_tier(RetentionTier.EVIDENCE)

    classification: dict[str, Any] = {
        "available": True,
        "classified": True,
        "classifier": outcome.classifier,
        "classifier_version": outcome.classifier_version,
        # The same honesty the search surface applies to a hash-derived
        # embedder: wording a rule-based classifier does not recognise is
        # invisible to it, and a caller told this was semantic would read an
        # unclassified span as "there was nothing there".
        "semantic_classification": outcome.semantic,
        "idempotent_replay": outcome.replayed,
        "spans": [
            {
                "classification": span.classification.value,
                "retention_tier": span.tier.value,
                "route": span.route.value,
                "confidence": round(span.confidence, 2),
                "review_required": span.review_required,
                "span": {"start": span.span.start, "end": span.span.end},
                "text": span.normalized_text,
                "fields": span.fields,
            }
            for span in outcome.spans
        ],
        "durable_candidates": len(durable),
        "operational_records": len(outcome.operational_ids),
        "evidence_only": len(evidence),
        "unclassified": len(outcome.unclassified_spans),
        "knowledge_changed": False,
        "note": (
            "Classification says what a span was, not whether it is true. "
            "Nothing here is confirmed knowledge, and no operational status "
            "changed: a reported transition is a proposal."
        ),
    }
    if operational and not outcome.operational_ids and not outcome.replayed:
        classification["warnings"] = [
            "Operational spans were found but none met the confidence to route; "
            "they are recorded for review."
        ]
    if hint:
        # T24.5: recorded and compared, never obeyed. A caller asserting
        # "requirement" over a greeting would otherwise route the greeting.
        classification["hint"] = {
            "supplied": hint,
            "agreed": outcome.hint_agreed,
            "note": (
                "A hint is compared against what the classifier found. It does "
                "not override the classification."
            ),
        }
    return {"classification": classification}


def _render_observation(observation: str, source: dict[str, Any] | None) -> str:
    """Render an observation with its source, as one verbatim record.

    The classification hint used to be appended here as a line of text. It
    routed nothing and was never read again, which made the parameter a claim
    the system did not honour (T24.5). It is now compared against what the
    classifier found and reported as agreement or disagreement, so the observed
    text stays the observation and nothing else.

    The observation is the prefix of the rendered content, so a span into the
    observation is a span into what was stored.
    """

    lines = [observation.strip()]
    if source:
        parts = [f"{key}: {value}" for key, value in sorted(source.items()) if value]
        if parts:
            lines.append("")
            lines.append("Source — " + "; ".join(parts))
    return "\n".join(lines)


def kae_get_operational_state(
    context: ToolContext,
    project_id: str,
    states: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    subject: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Report where the work stands, as reported rather than as verified (N4).

    Separate from the briefing on purpose. The briefing answers "what state is
    this project in" and carries operational state as one section of that;
    this answers "show me the blockers" or "what happened to M8", which is a
    different question and needs filters and paging the briefing should not
    grow.

    Everything here is a **report**. `authority` says who claimed it and
    `state` says whether anyone has accepted the claim; a record that is
    `proposed` has been read by nobody.
    """

    project = resolve_project(context, project_id)
    if context.classification is None:
        raise CapabilityUnavailableError(
            "operational state is unavailable: no classifier is configured for "
            "this server, so no observation has been classified or routed"
        )

    records = context.classification.operational_state(
        project.id, states=states, kinds=kinds, subject=subject
    )
    page = response_policy.paginate(
        [
            {
                "operational_update_id": record.operational_update_id,
                "kind": record.kind,
                "subject": record.subject,
                "reported_status": record.reported_status,
                "current_status": record.current_status,
                "transition_type": record.transition_type,
                "authority": record.authority,
                "state": record.state,
                "verification": record.verification,
                "effective_date": record.effective_date,
                "date_role": record.date_role,
                "settlements": record.detail.get("settlements", []),
            }
            for record in records
        ],
        limit=limit,
        cursor=cursor,
    )
    return {
        "project_id": str(project.id),
        **page,
        "filters": {
            "states": list(states) if states else [state.value for state in ACTIVE_STATES],
            "kinds": list(kinds) if kinds else None,
            "subject": subject,
        },
        "note": (
            "Reported, not verified. A milestone is never completed because a "
            "sentence said so; a proposed record is a claim nobody has accepted."
        ),
    }


def kae_get_classifications(
    context: ToolContext,
    project_id: str,
    tiers: Sequence[str] | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """List classified spans of this project's observations (N4).

    Reading these was previously possible only through the briefing's tier
    section, which cannot be filtered or paged. A reviewer working through what
    a classifier produced needs both.

    Each span carries the range of the stored observation it came from, so a
    reader can check the classification against the words rather than against
    the summary of them.
    """

    project = resolve_project(context, project_id)
    if context.classification is None:
        raise CapabilityUnavailableError(
            "classifications are unavailable: no classifier is configured for this server"
        )

    resolved = _requested_tiers(tiers) if tiers else None
    rows = context.classification.classifications(project.id, resolved)
    page = response_policy.paginate(list(rows), limit=limit, cursor=cursor)
    return {
        "project_id": str(project.id),
        **page,
        "semantic_classification": context.classification.semantic,
        "classifier": context.classification.classifier_name,
        "classifier_version": context.classification.classifier_version,
        "tiers": [tier.value for tier in resolved] if resolved else "all",
        "knowledge_changed": False,
        "note": (
            "Classification says what a span was, not whether it is true. "
            "Nothing listed here is confirmed knowledge."
        ),
    }


def kae_settle_operational_record(
    context: ToolContext,
    project_id: str,
    operational_update_id: str,
    state: str,
    actor: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Relay a person's decision about a reported operational record (N4).

    The tool *relays* a decision; it does not make one — the same separation
    `kae_confirm_knowledge` rests on. An agent that has not been told who is
    settling cannot supply `actor`, and the audit trail never says a person
    decided without naming which person.

    Accepting a reported milestone completion still does not verify it. It
    records that someone took responsibility for the claim, which is a
    different and weaker thing, and the record keeps saying who reported it.
    """

    project = resolve_project(context, project_id)
    if context.classification is None:
        raise CapabilityUnavailableError(
            "operational records are unavailable: no classifier is configured for this server"
        )
    if not operational_update_id or not operational_update_id.strip():
        raise InvalidArgumentError("operational_update_id is required")
    if not actor or not actor.strip():
        raise InvalidArgumentError(
            "actor is required: settling an operational record is a decision, and a "
            "decision nobody is named for cannot be audited"
        )
    try:
        target = OperationalState(str(state).strip().lower())
    except ValueError:
        valid = ", ".join(s.value for s in OperationalState)
        raise InvalidArgumentError(f"unknown state {state!r}; expected one of {valid}") from None

    try:
        record = context.classification.settle(
            project.id, operational_update_id.strip(), target, actor.strip(), note
        )
    except OperationalRecordNotFoundError as error:
        raise KnowledgeNotFoundError(str(error)) from error
    except InvalidOperationalTransitionError as error:
        raise InvalidStateTransitionError(str(error)) from error

    return {
        "operational_update_id": record.operational_update_id,
        "kind": record.kind,
        "subject": record.subject,
        "state": record.state,
        "reported_status": record.reported_status,
        "authority": record.authority,
        "verification": record.verification,
        "settled_by": actor.strip(),
        "knowledge_changed": False,
        "note": (
            "A decision was recorded about a reported claim. This does not verify "
            "the claim, and it does not change project knowledge."
        ),
    }


def kae_confirm_knowledge(
    context: ToolContext,
    project_id: str,
    knowledge_id: str,
    expected_version: Any = None,
    note: str | None = None,
    reviewer: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Relay a person's decision to accept one proposed item as authoritative.

    The tool *relays* a decision; it does not make one. FR-005 keeps
    confirmation a human act, and this surface is reached by agents, so the
    separation cannot rest on the capability being absent — it rests on the
    decision being attributable.

    ``reviewer`` is therefore required. An agent that has not been told who is
    confirming cannot supply it, and the audit trail never says a person decided
    without naming which person. That is weaker than not having the tool at all,
    and it is the trade recorded in PHASE_C_DECISIONS.md.
    """

    project = resolve_project(context, project_id)
    if not knowledge_id or not knowledge_id.strip():
        raise InvalidArgumentError("knowledge_id is required")
    if not reviewer or not reviewer.strip():
        raise InvalidArgumentError(
            "reviewer is required: confirmation is a human act, and the record "
            "must name the person who made it rather than the agent relaying it"
        )
    version = _require_version(expected_version)

    try:
        outcome = context.memory.review_confirm(
            project.id,
            KnowledgeItemId(knowledge_id),
            expected_version=version,
            actor_type=ActorType.USER,
            actor_id=reviewer.strip(),
            note=note,
            idempotency_key=idempotency_key,
        )
    except DomainKnowledgeNotFound as error:
        raise KnowledgeNotFoundError(str(error)) from None
    except StaleVersionError as error:
        raise VersionConflictError(str(error)) from None
    except InvalidLifecycleTransitionError as error:
        raise InvalidStateTransitionError(str(error)) from None

    return {
        "knowledge_id": knowledge_id,
        "state": outcome.item.lifecycle.value,
        "version": outcome.item.current_version.number,
        "authoritative": outcome.item.lifecycle is LifecycleState.VALIDATED,
        "already_applied": outcome.replayed,
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "readiness_changed": not outcome.replayed,
    }


def kae_reject_knowledge(
    context: ToolContext,
    project_id: str,
    knowledge_id: str,
    expected_version: Any = None,
    reason_code: str | None = None,
    note: str | None = None,
    reviewer: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Relay a person's decision that proposed knowledge must not become authoritative.

    Not deletion. The statement and its provenance stay readable; it stops
    counting toward readiness and stops appearing in search. Someone reading the
    project later can still see what was considered and turned down, which is
    most of the value of having rejected it explicitly rather than ignoring it.

    ``reviewer`` is required for the same reason as confirmation: this records a
    human decision, and the record names which human.
    """

    project = resolve_project(context, project_id)
    if not knowledge_id or not knowledge_id.strip():
        raise InvalidArgumentError("knowledge_id is required")
    if not reviewer or not reviewer.strip():
        raise InvalidArgumentError(
            "reviewer is required: rejection is a human decision, and the record "
            "must name the person who made it rather than the agent relaying it"
        )
    version = _require_version(expected_version)
    reason = _require_reason(reason_code, note)

    try:
        outcome = context.memory.review_reject(
            project.id,
            KnowledgeItemId(knowledge_id),
            expected_version=version,
            reason_code=reason,
            actor_type=ActorType.USER,
            actor_id=reviewer.strip(),
            note=note,
            idempotency_key=idempotency_key,
        )
    except DomainKnowledgeNotFound as error:
        raise KnowledgeNotFoundError(str(error)) from None
    except StaleVersionError as error:
        raise VersionConflictError(str(error)) from None
    except InvalidLifecycleTransitionError as error:
        raise InvalidStateTransitionError(str(error)) from None

    return {
        "knowledge_id": knowledge_id,
        "state": outcome.item.lifecycle.value,
        "version": outcome.item.current_version.number,
        "authoritative": False,
        "already_applied": outcome.replayed,
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "readiness_changed": not outcome.replayed,
        "retrievable": False,
    }


def _require_version(expected_version: Any) -> int:
    """Validate the optimistic-concurrency token shared by the review tools."""

    if expected_version is None:
        raise InvalidArgumentError(
            "expected_version is required so a decision cannot be applied to "
            "wording that has changed since it was read"
        )
    try:
        version = int(expected_version)
    except (TypeError, ValueError):
        raise InvalidArgumentError("expected_version must be an integer") from None
    if version < 1:
        raise InvalidArgumentError("expected_version must be 1 or greater")
    return version


def _require_reason(reason_code: str | None, note: str | None) -> RejectionReason:
    """Resolve the rejection reason, insisting that 'other' says something.

    A reason of "other" with no note records that someone declined to say why,
    which is less useful than no category at all — the next reader cannot tell a
    factual error from a scope decision.
    """

    if not reason_code or not reason_code.strip():
        raise InvalidArgumentError(
            "reason_code is required: "
            + ", ".join(sorted(reason.value for reason in RejectionReason))
        )
    try:
        reason = RejectionReason(reason_code.strip())
    except ValueError:
        raise InvalidArgumentError(
            f"unknown reason_code {reason_code!r}; expected one of "
            + ", ".join(sorted(r.value for r in RejectionReason))
        ) from None
    if reason is RejectionReason.OTHER and not (note or "").strip():
        raise InvalidArgumentError("a reason_code of 'other' requires a note explaining why")
    return reason


def kae_correct_knowledge(
    context: ToolContext,
    project_id: str,
    knowledge_id: str,
    expected_version: Any = None,
    content: str | None = None,
    note: str | None = None,
    reviewer: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Relay a person's corrected wording for one knowledge statement.

    The previous wording is kept, not overwritten: versions are append-only, and
    the original remains readable as the provenance of anything derived from it
    while it stood. What the agent proposed and what the person accepted are
    both part of the record.

    Correcting an unreviewed statement accepts the corrected form, because the
    reviewer wrote it. Correcting a confirmed one returns it to proposed — the
    old confirmation covered the old wording.
    """

    project = resolve_project(context, project_id)
    if not knowledge_id or not knowledge_id.strip():
        raise InvalidArgumentError("knowledge_id is required")
    if not reviewer or not reviewer.strip():
        raise InvalidArgumentError(
            "reviewer is required: a correction is a human decision, and the "
            "record must name the person who wrote it rather than the agent "
            "relaying it"
        )
    if content is None or not content.strip():
        raise InvalidArgumentError("content is required: a correction must say what it corrects to")
    version = _require_version(expected_version)

    try:
        outcome = context.memory.review_correct(
            project.id,
            KnowledgeItemId(knowledge_id),
            expected_version=version,
            content=content,
            actor_type=ActorType.USER,
            actor_id=reviewer.strip(),
            note=note,
            idempotency_key=idempotency_key,
        )
    except DomainKnowledgeNotFound as error:
        raise KnowledgeNotFoundError(str(error)) from None
    except StaleVersionError as error:
        raise VersionConflictError(str(error)) from None
    except (InvalidLifecycleTransitionError, DomainInvariantError) as error:
        raise InvalidStateTransitionError(str(error)) from None

    authoritative = outcome.item.lifecycle is LifecycleState.VALIDATED
    return {
        "knowledge_id": knowledge_id,
        "state": outcome.item.lifecycle.value,
        "version": outcome.item.current_version.number,
        "replaced_version": outcome.event.from_version_number if outcome.event else None,
        "authoritative": authoritative,
        "already_applied": outcome.replayed,
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "readiness_changed": not outcome.replayed,
        "embedding": "pending" if not outcome.replayed else "unchanged",
        "note": (
            "Corrected wording accepted; you wrote it."
            if authoritative
            else "Returned to proposed: the earlier confirmation covered the previous wording."
        ),
    }


CLARIFICATION_LIMIT = 10
"""How many open questions one call returns by default.

A gap list is a work queue, and handing back forty at once produces neither a
review nor a plan. The cap is a default rather than a maximum so a caller that
genuinely wants the whole queue can say so.
"""


def kae_get_clarifications(
    context: ToolContext,
    project_id: str,
    limit: int | None = None,
    include_deferred: bool = False,
) -> dict[str, Any]:
    """Return the open questions this project's gaps justify asking a person.

    **This call records questions.** Clarifications are derived from findings
    and have no identity of their own, so a purely read-only version would hand
    back questions that :func:`kae_answer_clarification` could not answer.
    Materialising them is what makes them addressable.

    Safe to call repeatedly. Questions are keyed on what they are about rather
    than on their wording, so re-deriving one already asked returns the existing
    question instead of asking a person the same thing twice.

    Only gaps a person can answer are returned. Work queues — "confirm these
    candidates" — are not questions, and offering them here would spend the one
    resource this loop exists to spend carefully.

    A question someone deferred or could not answer is **still unresolved and
    is not asked again** unless `include_deferred` asks for it. It is counted
    either way, in `deferred`, so "not asked again" never quietly becomes "no
    longer owed".
    """

    project = resolve_project(context, project_id)
    if context.clarification is None:
        raise CapabilityUnavailableError(
            capability="clarifications",
            missing=["clarification_service"],
            use_instead=["kae_get_project_briefing"],
        )
    bound = _clarification_limit(limit)

    questions = context.clarification.open_questions(
        project.id, limit=bound, include_deferred=include_deferred
    )
    awaiting = context.clarification.awaiting_a_person(project.id)
    return {
        "project_id": str(project.id),
        "questions": [_render_question(question) for question in questions],
        "count": len(questions),
        # Unresolved, but already put to someone who did not decide. Held back
        # from the asking list rather than dropped: a person who said "I don't
        # know yet" should not be asked again on the next call, and the project
        # should not pretend the question went away.
        "deferred": len(awaiting),
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        # Not "truncation": that name belongs to the response policy, which
        # uses it for fields a detail level dropped. Two different omissions
        # under one key would leave a caller unable to tell "questions you did
        # not see" from "fields we compacted away".
        "omitted": _clarification_omitted(context, project.id, len(questions), bound),
        "note": (
            "Answer with kae_answer_clarification. An answer is recorded as "
            "evidence and extracted into proposed knowledge; a person still "
            "confirms what becomes project knowledge."
        ),
    }


def _clarification_limit(limit: int | None) -> int:
    if limit is None:
        return CLARIFICATION_LIMIT
    try:
        bound = int(limit)
    except (TypeError, ValueError):
        raise InvalidArgumentError("limit must be an integer") from None
    if bound < 1:
        raise InvalidArgumentError("limit must be 1 or greater")
    return bound


def _render_question(question: OpenQuestion) -> dict[str, Any]:
    return {
        "clarification_id": str(question.id),
        "question": question.question,
        "severity": question.severity,
        "finding_kind": question.finding_kind,
        "area_key": question.area_key,
        "knowledge_ids": list(question.knowledge_ids),
        "status": "open",
        # Open, and not necessarily untouched. A question someone deferred is
        # still owed; reporting only "open" would lose that someone was already
        # asked and said they did not know (N36).
        "disposition": question.disposition.value,
        "asked_at": question.asked_at.isoformat(),
        "newly_asked": question.newly_asked,
    }


def _clarification_omitted(
    context: ToolContext, project_id: Any, returned: int, bound: int
) -> dict[str, Any] | None:
    """Report the questions this bound left out.

    A caller cannot tell a short queue from a bounded one, and treating the
    second as the first is how a project looks finished while questions go
    unasked.
    """

    if returned < bound or context.clarification is None:
        return None
    total = len(context.clarification.pending(project_id))
    if total <= returned:
        return None
    return {
        "returned": returned,
        "available": total,
        "reason": f"limit={bound}",
        "guidance": "Raise limit to see the rest. This is not the whole queue.",
    }


def kae_answer_clarification(
    context: ToolContext,
    project_id: str,
    clarification_id: str,
    answer: str | None = None,
    disposition: str = "answered",
    assumption_id: str | None = None,
    idempotency_key: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Record what a person said about an open question, verbatim.

    The answer is **evidence**, not knowledge. It is stored exactly as given and
    handed to the requirements agent like any other input; what that produces is
    a candidate a person still confirms. Routing it anywhere else would let this
    loop write project knowledge on someone's behalf.

    So the response says three separate things, and they must stay separate: the
    answer was accepted, extraction was scheduled, and **no knowledge has
    changed yet**. A caller that reads the first as the third would believe the
    project knows something nobody has confirmed.

    A fourth thing stays separate too: `disposition`. "I don't know yet, pick
    something reasonable but don't make it permanent" is a real answer to a real
    question, and it is not a decision. Recording it as one would put a choice
    in the project that nobody made; discarding it would lose what the person
    actually said. Only `answered` closes the question — every other disposition
    is recorded and **leaves it open**, so the queue keeps saying what is
    genuinely undecided.
    """

    project = resolve_project(context, project_id)
    if context.clarification is None:
        raise CapabilityUnavailableError(
            capability="clarifications",
            missing=["clarification_service"],
            use_instead=["kae_submit_observation"],
        )
    if not clarification_id or not clarification_id.strip():
        raise InvalidArgumentError("clarification_id is required")
    if answer is None or not answer.strip():
        raise InvalidArgumentError(
            "answer is required: an empty answer records that someone was asked "
            "and says nothing about what they know"
        )
    try:
        chosen = Disposition(str(disposition).strip().lower())
    except ValueError:
        valid = ", ".join(value.value for value in Disposition)
        raise InvalidArgumentError(
            f"unknown disposition {disposition!r}; expected one of {valid}"
        ) from None

    try:
        recorded = context.clarification.answer(
            project.id,
            MessageId(clarification_id),
            answer,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            disposition=chosen,
            assumption_id=assumption_id,
        )
    except DispositionError as error:
        raise InvalidArgumentError(str(error)) from None
    except LookupError as error:
        raise KnowledgeNotFoundError(str(error)) from None
    except AlreadyAnsweredError as error:
        raise ConflictError(str(error)) from None
    except ValueError as error:
        raise InvalidArgumentError(str(error)) from None

    progress = context.clarification.progress(project.id, MessageId(clarification_id))
    return {
        "clarification_id": clarification_id,
        "answer_id": str(recorded.answer.id),
        "status": chosen.value,
        # The question's own state, not the response's. These differ precisely
        # when they matter: a deferred question is answered *and* still open.
        "disposition": chosen.value,
        "question_settled": settles(chosen),
        "still_open": not settles(chosen),
        "assumption_id": assumption_id,
        # Explicit rather than inferred. A caller should not have to work out
        # from `knowledge_changed: false` and a run id where this actually is.
        "workflow_state": progress.state.value,
        "extraction_run_id": str(recorded.run_id),
        # Three separate facts, deliberately not collapsed. The answer is
        # recorded; extraction is queued and has not run; knowledge is
        # unchanged until a person confirms what extraction proposes.
        "knowledge_state": "pending_extraction",
        "knowledge_changed": progress.knowledge_changed,
        "readiness_changed": False,
        "replayed": recorded.replayed,
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "next_steps": [
            "Extraction runs when a worker picks up the queued run.",
            "What it produces is proposed knowledge, not confirmed knowledge.",
            "A person confirms it with kae_confirm_knowledge.",
            *(
                []
                if settles(chosen)
                else [
                    "This question stays open: what was recorded is not a decision.",
                    "It will be asked again, and answering it later is not a correction.",
                ]
            ),
        ],
    }


def kae_ingest_document(
    context: ToolContext,
    project_id: str,
    document: str,
    text: str,
    max_chunks: int | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Record a document as evidence and queue it to be read (T19).

    The document is split and every span is stored verbatim as a message, which
    is what a later statement traces back to. Extraction reads those stored
    spans rather than a copy passed through this call, so the provenance chain
    survives the trip.

    **Nothing is known yet when this returns.** The response separates three
    facts that a caller must not collapse: the text was recorded, extraction was
    queued, and no knowledge has changed. Reading the first as the third would
    have the project believing something no run has produced and no person has
    confirmed.

    Idempotent per document and content. Re-submitting the same document reuses
    the messages and runs it already created instead of reading it twice.
    """

    project = resolve_project(context, project_id)
    if context.ingestion is None:
        raise CapabilityUnavailableError(
            capability="document ingestion",
            missing=["ingestion_service"],
            use_instead=["kae_submit_observation for a single statement"],
        )
    if not document or not document.strip():
        raise InvalidArgumentError(
            "document is required: it names the source a span is quoted from, "
            "and evidence without a source cannot be traced"
        )
    if not text or not text.strip():
        raise InvalidArgumentError("text is required; an empty document records nothing")

    policy = IngestionPolicy()
    if max_chunks is not None:
        if max_chunks < 1:
            raise InvalidArgumentError("max_chunks must be at least 1")
        policy = IngestionPolicy(
            target_tokens=policy.target_tokens,
            max_tokens=policy.max_tokens,
            max_chunks=max_chunks,
            max_items_per_chunk=policy.max_items_per_chunk,
        )

    try:
        result = context.ingestion.ingest_document(
            project.id, document.strip(), text, policy=policy, actor_id=actor_id
        )
    except ValueError as error:
        raise InvalidArgumentError(str(error)) from None

    return _ingestion_payload(context, project_id, result)


def _ingestion_payload(
    context: ToolContext, project_id: str, result: IngestionResult
) -> dict[str, Any]:
    """Render an ingestion without overstating what it achieved."""

    outstanding = (
        context.ingestion.outstanding_runs(ProjectId(project_id))
        if context.ingestion is not None
        else 0
    )
    warnings = list(result.warnings)
    if not result.complete:
        warnings.append(
            f"{result.truncated_chunks} of {result.chunks_available} spans were not "
            f"queued: the document exceeded max_chunks. Raise max_chunks or split "
            f"the document, or the unread remainder will be silently absent from "
            f"everything downstream."
        )

    return {
        "document": result.document,
        "session_id": str(result.session_id),
        "chunks_recorded": len(result.chunks),
        "chunks_available": result.chunks_available,
        "truncated_chunks": result.truncated_chunks,
        "complete": result.complete,
        "idempotent_replay": result.replayed,
        "extraction_runs_queued": [str(chunk.run_id) for chunk in result.chunks],
        "outstanding_runs": outstanding,
        # Three separate facts, deliberately not collapsed.
        "evidence_recorded": True,
        "knowledge_changed": False,
        "workflow_state": "extraction_queued" if result.chunks else "nothing_to_read",
        "warnings": warnings,
        "next_steps": [
            "Extraction runs are queued, not finished. A worker must drain them "
            "before any candidate exists.",
            "Then kae_get_project_briefing shows what was proposed, and a person "
            "confirms it with kae_confirm_knowledge.",
        ],
    }


def kae_get_preliminary_context(
    context: ToolContext,
    project_id: str,
    purpose: str = "discovery",
) -> dict[str, Any]:
    """Compose the most useful view a sparse project supports (N44).

    Distinct from `kae_assemble_context`, which shows what a person has
    confirmed. That is the right default for building against and the wrong one
    for a project where nobody has confirmed anything yet — which is the
    ordinary state of a project someone described in a sentence yesterday.

    Four things are returned separately and are **never merged**: what was
    stated verbatim, what has been confirmed, what was proposed or assumed, and
    what nobody has decided. A reader who cannot tell a confirmed requirement
    from a plausible guess has a document that is worse than nothing — it is the
    same document with the warning removed.

    This never refuses. Low readiness produces a thinner context, never an
    error: incomplete project knowledge is a normal project condition, and
    withholding output over it is the gate this system does not have.

    Nothing here is confirmed by producing it. Reading is not deciding.
    """

    project = resolve_project(context, project_id)
    if context.preliminary is None:
        raise CapabilityUnavailableError(
            capability="preliminary context",
            missing=["preliminary_context_service"],
            use_instead=["kae_assemble_context", "kae_get_project_briefing"],
        )

    try:
        chosen = AssemblyPurpose(purpose)
    except ValueError:
        raise InvalidArgumentError(
            f"unknown purpose {purpose!r}. Choose one of: "
            f"{', '.join(sorted(p.value for p in AssemblyPurpose))}"
        ) from None

    preliminary = context.preliminary.compose(project.id, chosen)
    return _preliminary_payload(preliminary)


def _preliminary_payload(preliminary: PreliminaryContext) -> dict[str, Any]:
    """Render preliminary context with its epistemic boundaries intact."""

    return {
        "project_id": preliminary.project_id,
        "project_name": preliminary.project_name,
        "generated_at": preliminary.generated_at.isoformat(),
        "knowledge_revision": preliminary.knowledge_revision,
        "readiness_percentage": preliminary.readiness_percentage,
        "is_preliminary": preliminary.is_preliminary,
        # First, because everything below is derived from it, and a preliminary
        # context is far likelier to be wrong in its interpretation than in its
        # transcription. A reader who can see the sentence can catch that.
        "stated_verbatim": [
            {
                "message_id": entry.message_id,
                "text": entry.text,
                # Relayed by an agent or typed by a person: not the same
                # evidence, and a payload that flattened them would overstate
                # the second.
                "actor_type": entry.actor_type,
                "message_type": entry.message_type,
            }
            for entry in preliminary.stated_verbatim
        ],
        "known": [_statement_payload(s) for s in preliminary.known],
        "proposed": [_statement_payload(s) for s in preliminary.proposed],
        "assumed": [
            {
                "assumption_id": entry.assumption_id,
                "subject": entry.subject,
                "assumed_value": entry.assumed_value,
                "reason": entry.reason,
                "origin": entry.origin,
                "consequence": entry.consequence,
                "state": entry.state,
                "reversible": entry.reversible,
                "material": entry.material,
                "accepted_by": entry.accepted_by,
                # Carries the consequence in the sentence itself. "We assumed
                # single-tenant" invites a nod; the same line with "multi-tenancy
                # would be architectural rework" invites a decision.
                "disclosure": entry.disclosure,
            }
            for entry in preliminary.assumed
        ],
        "material_unknowns": [_unknown_payload(u) for u in preliminary.material_unknowns],
        "deferrable_unknowns": [_unknown_payload(u) for u in preliminary.deferrable_unknowns],
        "package_id": preliminary.assembly.manifest.package_id,
        "content_hash": preliminary.assembly.manifest.content_hash,
        # Same pins the assembly read, so a deliverable recorded from this is
        # reproducible in fact rather than in appearance (N20.1).
        "statement_pins": [
            {"knowledge_id": knowledge_id, "version": version}
            for knowledge_id, version in preliminary.assembly.manifest.statement_pins
        ],
        "warnings": list(preliminary.warnings),
        "knowledge_changed": False,
        "note": (
            "Nothing here is confirmed by being returned. Proposed statements "
            "are candidates and assumptions are guesses; a person confirms what "
            "becomes project knowledge."
        ),
    }


def _statement_payload(statement: AssembledStatement) -> dict[str, Any]:
    return {
        "knowledge_id": statement.knowledge_id,
        "kind": statement.kind,
        "text": statement.text,
        "area_key": statement.area_key,
        "version": statement.version,
        "lifecycle": statement.lifecycle,
        # Two separate words that were one for too long: `label` says where
        # authority comes from, `inclusion_class` says whether a person ruled.
        "label": statement.label,
        "inclusion_class": statement.inclusion_class,
    }


def _unknown_payload(unknown: UnknownEntry) -> dict[str, Any]:
    return {
        "clarification_id": unknown.clarification_id,
        "question": unknown.question,
        "area_key": unknown.area_key,
        "severity": unknown.severity,
        "finding_kind": unknown.finding_kind,
        # Someone was already asked and did not decide. Different from nobody
        # having been asked, and the difference must survive into the document.
        "disposition": unknown.disposition,
    }


def kae_assemble_context(
    context: ToolContext,
    project_id: str,
    purpose: str = "implementation",
    include_proposed: bool = False,
) -> dict[str, Any]:
    """Assemble the knowledge one purpose needs, pinned to one revision (T21).

    Bounded rather than complete: each purpose names the areas that serve it, so
    an implementation package does not carry the architecture review's noise.
    The bound is what makes this smaller than the project.

    Deterministic. The same revision and purpose produce the same content hash,
    so a caller can tell "this is the package I already have" from "the project
    moved" without re-reading it.

    ``include_proposed`` carries unconfirmed candidates too. Allowed, because an
    incomplete package is often still useful — but the manifest always states
    the confirmation split and every unresolved gap it is carrying. Generation
    may be incomplete; it may never be silent.
    """

    project = resolve_project(context, project_id)
    if context.assembly is None:
        raise CapabilityUnavailableError(
            capability="context assembly",
            missing=["assembly_service"],
            use_instead=["kae_get_project_briefing"],
        )

    try:
        chosen = AssemblyPurpose(purpose)
    except ValueError:
        raise InvalidArgumentError(
            f"unknown purpose {purpose!r}. Choose one of: "
            f"{', '.join(sorted(p.value for p in AssemblyPurpose))}"
        ) from None

    assembly = context.assembly.assemble(project.id, chosen, include_proposed=include_proposed)
    return _assembly_payload(assembly)


def _assembly_payload(assembly: ContextAssembly) -> dict[str, Any]:
    """Render an assembly with its lineage and its limits attached."""

    manifest = assembly.manifest
    confirmation = manifest.confirmation_state
    description = describe_package(assembly)
    return {
        "manifest": {
            "package_id": manifest.package_id,
            "project_id": manifest.project_id,
            "scope": manifest.scope,
            "purpose": manifest.purpose,
            "knowledge_revision": manifest.knowledge_revision,
            "generated_at": manifest.generated_at.isoformat(),
            "generator_version": manifest.generator_version,
            "package_schema": manifest.package_schema,
            "content_hash": manifest.content_hash,
            "statement_count": manifest.statement_count,
            "traced_statements": manifest.traced_statements,
            "source_knowledge": list(manifest.source_knowledge),
            # Always present, including when everything is confirmed: a reader
            # must never infer from an absent field that nothing was proposed.
            "confirmation_state": {
                "confirmed": confirmation.confirmed,
                "proposed": confirmation.proposed,
                "contested": confirmation.contested,
                "total": confirmation.total,
            },
            "unresolved_critical_gaps": [
                {"summary": gap.summary, "kind": gap.kind, "area": gap.area_key}
                for gap in manifest.unresolved_critical_gaps
            ],
            "warnings": list(manifest.warnings),
        },
        "sections": [
            {
                "area": section.area_key,
                "name": section.name,
                "statements": [
                    {
                        "knowledge_id": statement.knowledge_id,
                        "kind": statement.kind,
                        "text": statement.text,
                        "label": statement.label,
                        "version": statement.version,
                        "lifecycle": statement.lifecycle,
                    }
                    for statement in section.statements
                ],
            }
            for section in assembly.sections
        ],
        # What a package would contain, described rather than produced (T22).
        # Rendering belongs to whoever owns the destination; what a caller needs
        # here is the shape, so it can decide whether to render at all.
        "package": {
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
        },
        "guidance": [
            "Every statement carries its lifecycle. Treat anything not confirmed "
            "as a candidate, not a fact.",
            "unresolved_critical_gaps are unanswered by a person. Do not choose "
            "an answer on the project's behalf; if one blocks the work, stop.",
            f"This package is pinned to knowledge revision "
            f"{manifest.knowledge_revision}. Re-assemble if the project has moved.",
        ],
    }
