"""The KAE MCP server (ADR-0018).

Local STDIO transport. One process per client, started by the client.

**stdout is the wire.** Under STDIO transport a stray ``print``, a library
banner, or a logging handler that defaults to stdout corrupts the JSON-RPC
stream, and the failure looks like a client bug rather than a stray write.
Logging is configured to stderr explicitly at startup rather than relying on
defaults, and nothing in this package writes to stdout directly.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.agents import provider
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.memory_service import MemoryService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.mcp import response_policy, tools
from kae_memory.mcp.errors import safe_error

LOGGER = logging.getLogger("kae_memory.mcp")

SERVER_NAME = "kae-memory"
SERVER_INSTRUCTIONS = """\
KAE-Memory is the authoritative record of what this project durably knows.

Read the project briefing before planning. Open decisions are unresolved by a
person, not by you: if one blocks the work, report it and stop rather than
choosing an answer on the project's behalf.

Anything you submit is recorded as proposed evidence. It is not confirmed
knowledge, and submitting it does not change the project definition.

Where a response names a capability as unavailable, that is a real gap in this
version. Do not infer the missing information.
"""


def configure_logging() -> None:
    """Send logs to stderr. stdout belongs to the protocol."""

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("KAE_LOG_LEVEL", "INFO").upper())


def database_url() -> str:
    """Resolve the database URL from the existing configuration mechanism.

    The same variable the API and worker read. A second configuration format
    for MCP would be one more thing to get wrong in a client config file.
    """

    url = os.environ.get("KAE_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "KAE_DATABASE_URL is not set. Supply it in the MCP client's server "
            "configuration, the same value the API and worker use."
        )
    return url


def build_context(url: str | None = None) -> tools.ToolContext:
    """Construct the application services this server adapts."""

    engine = create_engine(url or database_url(), pool_pre_ping=True)
    factory = sessionmaker(engine)
    embedder, name = provider.build_embedder(os.environ)
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=ReadinessService(factory),
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, embedder),
        embedder_name=name,
        response_policy=response_policy.from_environment(os.environ),
    )


# -- tool surface ----------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "kae_list_projects",
        "description": "List the KAE projects this environment can read.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kae_create_project",
        "description": (
            "Create a project. Only a name is required; the key is derived from "
            "it. Idempotent by key — creating twice returns the existing project "
            "with created=false rather than failing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "key": {
                    "type": "string",
                    "description": "Optional. Derived from the name when omitted.",
                },
                "description": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_get_project_briefing",
        "description": (
            "Current understanding of one project: confirmed statements by area, "
            "readiness, open questions, and the knowledge revision. Read this "
            "before planning implementation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "profile": {"type": "string", "enum": ["economy", "regular", "detailed"]},
                "detail": {
                    "type": "string",
                    "enum": ["summary", "standard", "diagnostic"],
                    "description": (
                        "summary omits statements and arithmetic; standard adds "
                        "statements; diagnostic adds the readiness explanation."
                    ),
                },
                "prose": {"type": "string", "enum": ["none", "minimal", "concise", "standard"]},
                "max_output_tokens": {"type": "integer", "minimum": 1},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_get_module_context",
        "description": (
            "Implementation context for one module. Reports a structured "
            "capability gap in this version — modules are not yet modelled."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}, "module": {"type": "string"}},
            "required": ["project_id", "module"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_search_knowledge",
        "description": (
            "Search project knowledge without loading the whole project. "
            "Lexical mode matches the query's terms and word families with no "
            "embedding model involved; semantic mode ranks by meaning and needs "
            "a real embedder. The response names the mode that ran, labels each "
            "result's relevance, and warns when semantic ranking is unavailable."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "lexical", "semantic"],
                    "description": (
                        "auto falls back to lexical whenever the active embedder "
                        "cannot rank meaning."
                    ),
                },
                "diagnostics": {
                    "type": "boolean",
                    "description": (
                        "Include vector distances, coverage scores, and the "
                        "embedded text alongside the normal result."
                    ),
                },
            },
            "required": ["project_id", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_get_open_decisions",
        "description": "Unresolved questions and findings that could affect the work.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_get_readiness",
        "description": (
            "Readiness for the scope this version can compute. Project scope "
            "only; the response says so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_submit_observation",
        "description": (
            "Record something discovered while inspecting or implementing, as "
            "proposed evidence. Nothing is confirmed by this call. Requires an "
            "idempotency_key so a retry cannot duplicate evidence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "observation": {"type": "string"},
                "idempotency_key": {"type": "string", "maxLength": 200},
                "source": {"type": "object", "additionalProperties": True},
                "classification_hint": {"type": "string"},
            },
            "required": ["project_id", "observation", "idempotency_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_confirm_knowledge",
        "description": (
            "Record a person's decision to accept one proposed knowledge item as "
            "authoritative. Requires expected_version: the decision is about "
            "specific wording, and a version that has moved is refused rather "
            "than applied. Do not call this on your own initiative — confirmation "
            "is a human act, and this tool records that a person made it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "knowledge_id": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 1},
                "note": {"type": "string"},
                "reviewer": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "The person whose decision this is. Required: you are "
                        "relaying their decision, not making one. If you have "
                        "not been told who is confirming, do not call this tool."
                    ),
                },
                "idempotency_key": {"type": "string", "maxLength": 200},
            },
            "required": ["project_id", "knowledge_id", "expected_version", "reviewer"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_reject_knowledge",
        "description": (
            "Record a person's decision that one proposed knowledge item must "
            "not become authoritative. Not deletion: the statement stays "
            "readable as history, stops counting toward readiness, and stops "
            "appearing in search. Requires a reason_code and, like confirmation, "
            "the name of the person whose decision this is."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "knowledge_id": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 1},
                "reason_code": {
                    "type": "string",
                    "enum": [
                        "incorrect",
                        "irrelevant",
                        "duplicate",
                        "obsolete",
                        "unsupported",
                        "out_of_scope",
                        "other",
                    ],
                },
                "note": {
                    "type": "string",
                    "description": "Required when reason_code is 'other'.",
                },
                "reviewer": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "The person whose decision this is. Required: you are "
                        "relaying their decision, not making one."
                    ),
                },
                "idempotency_key": {"type": "string", "maxLength": 200},
            },
            "required": [
                "project_id",
                "knowledge_id",
                "expected_version",
                "reason_code",
                "reviewer",
            ],
            "additionalProperties": False,
        },
    },
]

RESOURCE_DEFINITIONS: list[dict[str, str]] = [
    {
        "uri": "kae://projects/{project_id}/briefing",
        "name": "Project briefing",
        "description": "Current understanding, readiness, and open questions.",
        "mimeType": "application/json",
    },
    {
        "uri": "kae://projects/{project_id}/requirements",
        "name": "Requirements",
        "description": "Confirmed requirement statements with their labels.",
        "mimeType": "application/json",
    },
    {
        "uri": "kae://projects/{project_id}/open-decisions",
        "name": "Open decisions",
        "description": "What remains unresolved, and what it affects.",
        "mimeType": "application/json",
    },
    {
        "uri": "kae://projects/{project_id}/readiness",
        "name": "Readiness",
        "description": "Project-scope readiness with per-area contribution.",
        "mimeType": "application/json",
    },
]

PREPARE_IMPLEMENTATION_PROMPT = """\
Prepare an implementation plan for {scope} in KAE project {project_id}.

