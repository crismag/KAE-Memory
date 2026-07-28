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

from kae_memory.application.memory_service import MemoryService
from kae_memory.application.readiness_service import ReadinessService

APP_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration, all of it from the environment (FR-018)."""

    database_url: str
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_environment(cls) -> "Settings":
        """Read settings, failing loudly rather than defaulting to a wrong database."""

        url = os.environ.get("KAE_DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError(
                "KAE_DATABASE_URL is not set. Copy .env.example and set it, for example "
                "'cockroachdb+psycopg://user:password@host:26257/kae?sslmode=verify-full'."
            )
        return cls(
            database_url=url,
            # Binds to loopback by default. A process that listens on every
            # interface by accident is a data breach in an API with no
            # authentication (ADR-0014).
            host=os.environ.get("KAE_API_HOST", "127.0.0.1"),
            port=int(os.environ.get("KAE_API_PORT", "8000")),
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


Memory = Annotated[MemoryService, Depends(get_memory)]
Readiness = Annotated[ReadinessService, Depends(get_readiness)]
SessionFactory = Annotated["sessionmaker[DbSession]", Depends(get_session_factory)]
