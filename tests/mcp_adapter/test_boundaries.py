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
from typing import Any

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
        env={
            "PATH": "/usr/bin:/bin",
            "KAE_DATABASE_PROVIDER": "cockroachdb",
            "KAE_DATABASE_URL": secret_url,
        },
    )

    assert completed.stdout == "", "doctor writes to stderr; stdout belongs to the protocol"
    assert "hunter2" not in completed.stderr
    assert "cockroachdb" in completed.stderr, "the backend is safe to report"


def test_doctor_fails_without_a_configured_provider() -> None:
    """Naming the provider is the first thing a deployment must do.

    Previously this asserted on the connection URL. Selection now comes first:
    a URL without a provider says where to connect and not what to expect
    there, and the doctor refuses rather than guessing (ADR-0022).
    """

    completed = subprocess.run(
        [sys.executable, "-m", "kae_memory.mcp", "doctor"],
        capture_output=True,
        text=True,
        timeout=180,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert completed.returncode == 1
    assert "KAE_DATABASE_PROVIDER" in completed.stderr
    assert "not ready to serve" in completed.stderr


# -- surface shape ---------------------------------------------------------


def test_the_tool_surface_stays_small() -> None:
    """A large surface degrades agent behaviour and couples clients.

    Twenty-six tools, and the list is enumerated rather than counted so that
    adding one is a deliberate edit here. `kae_create_project` was added because an
    agent could submit an observation about a project but could not bring one
    into being, which made the surface unusable without a second channel. The
    three review tools arrived in T12 to T14 — see the write-surface test below
    for what that cost. `kae_get_clarifications` arrived in T16,
    `kae_answer_clarification` in T17, and Phase E added `kae_ingest_document`
    and `kae_assemble_context`.

    N4 added three, and the count is the argument for having added them. T24
    shipped classification with a write path and no read or review path: spans
    and operational records were reachable only through the briefing, and four
    states the domain models were reachable by nothing at all. Two filtered
    reads and one settle command are the smallest surface that closes it.

    N17-N19 added three more, and they replaced a refusal rather than adding
    reach: `kae_get_module_context` had reported a capability gap since T1
    because modules had no model, no edges, and no traversal. Defining a
    module, relating it, and reading the graph are what that gap was made of.

    N20 added two: recording an assembled output as a durable deliverable, and
    listing what was recorded. Neither renders or publishes anything — an
    assembly is a computation whose id is fresh per call, and a deliverable is
    the durable record that the output existed.

    N45 added three. The assumption model shipped with N35 and no adapter
    reached it, which is how "I do not know yet, choose something reasonable"
    had nowhere to go — the third no-caller gap in this repository, and the one
    manual testing hit twice.

    N44 added one, and it is a genuinely different question rather than a
    variant of `kae_assemble_context`. That tool answers "what has this project
    settled", which for a project described in one sentence is "nothing".
    Preliminary context answers "what is the most useful thing you can say
    anyway", and the two must not be one tool: an assembly that quietly
    included guesses would be the failure this repository spends most of its
    invariants preventing.
    """

    assert len(TOOL_DEFINITIONS) == 27
    names = {definition["name"] for definition in TOOL_DEFINITIONS}
    assert names == {
        "kae_create_project",
        "kae_list_projects",
        "kae_get_project_briefing",
        "kae_get_module_context",
        "kae_get_preliminary_context",
        "kae_search_knowledge",
        "kae_get_open_decisions",
        "kae_get_readiness",
        "kae_record_assumption",
        "kae_list_assumptions",
        "kae_accept_assumption",
        "kae_record_deliverable",
        "kae_list_deliverables",
        "kae_define_module",
        "kae_relate_modules",
        "kae_get_module_graph",
        "kae_get_operational_state",
        "kae_get_classifications",
        "kae_settle_operational_record",
        "kae_submit_observation",
        "kae_confirm_knowledge",
        "kae_reject_knowledge",
        "kae_ingest_document",
        "kae_assemble_context",
        "kae_correct_knowledge",
        "kae_get_clarifications",
        "kae_answer_clarification",
    }


def test_the_write_surface_is_named_and_small() -> None:
    """Seven writes. Three decide, and one does not look like a write at all.

    This test previously asserted that *no* tool here could confirm anything:
    with confirmation absent from the surface, FR-005 held structurally and an
    agent could not violate it. Phase C required exposing confirmation to MCP,
    so that guarantee is gone and cannot be recovered by wording.

    What replaces it is attribution, checked below: the surface may relay a
    human decision but may never originate one anonymously.
    """

    writers = {
        "kae_create_project",
        "kae_submit_observation",
        "kae_confirm_knowledge",
        "kae_reject_knowledge",
        "kae_correct_knowledge",
        "kae_get_clarifications",
        "kae_answer_clarification",
    }
    names = {d["name"] for d in TOOL_DEFINITIONS}

    assert writers == {d["name"] for d in TOOL_DEFINITIONS if _is_write(d)}
    assert writers <= names


def test_a_confirmation_must_name_the_person_who_made_it() -> None:
    """The residual protection after FR-005 stopped being structural.

    An agent that has not been told who is confirming cannot supply `reviewer`,
    so it cannot record "a person confirmed this" on its own initiative. The
    audit trail never carries an unattributed human decision.
    """

    deciding = [
        d
        for d in TOOL_DEFINITIONS
        if any(token in d["name"] for token in ("confirm", "reject", "correct"))
    ]
    assert deciding, "the review tools are expected to exist from T12 onward"
    for definition in deciding:
        required = definition["inputSchema"]["required"]
        assert "reviewer" in required, definition["name"]
        assert "expected_version" in required, definition["name"]


def test_no_tool_approves_or_confirms_without_review() -> None:
    """Bulk and blanket approval stay off the surface entirely.

    One item, one named reviewer, one version. A tool that confirmed many items
    at once would make the reviewer's attention unverifiable, which is the thing
    the attribution requirement is protecting.
    """

    for definition in TOOL_DEFINITIONS:
        name = definition["name"]
        assert "approve" not in name, name
        assert not name.endswith("_all"), name
        if any(token in name for token in ("confirm", "reject", "correct")):
            properties = definition["inputSchema"]["properties"]
            assert "knowledge_id" in properties, name
            assert "knowledge_ids" not in properties, name


def _is_write(definition: dict[str, Any]) -> bool:
    """Whether a tool changes durable state."""

    return any(
        token in definition["name"]
        # `clarifications` is here because kae_get_clarifications records the
        # questions it returns. A `get_` that writes is a trap for anyone
        # reasoning about which calls are safe to retry, so it is declared.
        for token in (
            "create",
            "submit",
            "confirm",
            "reject",
            "correct",
            "clarifications",
            "answer",
        )
    )


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


def test_every_declared_tool_is_actually_registered(factory: sessionmaker[Session]) -> None:
    """Declaring a tool is not the same as serving it.

    `kae_create_project` was declared in TOOL_DEFINITIONS, given a wrapper, and
    routed in `dispatch` — and never reached a client, because the registration
    list was maintained by hand and did not include it. Every other test reaches
    the handlers through `dispatch`, which does not come through `build_server`,
    so nothing caught it.
    """

    readiness = ReadinessService(factory)
    readiness.install_template()
    context = tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
    )

    server = build_server(context)

    registered = {tool.name for tool in server._tool_manager.list_tools()}
    declared = {definition["name"] for definition in TOOL_DEFINITIONS}
    assert registered == declared


def test_a_rejection_must_record_why() -> None:
    """A rejected statement stays readable forever.

    Without the reason, a later reader has the record and not the meaning: they
    cannot tell a factual error from a scope decision, and those call for
    entirely different follow-ups.
    """

    rejecting = [d for d in TOOL_DEFINITIONS if "reject" in d["name"]]
    assert rejecting, "the rejection tool is expected to exist from T13 onward"
    for definition in rejecting:
        assert "reason_code" in definition["inputSchema"]["required"], definition["name"]


def test_a_read_named_tool_that_writes_says_so() -> None:
    """`kae_get_clarifications` records the questions it returns.

    A `get_` that mutates is a trap for anyone reasoning about which calls are
    safe to retry or to run speculatively. It is allowed here because derived
    clarifications have no identity and an unanswerable question is useless —
    but the description has to admit it, not bury it.
    """

    definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_get_clarifications")
    description = definition["description"].lower()

    assert "record" in description, "a mutating read must declare the mutation"
