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
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.deliverable_service import DeliverableService
from kae_memory.application.ingestion_service import IngestionService
from kae_memory.application.memory_service import MemoryService
from kae_memory.application.module_service import ModuleService
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.application.project_deletion_service import ProjectDeletionService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.application.setup_service import SetupService
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
