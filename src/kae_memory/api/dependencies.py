"""Wiring: settings from the environment, one engine, services per request.

The API owns no business rules. It resolves identifiers, calls
:class:`MemoryService` or :class:`ReadinessService`, and shapes the answer. Every
invariant that makes the audit trail trustworthy stays in the application and
domain layers (ADR-0004).
"""

import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.agents import provider as embedding_provider
from kae_memory.agents.goal_judge import default_goal_judge
from kae_memory.application.actor_synthesis_service import ActorSynthesisService
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.assumption_synthesis_service import AssumptionSynthesisService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.constraint_synthesis_service import ConstraintSynthesisService
from kae_memory.application.decision_synthesis_service import DecisionSynthesisService
from kae_memory.application.deliverable_service import DeliverableService
from kae_memory.application.goal_synthesis_service import GoalSynthesisService
from kae_memory.application.ingestion_service import IngestionService
from kae_memory.application.memory_service import MemoryService
from kae_memory.application.module_service import ModuleService
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.application.project_deletion_service import ProjectDeletionService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.reconciliation_service import ReconciliationService
from kae_memory.application.requirement_synthesis_service import RequirementSynthesisService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.application.rule_synthesis_service import RuleSynthesisService
from kae_memory.application.setup_service import SetupService
from kae_memory.application.source_service import SourceService
from kae_memory.application.synthesis_service import SynthesisService
from kae_memory.application.unknown_synthesis_service import UnknownSynthesisService
from kae_memory.persistence import providers

from .errors import not_found

APP_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration, all of it from the environment (FR-018)."""

    database_url: str
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls) -> "Settings":
        """Read settings, failing loudly rather than defaulting to a wrong database."""

        # One resolver for the whole process. Provider identity is decided in
        # `persistence.providers` and nowhere else, so switching engines stays
        # configuration rather than a code change.
        database = providers.resolve()
        return cls(
            database_url=database.url,
            # Binds to loopback by default. A process that listens on every
            # interface by accident is a data breach in an API with no
            # authentication (ADR-0014).
            host=os.environ.get("KAE_API_HOST", "127.0.0.1"),
            port=int(os.environ.get("KAE_API_PORT", "8000")),
            # Empty by default, so a misconfigured split-origin deployment fails
            # closed rather than opening an unauthenticated API to any origin
            # (ADR-0017). Same-origin hosting needs none of this.
            cors_origins=tuple(
                origin.strip()
                for origin in os.environ.get("KAE_CORS_ORIGINS", "").split(",")
                if origin.strip()
            ),
        )


def build_engine(settings: Settings) -> Engine:
    """Return the engine the application will share."""

    return create_engine(settings.database_url, pool_pre_ping=True)


def migration_revision(session_factory: sessionmaker[DbSession]) -> str | None:
    """Return the applied Alembic revision, or ``None`` if unavailable.

    Read from ``alembic_version`` rather than from the migration files: FR-017
    asks what the *database* has applied, and the answer the files give is what
    someone intended, not what is true.
    """

    try:
        with session_factory() as session:
            row = session.execute(text("SELECT version_num FROM alembic_version")).first()
    except Exception:
        # A schema built by metadata rather than by Alembic has no version table.
        # Reporting "unknown" is honest; failing the health check because the
        # revision cannot be read would take a working service out of rotation.
        return None
    return None if row is None else str(row[0])


def get_memory(request: Request) -> MemoryService:
    """Return the request's memory service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return MemoryService(factory)


def get_readiness(request: Request) -> ReadinessService:
    """Return the request's readiness service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ReadinessService(factory)


def get_blueprint(request: Request) -> BlueprintService:
    """Return the request's blueprint service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return BlueprintService(factory)


def get_review(request: Request) -> ReviewService:
    """Return the request's review service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ReviewService(factory)


def get_retrieval(request: Request) -> RetrievalService:
    """Return the request's retrieval service.

    The embedder is built once at startup and reused, because building one per
    request would make every search pay provider construction, and — for a real
    provider — hide a credential failure inside an unrelated request.
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return RetrievalService(
        factory, request.app.state.embedder, embedder_name=request.app.state.embedder_name
    )


def get_ingestion(request: Request) -> IngestionService:
    """Return the request's ingestion service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return IngestionService(factory)


def get_project_deletion(request: Request) -> ProjectDeletionService:
    """Return the request's project-deletion service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ProjectDeletionService(factory)


