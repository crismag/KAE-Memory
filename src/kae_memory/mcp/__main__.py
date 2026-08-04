"""``kae-memory-mcp`` — serve over STDIO, or diagnose why it cannot.

``doctor`` exists because a failing MCP server gives a client almost nothing to
report. It checks the same things the server needs, in the order the server
needs them, and prints no secrets: a database URL is reported as reachable or
not, never echoed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from kae_memory import config as database_config
from kae_memory.mcp.server import (
    RESOURCE_DEFINITIONS,
    TOOL_DEFINITIONS,
    build_context,
    configure_logging,
    serve,
)

OK = "ok"
FAIL = "fail"
WARN = "warn"


def _line(state: str, label: str, detail: str = "") -> str:
    mark = {OK: "PASS", FAIL: "FAIL", WARN: "WARN"}[state]
    return f"[{mark}] {label}" + (f" — {detail}" if detail else "")


def _redacted_target(url: str) -> str:
    """Describe a database URL without disclosing it.

    Host and database name are enough to diagnose a misconfiguration. The
    password never is.
    """

    try:
        from sqlalchemy.engine import make_url

        parsed = make_url(url)
        host = parsed.host or "?"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.get_backend_name()} {host}{port}/{parsed.database or '?'}"
    except Exception:
        return "unparseable URL"


def _migration_state(url: str) -> tuple[str, str]:
    """Report whether the schema is at the revision this code expects.

    A reachable database is not a migrated one. Reporting "ready to serve"
    while a migration is half-applied sends the client to discover the problem
    as a tool failure, which is the least useful place to find it.
    """

    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        root = Path(__file__).resolve().parents[3]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "migrations"))
        expected = ScriptDirectory.from_config(config).get_current_head()

        # Alembic's own API, not a query written here: the adapter states its
        # schema expectation through the tool that owns migrations.
        engine = create_engine(url)
        with engine.connect() as connection:
            applied = MigrationContext.configure(connection).get_current_revision()

        if applied is None:
            return FAIL, "no migrations applied — run 'alembic upgrade head'"
        if applied != expected:
            return FAIL, f"at {applied}, expected {expected} — run 'alembic upgrade head'"
        return OK, f"at {applied}"
    except Exception as exception:
        return FAIL, f"could not determine migration state ({type(exception).__name__})"


def _provider_name() -> str:
    """Name the selected provider for a diagnostic, without assuming one."""

    try:
        return database_config.resolve_provider().value
    except database_config.ProviderConfigurationError:
        return "database"


def doctor() -> int:
    """Report whether this environment can serve, and exit non-zero if not."""

    checks: list[str] = []
    failed = False

    url: str | None = None
    try:
        database = database_config.resolve()
        url = database.url
        described = database.describe()
        checks.append(_line(OK, "database provider", described["database_provider"]))
        checks.append(_line(OK, "vector provider", described["vector_provider"]))
        checks.append(_line(OK, "connection", _redacted_target(url)))
    except database_config.ProviderConfigurationError as error:
        # Named rather than guessed. A doctor that reported a working default
        # would be diagnosing a deployment nobody configured.
        checks.append(_line(FAIL, "database provider", str(error)))
        failed = True

    environment = os.environ.get("KAE_ENVIRONMENT", "local")
    checks.append(_line(OK, "KAE_ENVIRONMENT", environment))

    context = None
    if url:
        try:
            context = build_context(url)
            checks.append(_line(OK, "application services", "initialised"))
        except Exception as exception:
            checks.append(_line(FAIL, "application services", type(exception).__name__))
            failed = True

    if context is not None:
        try:
            projects = context.memory.list_projects()
            checks.append(_line(OK, "database reachable", f"{len(projects)} project(s) readable"))
            if not projects:
                checks.append(
                    _line(
                        WARN,
                        "project data",
                        "no projects exist — tools will return empty results",
                    )
                )
        except Exception as exception:
            checks.append(
                _line(
                    FAIL,
                    "database reachable",
                    f"{type(exception).__name__} — is the configured "
                    f"{_provider_name()} running, and are migrations applied?",
                )
            )
            failed = True

    if context is not None and url:
        state, detail = _migration_state(url)
        checks.append(_line(state, "migrations", detail))
        if state == FAIL:
            failed = True

    if context is not None:
        checks.append(
            _line(
                WARN if not context.semantic_ranking else OK,
                "embedder",
                f"{context.embedder_name}"
                + (
                    " — hash-derived; search ordering is not semantic relevance"
                    if not context.semantic_ranking
                    else ""
                ),
            )
        )

    checks.append(_line(OK, "tools", f"{len(TOOL_DEFINITIONS)} enumerated"))
    checks.append(_line(OK, "resources", f"{len(RESOURCE_DEFINITIONS)} enumerated"))
    checks.append(_line(OK, "prompts", "1 enumerated (kae.prepare-implementation)"))
    checks.append(
        _line(
            WARN,
            "module context",
            "reports capability_unavailable by design — modules are not yet modelled",
        )
    )

    print("kae-memory-mcp doctor", file=sys.stderr)
    for check in checks:
        print(check, file=sys.stderr)
    print(
        "\n" + ("not ready to serve" if failed else "ready to serve"),
        file=sys.stderr,
    )
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``kae-memory-mcp`` command."""

    parser = argparse.ArgumentParser(
        prog="kae-memory-mcp",
        description="KAE-Memory MCP server (stdio transport).",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve", "doctor"],
        help="serve over stdio (default), or diagnose the environment",
    )
    arguments = parser.parse_args(argv)

    configure_logging()

    if arguments.command == "doctor":
        return doctor()

    asyncio.run(serve())
    return 0


def _run() -> Any:
    raise SystemExit(main())


if __name__ == "__main__":
    _run()
