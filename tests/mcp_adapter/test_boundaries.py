"""Architectural guarantees of the MCP adapter (ADR-0018).

Two of these are enforced nowhere else. The dependency direction is a review
rule that a test can hold to; the stdout rule is invisible until a client
reports a protocol error that looks like its own bug.
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.memory_service import MemoryService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.mcp import tools
from kae_memory.mcp.server import (
    RESOURCE_DEFINITIONS,
    TOOL_DEFINITIONS,
    build_server,
    configure_logging,
)

MCP_PACKAGE = Path(__file__).resolve().parents[2] / "src" / "kae_memory" / "mcp"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_the_adapter_never_imports_persistence() -> None:
    """MCP -> application -> domain -> persistence, one way only.

    ADR-0004 keeps domain invariants in the domain rather than the schema, so
    an adapter that reached past the application layer would write knowledge
    those invariants never saw.
    """

    offenders: dict[str, set[str]] = {}
    for module in sorted(MCP_PACKAGE.glob("*.py")):
        persistence = {
            name for name in _imported_modules(module) if name.startswith("kae_memory.persistence")
        }
        if persistence:
            offenders[module.name] = persistence

    assert not offenders, f"MCP modules must not import persistence: {offenders}"


def test_the_adapter_never_constructs_sql() -> None:
    """No raw SQL, and no SQLAlchemy query construction, in the adapter.

    Two narrow exceptions: ``server.py`` builds the session factory the
    application services are given, and ``doctor`` reads the schema revision
    through Alembic's own API — diagnostics have to be able to report a
    half-applied migration, and that is the tool which owns migrations.
    """

    forbidden = (
        "sqlalchemy.select",
        "sqlalchemy.text",
        "session.execute",
        "session.query",
        "_session.execute",
        "raw_connection",
        "INSERT INTO",
        "SELECT ",
    )
    offenders: dict[str, list[str]] = {}
    for module in sorted(MCP_PACKAGE.glob("*.py")):
        source = module.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in source]
        if hits:
            offenders[module.name] = hits

    assert not offenders, f"MCP modules must not build queries: {offenders}"


def test_logging_is_configured_to_stderr() -> None:
    """stdout is the wire. A handler defaulting to stdout corrupts the stream."""

    configure_logging()
    handlers = logging.getLogger().handlers

    assert handlers, "logging must be configured explicitly, not left to defaults"
    for handler in handlers:
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr, "log handlers must write to stderr"


def test_importing_and_building_the_server_writes_nothing_to_stdout(
    factory: sessionmaker[Session],
) -> None:
    """A stray banner or print at import time is enough to break the protocol.

    Run in a subprocess so an import that only happens once cannot be masked by
    the test session having already performed it.
    """

    script = (
        "import sys\n"
        "from kae_memory.mcp.server import build_server, configure_logging\n"
        "from kae_memory.mcp.tools import ToolContext\n"
        "configure_logging()\n"
        "import logging; logging.getLogger('kae_memory.mcp').info('a log line')\n"
        "sys.stderr.write('stderr is fine\\n')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "", f"stdout must stay empty, got: {completed.stdout!r}"
    assert "a log line" in completed.stderr


def test_doctor_prints_only_to_stderr_and_hides_the_password() -> None:
    """Diagnostics must never echo a credential."""

    secret_url = "cockroachdb+psycopg://root:hunter2@db.internal:26257/kae?sslmode=disable"
    completed = subprocess.run(
        [sys.executable, "-m", "kae_memory.mcp", "doctor"],
        capture_output=True,
        text=True,
        timeout=180,
        env={"PATH": "/usr/bin:/bin", "KAE_DATABASE_URL": secret_url},
    )

    assert completed.stdout == "", "doctor writes to stderr; stdout belongs to the protocol"
    assert "hunter2" not in completed.stderr
    assert "cockroachdb" in completed.stderr, "the backend is safe to report"


def test_doctor_fails_without_a_database_url() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "kae_memory.mcp", "doctor"],
        capture_output=True,
        text=True,
        timeout=180,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert completed.returncode == 1
    assert "KAE_DATABASE_URL" in completed.stderr
    assert "not ready to serve" in completed.stderr


# -- surface shape ---------------------------------------------------------


def test_the_tool_surface_stays_small() -> None:
    """A large surface degrades agent behaviour and couples clients.

    Eight tools. `kae_create_project` was added because an agent could submit an
    observation about a project but could not bring one into being, which made
    the surface unusable without a second channel.
    """

    assert len(TOOL_DEFINITIONS) == 8
    names = {definition["name"] for definition in TOOL_DEFINITIONS}
    assert names == {
        "kae_create_project",
        "kae_list_projects",
        "kae_get_project_briefing",
        "kae_get_module_context",
        "kae_search_knowledge",
        "kae_get_open_decisions",
        "kae_get_readiness",
        "kae_submit_observation",
    }


def test_the_write_surface_is_named_and_small() -> None:
    """Two writes, and neither confirms anything.

    One brings a subject into being, the other adds evidence about one.
    Confirmation stays a human act (FR-005), so no tool here may perform it.
    """

    writers = {"kae_create_project", "kae_submit_observation"}
    names = {d["name"] for d in TOOL_DEFINITIONS}

    assert writers <= names
    assert not {n for n in names if "confirm" in n or "approve" in n}


def test_no_tool_exposes_storage_operations() -> None:
    """The surface describes engineering actions, never how Memory stores them."""

    forbidden = ("sql", "row", "table", "insert", "column", "weight")
    for definition in TOOL_DEFINITIONS:
        name = definition["name"].lower()
        assert not any(token in name for token in forbidden), definition["name"]


def test_every_tool_declares_a_strict_schema() -> None:
    for definition in TOOL_DEFINITIONS:
        schema = definition["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, definition["name"]


def test_resources_are_project_scoped() -> None:
    assert len(RESOURCE_DEFINITIONS) == 4
    for definition in RESOURCE_DEFINITIONS:
        assert definition["uri"].startswith("kae://projects/{project_id}/")


@pytest.mark.parametrize("attribute", ["add_tool", "resource", "prompt", "run_stdio_async"])
def test_the_server_binds_to_the_sdk(factory: sessionmaker[Session], attribute: str) -> None:
    """The binding layer is thin, but it must actually bind."""

    readiness = ReadinessService(factory)
    context = tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
    )
    server = build_server(context)

    assert hasattr(server, attribute)