def get_assembly(request: Request) -> AssemblyService:
    """Return the request's assembly service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return AssemblyService(factory)


def get_clarification(request: Request) -> ClarificationService:
    """Return the request's clarification service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ClarificationService(factory)


def get_classification(request: Request) -> ClassificationService:
    """Return the request's classification service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ClassificationService(factory, classifier=embedding_provider.build_classifier()[0])


def authorise_project(request: Request, project_id: str) -> None:
    """Refuse a project this principal may not read (N5).

    Deliberately a second check, after authentication and separate from it. A
    token proves who is calling; whether they may read this project is a
    different question, and answering both with one lookup is how a convenience
    quietly becomes a security control.

    A principal with no project scope may read every project — the restriction
    is opt-in, because a token scoped to nothing would authenticate and do
    nothing.
    """

    principal = getattr(request.state, "principal", None)
    if principal is None:
        return
    if not principal.may_read(project_id):
        # 404, not 403. Telling an unauthorised caller that a project exists is
        # itself a disclosure, and the two responses are indistinguishable to
        # someone who is simply wrong about the id.
        raise not_found("project", project_id)


def get_modules(request: Request) -> ModuleService:
    """Return the request's module service.

    Wired for reads only. The write path — defining a module and drawing an
    edge — stays on MCP until somebody rules who may draw an architecture
    (`D-19`).
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ModuleService(factory)


def get_sources(request: Request) -> SourceService:
    """Return the request's source service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return SourceService(factory)


def get_synthesis(request: Request) -> SynthesisService:
    """Return the request's synthesis-layer service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return SynthesisService(factory)


def get_goal_synthesis(request: Request) -> GoalSynthesisService:
    """Return the goal synthesizer, with whatever judge this deployment has.

    `None` is a supported deployment: synthesis then promotes only corroborated
    clusters and reports that it was unjudged (`D-101`).
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return GoalSynthesisService(
        factory, judge=default_goal_judge(), embedder=request.app.state.embedder
    )


def get_unknown_synthesis(request: Request) -> UnknownSynthesisService:
    """Return the unknown synthesizer, sharing the goal synthesizer's embedder.

    Both compare statements. Handing them different vector spaces would let the
    same project be compacted one way for goals and another for unknowns.
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return UnknownSynthesisService(factory, embedder=request.app.state.embedder)


def get_actor_synthesis(request: Request) -> ActorSynthesisService:
    """Return the actor synthesizer, which takes no embedder on purpose.

    The other two synthesizers share `app.state.embedder` so one project is not
    compacted in two vector spaces. Actor synthesis compares nothing: distance
    between two actor noun phrases measures shared subject matter rather than
    shared identity, which was measured before it was assumed (`D-121`).
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ActorSynthesisService(factory)


def get_decision_synthesis(request: Request) -> DecisionSynthesisService:
    """Return the decision synthesizer, which also takes no embedder.

    A decision is read one statement at a time: its class is the verb it uses,
    its scope is whether it binds beyond this conversation, and its state is
    whether a person accepted it (`D-123`). Nothing here compares two decisions,
    so there is no vector space to share.
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return DecisionSynthesisService(factory)


def get_assumption_synthesis(request: Request) -> AssumptionSynthesisService:
    """Return the assumption synthesizer, which also takes no embedder.

    An assumption is read one statement at a time: whether it is about the
    project, and what would change if it were false. Doc 05's consolidation —
    four collaboration rows becoming one area — is `SYN-3a`'s neighbourhood
    applied before candidates arrive here, and deliberately not a word-overlap
    grouper in this module, which would return four singletons (`D-135`).
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return AssumptionSynthesisService(factory)


def get_constraint_synthesis(request: Request) -> ConstraintSynthesisService:
    """Return the constraint synthesizer, which also takes no embedder.

    A boundary's reach is containment and shared terms between two statements
    (`D-124`), which is a lexical read rather than a distance. Where that read
    misses — an item answered by a constraint sharing none of its words — the
    gap is `SYN-3a`'s neighbourhood and is recorded as one, not papered over
    with a wider word list here.
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ConstraintSynthesisService(factory)


