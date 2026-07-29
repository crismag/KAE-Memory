"""The application factory.

`create_app` takes a session factory so tests and the entrypoint construct the
same application over different databases, with no import-time connection and no
global state.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from .dependencies import (
    APP_VERSION,
    Settings,
    build_engine,
    database_status,
    migration_revision,
)
from .errors import install_error_handlers
from .routers import blueprint, readiness, workspace
from .schemas import HealthResponse

DESCRIPTION = """
Engineering memory for AI product discovery.

**This API has no authentication.** The MVP defers authentication, teams, and
roles, so it is safe only behind a network boundary (ADR-0014).

Long operations never hold a request open: enqueueing agent work returns `202`
with a durable run identifier, and the client polls the run.
"""


def create_app(
    session_factory: sessionmaker[DbSession],
    engine: Engine | None = None,
    cors_origins: Sequence[str] = (),
) -> FastAPI:
    """Return an application bound to ``session_factory``.

    ``cors_origins`` is empty by default. A browser on another origin cannot
    reach this API unless a deployment names its origin explicitly — and doing so
    exposes an API with no authentication, which ADR-0017 permits only behind a
    network allowlist.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="KAE-Memory",
        version=APP_VERSION,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.session_factory = session_factory
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            # No credentials: there are none. Allowing them would imply a session
            # or token model that does not exist (ADR-0014).
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )
    install_error_handlers(app)
    app.include_router(workspace.router)
    app.include_router(readiness.router)
    app.include_router(blueprint.router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        """FR-017. Unversioned on purpose: an operational probe should not move
        when the business contract does.

        Reports ``degraded`` rather than ``ok`` when the database is unreachable,
        and never returns a connection string — the URL contains the password.
        """

        database = database_status(session_factory)
        revision = migration_revision(session_factory) if database == "up" else None
        return HealthResponse(
            status="ok" if database == "up" else "degraded",
            database=database,
            migration_revision=revision,
            version=APP_VERSION,
        )

    return app


def app_from_environment() -> FastAPI:
    """Build the application from ``KAE_DATABASE_URL`` and friends."""

    settings = Settings.from_environment()
    engine = build_engine(settings)
    return create_app(sessionmaker(engine), engine, settings.cors_origins)