Task: {task}

Work in this order:

1. Call kae_get_project_briefing for {project_id} and note the knowledge revision.
2. Call kae_get_module_context for {scope}. If it reports a capability gap,
   record that and continue with the briefing and search — do not invent the
   module's definition.
3. Call kae_get_open_decisions. If any unresolved decision blocks this task,
   say so and stop. Do not choose an answer on the project's behalf.
4. Call kae_get_readiness and state plainly whether the project is defined
   enough for this work.
5. Inspect the local repository with your own tools and identify where the code
   and KAE's record disagree.
6. Produce a plan that cites requirement and knowledge identifiers.
7. Submit anything significant you discovered with kae_submit_observation,
   supplying a stable idempotency_key.
8. Report the knowledge revision you worked from.

Do not invent missing requirements. An unknown is a finding, not a gap to fill.
"""


BRIEFING_FIELD_LEVELS: dict[str, response_policy.DetailLevel] = {
    "sections": response_policy.DetailLevel.STANDARD,
    "readiness.explanation": response_policy.DetailLevel.DIAGNOSTIC,
    "readiness.projection": response_policy.DetailLevel.DIAGNOSTIC,
}
"""Which briefing fields a detail level withholds.

Derived from the T1 measurements. `readiness.explanation` was 32% of the whole
response and justifies a number rather than answering "what state is this in";
`sections` was 21% and is the only field that grows with the corpus. Everything
else answers one of the six questions a briefing exists to answer, so it stays
at every level.
"""

TOOL_FIELD_LEVELS: dict[str, dict[str, response_policy.DetailLevel]] = {
    "kae_get_project_briefing": BRIEFING_FIELD_LEVELS,
}
"""Per-tool field maps. A tool absent from here is returned whole."""


def dispatch(context: tools.ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route one tool call, returning a structured payload either way.

    A raised exception becomes a structured error rather than a traceback: a
    traceback is not a tool result, and its text may embed a connection string.
    """

    handlers = {
        "kae_list_projects": lambda: tools.kae_list_projects(context),
        "kae_create_project": lambda: tools.kae_create_project(
            context,
            arguments.get("name", ""),
            arguments.get("key"),
            arguments.get("description"),
        ),
        "kae_get_project_briefing": lambda: tools.kae_get_project_briefing(
            context, arguments.get("project_id", "")
        ),
        "kae_get_module_context": lambda: tools.kae_get_module_context(
            context, arguments.get("project_id", ""), arguments.get("module", "")
        ),
        "kae_search_knowledge": lambda: tools.kae_search_knowledge(
            context,
            arguments.get("project_id", ""),
            arguments.get("query", ""),
            int(arguments.get("limit", 8)),
            arguments.get("kinds"),
            str(arguments.get("mode", "auto")),
            bool(arguments.get("diagnostics", False)),
        ),
        "kae_get_open_decisions": lambda: tools.kae_get_open_decisions(
            context, arguments.get("project_id", "")
        ),
        "kae_get_readiness": lambda: tools.kae_get_readiness(
            context, arguments.get("project_id", "")
        ),
        "kae_submit_observation": lambda: tools.kae_submit_observation(
            context,
            arguments.get("project_id", ""),
            arguments.get("observation", ""),
            arguments.get("idempotency_key", ""),
            arguments.get("source"),
            arguments.get("classification_hint"),
        ),
        "kae_reject_knowledge": lambda: tools.kae_reject_knowledge(
            context,
            arguments.get("project_id", ""),
            arguments.get("knowledge_id", ""),
            arguments.get("expected_version"),
            arguments.get("reason_code"),
            arguments.get("note"),
            arguments.get("reviewer"),
            arguments.get("idempotency_key"),
        ),
        "kae_confirm_knowledge": lambda: tools.kae_confirm_knowledge(
            context,
            arguments.get("project_id", ""),
            arguments.get("knowledge_id", ""),
            arguments.get("expected_version"),
            arguments.get("note"),
            arguments.get("reviewer"),
            arguments.get("idempotency_key"),
        ),
    }
    handler = handlers.get(name)
    if handler is None:
        return {"error": "unknown_tool", "message": f"no tool named {name!r}"}
    try:
        payload = handler()
    except Exception as exception:
        LOGGER.warning("tool %s failed: %s", name, type(exception).__name__)
        return safe_error(exception)

    field_levels = TOOL_FIELD_LEVELS.get(name)
    if field_levels is None or payload.get("error"):
        # An error payload is entirely integrity fields; projecting it would
        # only add a policy echo to a response about something that failed.
        return payload
    try:
        policy = response_policy.from_arguments(arguments, context.response_policy)
    except response_policy.InvalidPolicyError as error:
        return {"error": "invalid_argument", "message": str(error)}
    return response_policy.project(payload, policy, field_levels)


