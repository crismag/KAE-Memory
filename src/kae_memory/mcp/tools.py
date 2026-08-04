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

from collections.abc import Sequence
from typing import Any

from kae_memory.agents.provider import ranks_by_meaning
from kae_memory.application.blueprint_service import Blueprint, BlueprintService
from kae_memory.application.clarification_service import ClarificationService, OpenQuestion
from kae_memory.application.memory_service import MemoryService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import (
    MAX_DISTANCE,
    RetrievalService,
    SearchHit,
    SearchMode,
)
from kae_memory.application.review_service import Finding, ReviewService
from kae_memory.domain.chunks import strip_metadata_prefix
from kae_memory.domain.errors import (
    AlreadyAnsweredError,
    DomainInvariantError,
    InvalidLifecycleTransitionError,
    StaleVersionError,
)
from kae_memory.domain.errors import KnowledgeNotFoundError as DomainKnowledgeNotFound
from kae_memory.domain.identifiers import KnowledgeItemId, MessageId, ProjectId, SessionId
from kae_memory.domain.knowledge_review import RejectionReason
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.readiness import AreaResult, ReadinessSnapshot
from kae_memory.domain.workspace import ActorType, MessageType, SessionType
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
    ) -> None:
        self.memory = memory
        self.blueprint = blueprint
        self.readiness = readiness
        self.review = review
        self.retrieval = retrieval
        self.clarification = clarification
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


def _require_project(context: ToolContext, project_id: str) -> Any:
    if not project_id or not project_id.strip():
        raise InvalidArgumentError("project_id is required")
    project = context.memory.get_project(ProjectId(project_id))
    if project is None:
        raise ProjectNotFoundError(f"no project with id {project_id!r}")
    return project


def kae_list_projects(context: ToolContext) -> dict[str, Any]:
    """Identify the projects this environment can read."""

    projects = context.memory.list_projects()
    return {
        "projects": [
            {
                "project_id": str(project.id),
                "name": project.name,
                "key": project.key,
                "status": project.status.value,
            }
            for project in projects
        ],
        "count": len(projects),
    }


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