def get_requirement_synthesis(request: Request) -> RequirementSynthesisService:
    """Return the requirement synthesizer, which takes no embedder either.

    Doc 06's separations are readings of one sentence — what kind of statement
    it is, and whether a test could watch it happen — so nothing here compares
    two requirements by distance. Deduplication is the normalised wording, as it
    is everywhere else in synthesis.
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return RequirementSynthesisService(factory)


def get_rule_synthesis(request: Request) -> RuleSynthesisService:
    """Return the rule synthesizer, which takes no embedder either.

    A rule's weight comes from where it came from (`D-132`), which is a stored
    attribution rather than a distance, and its family is one ordered lexical
    read of its own wording. Nothing here compares two rules.
    """

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return RuleSynthesisService(factory)


def get_reconciliation(request: Request) -> ReconciliationService:
    """Return the request's reconciliation service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return ReconciliationService(factory)


def get_setup(request: Request) -> SetupService:
    """Return the request's preliminary setup service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return SetupService(factory)


def get_preliminary(request: Request) -> PreliminaryContextService:
    """Return the request's preliminary context service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return PreliminaryContextService(factory)


def get_assumptions(request: Request) -> AssumptionService:
    """Return the request's assumption service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return AssumptionService(factory)


def get_deliverables(request: Request) -> DeliverableService:
    """Return the request's deliverable service."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return DeliverableService(factory)


def get_session_factory(request: Request) -> sessionmaker[DbSession]:
    """Return the shared session factory."""

    factory: sessionmaker[DbSession] = request.app.state.session_factory
    return factory


def database_status(session_factory: sessionmaker[DbSession]) -> str:
    """Return ``"up"`` when a trivial query succeeds, ``"down"`` otherwise.

    A health endpoint that reports the process is alive while its only durable
    dependency is unreachable is worse than no health endpoint.
    """

    try:
        with session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - exercised only with the database down
        return "down"
    return "up"


def build_embedder(environ: dict[str, str] | None = None) -> tuple[object, str]:
    """Return the configured embedder and its name.

    Shared with the MCP server's construction rather than reimplemented, so the
    two adapters cannot end up ranking by different models — which would make
    the same query return different results depending on how it was asked.
    """

    return embedding_provider.build_embedder(environ if environ is not None else os.environ)


Memory = Annotated[MemoryService, Depends(get_memory)]
Readiness = Annotated[ReadinessService, Depends(get_readiness)]
Review = Annotated[ReviewService, Depends(get_review)]
Blueprints = Annotated[BlueprintService, Depends(get_blueprint)]
SessionFactory = Annotated["sessionmaker[DbSession]", Depends(get_session_factory)]
Retrieval = Annotated[RetrievalService, Depends(get_retrieval)]
Ingestion = Annotated[IngestionService, Depends(get_ingestion)]
ProjectDeletion = Annotated[ProjectDeletionService, Depends(get_project_deletion)]
Assembly = Annotated[AssemblyService, Depends(get_assembly)]
Clarifications = Annotated[ClarificationService, Depends(get_clarification)]
Classification = Annotated[ClassificationService, Depends(get_classification)]
Deliverables = Annotated[DeliverableService, Depends(get_deliverables)]
Assumptions = Annotated[AssumptionService, Depends(get_assumptions)]
Preliminary = Annotated[PreliminaryContextService, Depends(get_preliminary)]
Setup = Annotated[SetupService, Depends(get_setup)]
Modules = Annotated[ModuleService, Depends(get_modules)]
Sources = Annotated[SourceService, Depends(get_sources)]
Synthesis = Annotated[SynthesisService, Depends(get_synthesis)]
Reconciliation = Annotated[ReconciliationService, Depends(get_reconciliation)]
GoalSynthesis = Annotated[GoalSynthesisService, Depends(get_goal_synthesis)]
UnknownSynthesis = Annotated[UnknownSynthesisService, Depends(get_unknown_synthesis)]
ActorSynthesis = Annotated[ActorSynthesisService, Depends(get_actor_synthesis)]
DecisionSynthesis = Annotated[DecisionSynthesisService, Depends(get_decision_synthesis)]
ConstraintSynthesis = Annotated[ConstraintSynthesisService, Depends(get_constraint_synthesis)]
AssumptionSynthesis = Annotated[AssumptionSynthesisService, Depends(get_assumption_synthesis)]
RequirementSynthesis = Annotated[RequirementSynthesisService, Depends(get_requirement_synthesis)]
RuleSynthesis = Annotated[RuleSynthesisService, Depends(get_rule_synthesis)]
