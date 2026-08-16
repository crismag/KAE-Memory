"""The declared adapter capability registry (N6, ADR-0023).

ADR-0023 made HTTP and MCP peer adapters over the same application services and
said that a capability required on both and exposed by only one is a defect
rather than a roadmap item — *unless it is a declared exception*.

This is where it is declared. The register is executable: a test walks it
against the real `TOOL_DEFINITIONS` and the real FastAPI route table, in both
directions. A capability that claims an exposure it does not have fails, and —
the half that actually prevents drift — **a tool or route that is not
registered here fails too**.

That reverse check is the point. The twelve-capability gap N1 measured did not
happen because anyone decided HTTP should lack search. It happened because
nothing noticed, for five phases, that each new target landed on one adapter.
A register nobody has to remember to update is a register that describes the
past.

`EXCEPTIONS` are deliberate asymmetries, each with the reason it is one. An
exception is a decision; an absence is a defect. Keeping them in the same file,
in the same shape, is what stops the second from being filed as the first.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

_SYNTHESIS_HTTP_ONLY = (
    "Studio is the current consumer of the synthesized model and attention "
    "queue. CIE continues to write extracted evidence through existing "
    "knowledge tools until Phase 3 produces a model worth interviewing. "
    "Exposing empty synthesis collections on MCP would present a second "
    "knowledge surface agents would treat as authoritative."
)


class Exposure(StrEnum):
    """Where a capability is expected to be reachable."""

    BOTH = "both"
    """Required on HTTP and MCP. Absence on either is a defect."""

    AGENT_ONLY = "agent_only"
    """MCP only, by decision. Present on HTTP would be the defect."""

    PRODUCT_ONLY = "product_only"
    """HTTP only, by decision."""

    INTERNAL = "internal"
    """Neither. Operational or administrative, reached another way."""


@dataclass(frozen=True, slots=True)
class Capability:
    """One thing the platform can do, and where a caller may ask for it."""

    key: str
    summary: str
    exposure: Exposure
    mcp: tuple[str, ...] = ()
    http: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        asymmetric = self.exposure is not Exposure.BOTH
        if asymmetric and not self.reason:
            raise ValueError(
                f"{self.key}: an asymmetric exposure needs a reason. An exception "
                f"without one is indistinguishable from an oversight."
            )


REGISTRY: tuple[Capability, ...] = (
    Capability(
        key="project.list",
        summary="Identify the projects this environment can read",
        exposure=Exposure.BOTH,
        mcp=("kae_list_projects",),
        http=("GET /v1/projects",),
    ),
    Capability(
        key="project.create",
        summary="Create a project, idempotent by key",
        exposure=Exposure.BOTH,
        mcp=("kae_create_project",),
        http=("POST /v1/projects",),
    ),
    Capability(
        key="project.read",
        summary="Read one project's identity",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}",),
        reason=(
            "MCP answers this inside the briefing. A tool returning a name and a key "
            "would cost a round trip to learn what the next call already carries."
        ),
    ),
    Capability(
        key="knowledge.search",
        summary="Search project knowledge without loading the project",
        exposure=Exposure.BOTH,
        mcp=("kae_search_knowledge",),
        http=("GET /v1/projects/{project_id}/knowledge/search",),
    ),
    Capability(
        key="knowledge.list",
        summary="List a project's knowledge items",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/knowledge",),
        reason=(
            "An agent that loads every statement has defeated the point of a bounded "
            "context. Studio renders a review queue and legitimately needs the list."
        ),
    ),
    Capability(
        key="knowledge.confirm",
        summary=(
            "Transitional: relay a person's decision to accept an extracted "
            "candidate row. Not the attention queue (ADR-0007)."
        ),
        exposure=Exposure.BOTH,
        mcp=("kae_confirm_knowledge",),
        http=("POST /v1/knowledge/{item_id}/confirm",),
    ),
    Capability(
        key="readiness.extraction_coverage",
        summary="Report how much submitted content became knowledge",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/extraction-coverage",),
        reason=(
            "A disclosure for a person reading a coverage number, not an input "
            "to reasoning. An agent assembling context already receives what "
            "the project holds; telling it what was lost would invite it to "
            "speculate about the gap, which is the opposite of the point."
        ),
    ),
    Capability(
        key="knowledge.confirm_set",
        summary=(
            "Transitional: relay a person's single decision to accept a named "
            "set of extracted candidate rows. Not the attention queue (ADR-0007)."
        ),
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/knowledge/confirm",),
        reason=(
            "A set confirmation exists because a person was shown one reading "
            "composed of several statements and agreed to it; the set is the "
            "provenance of what they were shown. An agent has no such moment — "
            "it already holds the items and can confirm each on its own "
            "account. A bulk verb on MCP would only make it cheaper to convert "
            "a page of inference into user-confirmed knowledge in one call, "
            "which is the failure directive principle 8 exists to prevent."
        ),
    ),
    Capability(
        key="knowledge.reject",
        summary=(
            "Transitional: relay a person's decision to refuse an extracted "
            "candidate row. Not the attention queue (ADR-0007)."
        ),
        exposure=Exposure.BOTH,
        mcp=("kae_reject_knowledge",),
        http=("POST /v1/projects/{project_id}/knowledge/{item_id}/reject",),
    ),
    Capability(
        key="knowledge.correct",
        summary="Record corrected wording as a new version",
        exposure=Exposure.BOTH,
        mcp=("kae_correct_knowledge",),
        http=("POST /v1/projects/{project_id}/knowledge/{item_id}/correct",),
    ),
    Capability(
        key="knowledge.trace",
        summary="Resolve a statement to the evidence behind it",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/knowledge/{item_id}/trace",),
        reason=(
            "MCP carries provenance inside the payloads that quote a statement, so a "
            "separate trace call would return what the agent already holds."
        ),
    ),
    Capability(
        key="document.ingest",
        summary="Record a document as evidence and queue its extraction",
        exposure=Exposure.BOTH,
        mcp=("kae_ingest_document",),
        http=("POST /v1/projects/{project_id}/documents",),
    ),
    Capability(
        key="clarification.open",
        summary="Materialise the questions a project's findings justify asking",
        exposure=Exposure.BOTH,
        mcp=("kae_get_clarifications",),
        http=("POST /v1/projects/{project_id}/clarifications",),
    ),
    Capability(
        key="clarification.candidates",
        summary="List the questions a project's findings justify asking, without asking them",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/clarifications/candidates",),
        reason=(
            "The observational half of clarification.open. An agent that lists "
            "questions is about to ask one, and materialising is what gives it "
            "something to answer — so MCP wants the command. A product surface "
            "refreshes, paginates and monitors, and none of those should put a "
            "question to anybody or decide what id it gets."
        ),
    ),
    Capability(
        key="clarification.answer",
        summary="Record an answer and queue the extraction it justifies",
        exposure=Exposure.BOTH,
        mcp=("kae_answer_clarification",),
        http=("POST /v1/projects/{project_id}/clarifications/{question_id}/answer",),
    ),
    Capability(
        key="context.assemble",
        summary="Assemble a bounded context pinned to a knowledge revision",
        exposure=Exposure.BOTH,
        mcp=("kae_assemble_context",),
        http=("GET /v1/projects/{project_id}/context",),
    ),
    Capability(
        key="context.preliminary",
        summary="Compose the useful preliminary view of a project too sparse to assemble",
        exposure=Exposure.BOTH,
        mcp=("kae_get_preliminary_context",),
        http=("GET /v1/projects/{project_id}/preliminary-context",),
    ),
    Capability(
        key="setup.read",
        summary="Report what a project is configured to do, apart from what it knows",
        exposure=Exposure.BOTH,
        mcp=("kae_get_setup_state",),
        http=("GET /v1/projects/{project_id}/setup",),
    ),
    Capability(
        key="setup.questions",
        summary="List unsettled questions about configuration, not about the product",
        exposure=Exposure.BOTH,
        mcp=("kae_get_setup_questions",),
        http=("GET /v1/projects/{project_id}/setup/questions",),
    ),
    Capability(
        key="setup.configure",
        summary="Set a project's configuration — its repository, branch, kind, output format",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/setup/configuration",),
        reason=(
            "Setup is a person deciding how their project is wired. An agent "
            "that could rewrite `primary_repository` mid-run would change where "
            "the next publication goes without anybody choosing it. Reading it "
            "over MCP is right; writing it is not."
        ),
    ),
    Capability(
        key="publication.targets.register",
        summary="Register where a project may publish, and change which target is the default",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "POST /v1/projects/{project_id}/publication-targets",
            "POST /v1/projects/{project_id}/publication-targets/default",
        ),
        reason=(
            "The same reason as `setup.configure`, more sharply: this decides "
            "where bytes land. A destination an agent chose is a destination "
            "nobody authorised."
        ),
    ),
    Capability(
        key="connections.manage",
        summary="Record and authorise permission to reach a provider, never the credential",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "GET /v1/projects/{project_id}/connections",
            "POST /v1/projects/{project_id}/connections",
            "POST /v1/projects/{project_id}/connections/{connection_id}/authorization",
        ),
        reason=(
            "Granting access is an act of authorisation, and `granted` requires "
            "naming the person who gave it. An agent authorising its own reach "
            "would make that name meaningless."
        ),
    ),
    Capability(
        key="publication.targets",
        summary="List where a project may publish, and why it currently cannot",
        exposure=Exposure.BOTH,
        mcp=("kae_list_publication_targets",),
        http=("GET /v1/projects/{project_id}/publication-targets",),
    ),
    Capability(
        key="readiness.read",
        summary="Report how well understood a project is",
        exposure=Exposure.BOTH,
        mcp=("kae_get_readiness",),
        http=("GET /v1/projects/{project_id}/readiness",),
    ),
    Capability(
        key="readiness.recalculate",
        summary="Recalculate and snapshot readiness",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/readiness/calculate",),
        reason=(
            "MCP recalculates when a read finds a stale snapshot, so an agent never "
            "needs to ask. Studio drives it from a button."
        ),
    ),
    Capability(
        key="readiness.history",
        summary="Read past readiness snapshots",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/readiness/history",),
        reason="A trend is something a person looks at; an agent plans from the current figure.",
    ),
    Capability(
        key="readiness.areas",
        summary="Assign knowledge to readiness areas",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/readiness/areas",),
        reason="Template administration, not a product action an agent performs.",
    ),
    Capability(
        key="project.delete",
        summary="Remove a project and everything scoped to it",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "GET /v1/projects/{project_id}/deletion-plan",
            "DELETE /v1/projects/{project_id}",
        ),
        reason=(
            "Destructive and irreversible. An agent submitting evidence has no "
            "business removing the project it was submitted to, and the decision "
            "to delete is one a person makes after reading what would be lost."
        ),
    ),
    Capability(
        key="review.enqueue",
        summary="Queue the review pass that classifies extracted knowledge",
        exposure=Exposure.BOTH,
        mcp=("kae_enqueue_review",),
        http=("POST /v1/projects/{project_id}/review/runs",),
    ),
    Capability(
        key="review.findings",
        summary="What is missing, contested, or unresolved",
        exposure=Exposure.BOTH,
        mcp=("kae_get_project_briefing", "kae_get_open_decisions"),
        http=("GET /v1/projects/{project_id}/review",),
    ),
    Capability(
        key="blueprint.read",
        summary="Confirmed statements organised by area",
        exposure=Exposure.BOTH,
        mcp=("kae_get_project_briefing",),
        http=(
            "GET /v1/projects/{project_id}/blueprint",
            "GET /v1/projects/{project_id}/blueprint.md",
        ),
    ),
    Capability(
        key="blocker.manage",
        summary="Raise and resolve blockers",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "GET /v1/projects/{project_id}/blockers",
            "POST /v1/projects/{project_id}/blockers",
            "POST /v1/projects/{project_id}/blockers/{blocker_id}/resolve",
        ),
        reason=(
            "An agent reports a blocker as an observation and a person decides it is "
            "one. Letting an agent raise one directly would put an unreviewed claim "
            "into the register that gates readiness."
        ),
    ),
    Capability(
        key="contradiction.manage",
        summary="Record and resolve contradictions",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "POST /v1/projects/{project_id}/contradictions",
            "POST /v1/projects/{project_id}/contradictions/{relationship_id}/resolve",
        ),
        reason=(
            "Same as blockers: resolution is a human ruling, and ADR-0015 gates readiness on it."
        ),
    ),
    Capability(
        key="observation.submit",
        summary="Record something an agent discovered, as proposed evidence",
        exposure=Exposure.AGENT_ONLY,
        mcp=("kae_submit_observation",),
        reason=(
            "Studio's equivalent is a conversation message, which is a different "
            "durable act with its own session ordering. Offering both over HTTP "
            "would give a client two ways to say one thing."
        ),
    ),
    Capability(
        key="observation.classifications",
        summary="Read classified spans of submitted observations",
        exposure=Exposure.BOTH,
        mcp=("kae_get_classifications",),
        http=("GET /v1/projects/{project_id}/classifications",),
    ),
    Capability(
        key="operational.read",
        summary="Where the work stands, as reported",
        exposure=Exposure.BOTH,
        mcp=("kae_get_operational_state",),
        http=("GET /v1/projects/{project_id}/operational-state",),
    ),
    Capability(
        key="operational.settle",
        summary="Relay a person's decision about a reported operational record",
        exposure=Exposure.BOTH,
        mcp=("kae_settle_operational_record",),
        http=("POST /v1/projects/{project_id}/operational-state/{record_id}/settle",),
    ),
    Capability(
        key="source.reference",
        summary="Where a project's material comes from, and what revision was pinned",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "POST /v1/projects/{project_id}/sources",
            "GET /v1/projects/{project_id}/sources",
            "GET /v1/projects/{project_id}/sources/{source_id}",
            "POST /v1/projects/{project_id}/sources/{source_id}/state",
            "POST /v1/projects/{project_id}/sources/{source_id}/pin",
            "POST /v1/projects/{project_id}/sources/{source_id}/disposition",
        ),
        reason=(
            "Acquisition is Studio's (ADR-0005) and this is the durable half of it: "
            "Studio contacts the provider, resolves a revision, and records what it "
            "was told. An agent reads the evidence a source produced, not the "
            "configuration that produced it — and a tool that registered sources "
            "would be a second party configuring a project nobody asked it to."
        ),
    ),
    Capability(
        key="module.context",
        summary="Implementation context for one module",
        exposure=Exposure.AGENT_ONLY,
        mcp=("kae_get_module_context",),
        reason=(
            "The consumer is a coding agent implementing one module. Studio renders "
            "the module graph rather than a bounded implementation package, and will "
            "need an HTTP contract when it renders the package itself (N12)."
        ),
    ),
    Capability(
        key="module.define",
        summary="Register a module as a proposed part of the system",
        exposure=Exposure.AGENT_ONLY,
        mcp=("kae_define_module",),
        reason=(
            "Modules are proposed by extraction and confirmed by a person. Studio's "
            "curation flow is recordModuleDecision, which is a different act with "
            "its own contract still to be reconciled (N12)."
        ),
    ),
    Capability(
        key="module.relate",
        summary="Record a structural edge between modules, or to a statement",
        exposure=Exposure.AGENT_ONLY,
        mcp=("kae_relate_modules",),
        reason=(
            "The write path that was missing entirely. Same reason as module.define: "
            "Studio's structural editing contract is unreconciled, and a route "
            "written now would fix a shape that discussion has not settled."
        ),
    ),
    Capability(
        key="module.graph",
        summary="Every module, every edge, and the order they can be built in",
        exposure=Exposure.BOTH,
        mcp=("kae_get_module_graph",),
        http=(
            "GET /v1/projects/{project_id}/modules",
            "GET /v1/projects/{project_id}/modules/graph",
            "GET /v1/projects/{project_id}/modules/{key}",
        ),
        # This was `agent_only`, reasoned: *"a Studio view of the same graph is
        # a rendering question, and rendering is Studio's."* True, and it does
        # not follow — rendering being Studio's is exactly why Studio needs the
        # data, and the sentence read as a decision because it was one (`D-19`).
        #
        # What it produced: an agent connected over MCP could read a project's
        # architecture and the person who owns the project could not, and
        # `/dependencies` was empty on every deployment for want of a route.
        #
        # Reads only. `module.define` and `module.relate` stay agent-only for
        # the reason they always did: Studio's structural editing contract is
        # unreconciled, and a route written now would fix a shape discussion
        # has not settled.
    ),
    Capability(
        key="session.manage",
        summary="Open, close, and read conversation sessions",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "POST /v1/projects/{project_id}/sessions",
            "GET /v1/projects/{project_id}/sessions",
            "POST /v1/sessions/{session_id}/close",
            "GET /v1/sessions/{session_id}/messages",
            "POST /v1/sessions/{session_id}/messages",
        ),
        reason=(
            "ADR-0006 gives Memory durable conversation and Studio the interview. An "
            "agent submits observations rather than holding a session."
        ),
    ),
    Capability(
        key="run.manage",
        summary="Enqueue agent work and follow its progress",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "POST /v1/projects/{project_id}/runs",
            "GET /v1/projects/{project_id}/runs",
            "GET /v1/runs/{run_id}",
            "GET /v1/runs/{run_id}/events",
            "GET /v1/runs/{run_id}/knowledge",
        ),
        reason=(
            "Studio shows progress. An agent that *is* the work does not submit runs "
            "to itself, and a tool that let it would invite recursion nobody bounded."
        ),
    ),
    Capability(
        key="deliverable.record",
        summary="Record an assembled output as a durable deliverable",
        exposure=Exposure.BOTH,
        mcp=("kae_record_deliverable",),
        http=("POST /v1/projects/{project_id}/deliverables",),
    ),
    Capability(
        key="deliverable.list",
        summary="Recorded deliverables, newest first, with derived staleness",
        exposure=Exposure.BOTH,
        mcp=("kae_list_deliverables",),
        http=("GET /v1/projects/{project_id}/deliverables",),
    ),
    Capability(
        key="deliverable.read",
        summary="One deliverable's manifest, artifact index, and lifecycle",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/deliverables/{deliverable_id}",),
        reason=(
            "An agent that recorded a deliverable already holds its payload. "
            "Studio resolves one from a stored id when a person opens it later."
        ),
    ),
    Capability(
        key="deliverable.lifecycle",
        summary="Supersede or withdraw a recorded deliverable",
        exposure=Exposure.PRODUCT_ONLY,
        http=(
            "POST /v1/projects/{project_id}/deliverables/{deliverable_id}/supersede",
            "POST /v1/projects/{project_id}/deliverables/{deliverable_id}/withdraw",
        ),
        reason=(
            "Withdrawing what a project stands behind is a person's judgement, and "
            "an agent that could do it would be settling a question nobody asked it."
        ),
    ),
    Capability(
        key="assumption.record",
        summary="Record what KAE proceeded on in place of missing information",
        exposure=Exposure.BOTH,
        mcp=("kae_record_assumption",),
        http=("POST /v1/projects/{project_id}/assumptions",),
    ),
    Capability(
        key="assumption.list",
        summary="What a project is proceeding on without knowing",
        exposure=Exposure.BOTH,
        mcp=("kae_list_assumptions",),
        http=("GET /v1/projects/{project_id}/assumptions",),
    ),
    Capability(
        key="assumption.accept",
        summary="Relay a person taking responsibility for an assumption",
        exposure=Exposure.BOTH,
        mcp=("kae_accept_assumption",),
        http=("POST /v1/projects/{project_id}/assumptions/{assumption_id}/accept",),
    ),
    Capability(
        key="synthesis.model.list",
        summary="Read the synthesized project model (empty until a synthesizer runs)",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/model",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.model.put",
        summary="Create or update a working-model object, idempotent by identity",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.model.get",
        summary="Read one synthesized object and the evidence it is mapped to",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/model/{object_id}",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.model.correct",
        summary="Record a person's wording as the authoritative synthesized object",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model/{object_id}/correct",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.model.bind_evidence",
        summary="Map a synthesized object onto an extracted row without deleting it",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model/{object_id}/evidence",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.evidence.role",
        summary="Set how an extracted row participates in reasoning",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/knowledge/{item_id}/evidence-role",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.attention.list",
        summary="Read the human-attention queue (not unconfirmed extraction)",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/attention",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.attention.put",
        summary="Create an attention item; extraction must not call this",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/attention",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.attention.resolve",
        summary="Close an attention item so it leaves the live queue",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/attention/{item_id}/resolve",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.goals.run",
        summary="Cluster goal evidence into the project's goal model",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model/goals/runs",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.actors.run",
        summary="Turn actor evidence into the project's role and responsibility model",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model/actors/runs",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.actors.responsibilities",
        summary="Read who is Responsible or Accountable for each subject",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/model/actors/responsibilities",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.decisions.run",
        summary="Turn decision evidence into the project's proposals and settled choices",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model/decisions/runs",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.unknowns.run",
        summary="Turn current unknowns into themes and raise the material few",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/model/unknowns/runs",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.reconciliation.record",
        summary="Record an idempotent reconciliation or human-act change event",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/reconciliation/events",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.reconciliation.list",
        summary="List recorded reconciliation and human-act change events",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/reconciliation/events",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.reconciliation.run",
        summary="Run deterministic evidence-graph reconciliation without minting a model",
        exposure=Exposure.PRODUCT_ONLY,
        http=("POST /v1/projects/{project_id}/reconciliation/runs",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="synthesis.reconciliation.neighborhood",
        summary="Read bounded related evidence for later LLM context",
        exposure=Exposure.PRODUCT_ONLY,
        http=("GET /v1/projects/{project_id}/reconciliation/neighborhoods/{item_id}",),
        reason=_SYNTHESIS_HTTP_ONLY,
    ),
    Capability(
        key="embedding.reembed",
        summary="Migrate stored knowledge to a new embedding version",
        exposure=Exposure.INTERNAL,
        reason=(
            "Long-running, restartable, and destructive to get wrong. Driven by "
            "scripts/development/reembed-knowledge.py, where it can be resumed."
        ),
    ),
)


def by_key(key: str) -> Capability:
    """Return one capability, or raise if it is not registered."""

    for capability in REGISTRY:
        if capability.key == key:
            return capability
    raise KeyError(f"no capability {key!r} in the registry")


def declared_mcp_tools() -> frozenset[str]:
    """Every MCP tool the registry accounts for."""

    return frozenset(tool for capability in REGISTRY for tool in capability.mcp)


def declared_http_routes() -> frozenset[str]:
    """Every HTTP route the registry accounts for, as ``METHOD /path``."""

    return frozenset(route for capability in REGISTRY for route in capability.http)