def kae_get_project_briefing(context: ToolContext, project_id: str) -> dict[str, Any]:
    """Return the current concise understanding of one project.

    Composes the blueprint with readiness, because the blueprint needs the
    readiness figures to state its own limits honestly.

    Everything here is counted or computed from confirmed knowledge. The
    response adds no narrative and no purpose statement: summarising a project
    in words nobody confirmed would put an unattributable claim in the one tool
    whose value is that it never makes them.
    """

    project = _require_project(context, project_id)
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

    return {
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
    """Report that module context is not available in this version.

    Deliberately returns a gap rather than data. Modules are not a knowledge
    kind here, no general relationship write path exists, and nothing traverses
    the graph — so any module context this tool produced would be invented by
    the adapter rather than retrieved from the domain.

    The gap now names its subject and the way out. "Unavailable" alone leaves a
    caller unable to tell an unregistered module from an unsupported feature,
    and those have different remedies.
    """

    project = _require_project(context, project_id)
    if not module or not module.strip():
        raise InvalidArgumentError("module is required")
    raise CapabilityUnavailableError(
        capability="module context",
        missing=[
            "modules as a knowledge kind",
            "relationship write path (edges can currently only be created as contradictions)",
            "graph traversal for dependencies and dependents",
            "module-scoped readiness",
            "purpose- and scope-bounded context assembly",
        ],
        use_instead=[
            "kae_get_project_briefing for current project understanding",
            "kae_search_knowledge to locate knowledge related to this module",
            "kae_get_open_decisions to see what is unresolved",
        ],
        subject={
            "module": module,
            "project": project.name,
            "status": "not_registered",
            "detail": (
                "No module of this name is recorded, and none could be: modules "
                "are not yet a knowledge kind, so this version has nowhere to "
                "register one. The name was not rejected — it was never lookable."
            ),
        },
        available_now=_project_knowledge_named(context, project, module),
        next_steps=[
            "Read the project briefing for the confirmed knowledge that does exist.",
            "Resolve the open decisions that would block this module's requirements.",
            "Registering modules requires the module capability itself; it is a "
            "product change, not a configuration one.",
        ],
    )


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

    project = _require_project(context, project_id)
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

    payload: dict[str, Any] = {
        "query": query,
        "search_mode": resolved,
        "semantic_search_available": context.semantic_ranking,
        "ranking": {
            "lexical": resolved == "lexical",
            "semantic": resolved == "semantic",
            "metadata_filtered": parsed_kinds is not None,
        },
        "results": [
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
        "count": len(hits),
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


def kae_get_open_decisions(context: ToolContext, project_id: str) -> dict[str, Any]:
    """Return what is unresolved and could affect an agent's work."""

    project = _require_project(context, project_id)
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
        "open_knowledge": [
            {
                "knowledge_id": str(item.id),
                "text": item.current_version.content,
                "lifecycle": item.lifecycle.value,
            }
            for item in unknowns
        ],
        "findings": [
            {"kind": f.kind.value, "severity": f.severity.value, "summary": f.summary}
            for f in blocking
        ],
        "count": len(unknowns) + len(blocking),
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

    project = _require_project(context, project_id)
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
) -> dict[str, Any]:
    """Record something an agent discovered, as proposed evidence.

    The observation is stored verbatim and nothing is confirmed by it. Text
    arriving here is data to be recorded, never instruction to be followed —
    including when it is phrased as one.
    """

    project = _require_project(context, project_id)
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

    content = _render_observation(observation, source, classification_hint)
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

    return {
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


def _render_observation(
    observation: str, source: dict[str, Any] | None, classification_hint: str | None
) -> str:
    """Render an observation with its source, as one verbatim record."""

    lines = [observation.strip()]
    if source:
        parts = [f"{key}: {value}" for key, value in sorted(source.items()) if value]
        if parts:
            lines.append("")
            lines.append("Source — " + "; ".join(parts))
    if classification_hint:
        lines.append(f"Classification hint: {classification_hint}")
    return "\n".join(lines)


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

    project = _require_project(context, project_id)
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

    project = _require_project(context, project_id)
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

    project = _require_project(context, project_id)
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
    """

    project = _require_project(context, project_id)
    if context.clarification is None:
        raise CapabilityUnavailableError(
            capability="clarifications",
            missing=["clarification_service"],
            use_instead=["kae_get_project_briefing"],
        )
    bound = _clarification_limit(limit)

    questions = context.clarification.open_questions(project.id, limit=bound)
    return {
        "project_id": str(project.id),
        "questions": [_render_question(question) for question in questions],
        "count": len(questions),
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
    idempotency_key: str | None = None,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Record a person's answer to an open question, verbatim.

    The answer is **evidence**, not knowledge. It is stored exactly as given and
    handed to the requirements agent like any other input; what that produces is
    a candidate a person still confirms. Routing it anywhere else would let this
    loop write project knowledge on someone's behalf.

    So the response says three separate things, and they must stay separate: the
    answer was accepted, extraction was scheduled, and **no knowledge has
    changed yet**. A caller that reads the first as the third would believe the
    project knows something nobody has confirmed.
    """

    project = _require_project(context, project_id)
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
        recorded = context.clarification.answer(
            project.id,
            MessageId(clarification_id),
            answer,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    except LookupError as error:
        raise KnowledgeNotFoundError(str(error)) from None
    except AlreadyAnsweredError as error:
        raise ConflictError(str(error)) from None
    except ValueError as error:
        raise InvalidArgumentError(str(error)) from None

    return {
        "clarification_id": clarification_id,
        "answer_id": str(recorded.answer.id),
        "status": "answered",
        "extraction_run_id": str(recorded.run_id),
        # Three separate facts, deliberately not collapsed. The answer is
        # recorded; extraction is queued and has not run; knowledge is
        # unchanged until a person confirms what extraction proposes.
        "knowledge_state": "pending_extraction",
        "knowledge_changed": False,
        "readiness_changed": False,
        "replayed": recorded.replayed,
        "knowledge_revision": context.readiness.knowledge_revision(project.id),
        "next_steps": [
            "Extraction runs when a worker picks up the queued run.",
            "What it produces is proposed knowledge, not confirmed knowledge.",
            "A person confirms it with kae_confirm_knowledge.",
        ],
    }