def read_resource(context: tools.ToolContext, uri: str) -> dict[str, Any]:
    """Resolve a ``kae://`` resource URI to a payload."""

    if not uri.startswith("kae://projects/"):
        return {"error": "invalid_argument", "message": f"unsupported resource uri {uri!r}"}
    remainder = uri.removeprefix("kae://projects/")
    project_id, _, leaf = remainder.partition("/")
    try:
        if leaf == "briefing":
            return tools.kae_get_project_briefing(context, project_id)
        if leaf == "readiness":
            return tools.kae_get_readiness(context, project_id)
        if leaf == "open-decisions":
            return tools.kae_get_open_decisions(context, project_id)
        if leaf == "requirements":
            briefing = tools.kae_get_project_briefing(context, project_id)
            return {
                "project_id": project_id,
                "knowledge_revision": briefing["knowledge_revision"],
                "requirements": [
                    statement
                    for section in briefing["sections"]
                    for statement in section["statements"]
                    if statement["kind"] in {"requirement", "rule", "constraint"}
                ],
            }
    except Exception as exception:
        return safe_error(exception)
    return {"error": "invalid_argument", "message": f"unknown resource {leaf!r}"}


def build_server(context: tools.ToolContext) -> Any:
    """Bind the dispatch layer to an MCP server.

    Thin on purpose. All behaviour lives in :mod:`kae_memory.mcp.tools` and in
    :func:`dispatch`, which are plain functions and directly testable; this
    function only registers them, so the transport can change without the
    behaviour moving with it.
    """

    from mcp.server.mcpserver import MCPServer

    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    described = {definition["name"]: definition["description"] for definition in TOOL_DEFINITIONS}

    # Each wrapper is written out with explicit parameters rather than
    # generated from TOOL_DEFINITIONS: the SDK derives a tool's input schema
    # from the signature, so a ``**kwargs`` handler advertises one required
    # argument called "arguments" and every call fails validation.

    def kae_list_projects() -> dict[str, Any]:
        return dispatch(context, "kae_list_projects", {})

    def kae_create_project(
        name: str, key: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_create_project",
            {"name": name, "key": key, "description": description},
        )

    def kae_get_project_briefing(
        project_id: str,
        profile: str | None = None,
        detail: str | None = None,
        prose: str | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_project_briefing",
            {
                "project_id": project_id,
                "profile": profile,
                "detail": detail,
                "prose": prose,
                "max_output_tokens": max_output_tokens,
            },
        )

    def kae_get_module_context(project_id: str, module: str) -> dict[str, Any]:
        return dispatch(
            context, "kae_get_module_context", {"project_id": project_id, "module": module}
        )

    def kae_search_knowledge(
        project_id: str,
        query: str,
        limit: int = 8,
        kinds: list[str] | None = None,
        mode: str = "auto",
        diagnostics: bool = False,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_search_knowledge",
            {
                "project_id": project_id,
                "query": query,
                "limit": limit,
                "kinds": kinds,
                "mode": mode,
                "diagnostics": diagnostics,
            },
        )

    def kae_get_open_decisions(project_id: str) -> dict[str, Any]:
        return dispatch(context, "kae_get_open_decisions", {"project_id": project_id})

    def kae_get_readiness(project_id: str) -> dict[str, Any]:
        return dispatch(context, "kae_get_readiness", {"project_id": project_id})

    def kae_submit_observation(
        project_id: str,
        observation: str,
        idempotency_key: str,
        source: dict[str, Any] | None = None,
        classification_hint: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_submit_observation",
            {
                "project_id": project_id,
                "observation": observation,
                "idempotency_key": idempotency_key,
                "source": source,
                "classification_hint": classification_hint,
            },
        )

    def kae_confirm_knowledge(
        project_id: str,
        knowledge_id: str,
        expected_version: int,
        note: str | None = None,
        reviewer: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_confirm_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": expected_version,
                "note": note,
                "reviewer": reviewer,
                "idempotency_key": idempotency_key,
            },
        )

    def kae_reject_knowledge(
        project_id: str,
        knowledge_id: str,
        expected_version: int,
        reason_code: str,
        reviewer: str,
        note: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_reject_knowledge",
            {
                "project_id": project_id,
                "knowledge_id": knowledge_id,
                "expected_version": expected_version,
                "reason_code": reason_code,
                "note": note,
                "reviewer": reviewer,
                "idempotency_key": idempotency_key,
            },
        )

    wrappers = {
        handler.__name__: handler
        for handler in (
            kae_list_projects,
            kae_create_project,
            kae_get_project_briefing,
            kae_get_module_context,
            kae_search_knowledge,
            kae_get_open_decisions,
            kae_get_readiness,
            kae_submit_observation,
            kae_confirm_knowledge,
            kae_reject_knowledge,
        )
    }

    # Registration is driven by TOOL_DEFINITIONS rather than by the tuple above,
    # so a declared tool without a wrapper fails at startup instead of being
    # silently absent from the client's tool list. A missing wrapper used to be
    # invisible: every test reaches the handlers through `dispatch`, which does
    # not come through here.
    undeclared = set(wrappers) - {definition["name"] for definition in TOOL_DEFINITIONS}
    missing = {definition["name"] for definition in TOOL_DEFINITIONS} - set(wrappers)
    if missing or undeclared:
        raise RuntimeError(
            f"tool registration is inconsistent: declared without a wrapper "
            f"{sorted(missing)}, wrapped without a declaration {sorted(undeclared)}"
        )

    for definition in TOOL_DEFINITIONS:
        name = definition["name"]
        server.add_tool(
            wrappers[name],
            name=name,
            description=described[name],
            structured_output=True,
        )

    @server.resource("kae://projects/{project_id}/briefing")
    def briefing_resource(project_id: str) -> dict[str, Any]:
        """Current understanding, readiness, and open questions."""
        return read_resource(context, f"kae://projects/{project_id}/briefing")

    @server.resource("kae://projects/{project_id}/requirements")
    def requirements_resource(project_id: str) -> dict[str, Any]:
        """Confirmed requirement statements with their labels."""
        return read_resource(context, f"kae://projects/{project_id}/requirements")

    @server.resource("kae://projects/{project_id}/open-decisions")
    def open_decisions_resource(project_id: str) -> dict[str, Any]:
        """What remains unresolved, and what it affects."""
        return read_resource(context, f"kae://projects/{project_id}/open-decisions")

    @server.resource("kae://projects/{project_id}/readiness")
    def readiness_resource(project_id: str) -> dict[str, Any]:
        """Project-scope readiness with per-area contribution."""
        return read_resource(context, f"kae://projects/{project_id}/readiness")

    @server.prompt(name="kae.prepare-implementation")
    def prepare_implementation(project_id: str, module_or_scope: str, task: str) -> str:
        """Retrieve current context, check what blocks the work, then plan."""
        return PREPARE_IMPLEMENTATION_PROMPT.format(
            project_id=project_id, scope=module_or_scope, task=task
        )

    return server


async def serve() -> None:
    """Run the server over STDIO until the client disconnects."""

    context = build_context()
    server = build_server(context)
    LOGGER.info("kae-memory MCP server ready (stdio)")
    await server.run_stdio_async()
