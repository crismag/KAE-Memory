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

from kae_memory import config as database_config
from kae_memory.agents import provider
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.ingestion_service import IngestionService
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
    """Resolve the database URL through the shared provider configuration.

    The same resolver the API and worker use. A second configuration format for
    MCP would be one more thing to get wrong in a client config file, and a
    second place provider identity is decided.
    """

    return database_config.resolve().url


def build_context(url: str | None = None) -> tools.ToolContext:
    """Construct the application services this server adapts."""

    engine = create_engine(url or database_url(), pool_pre_ping=True)
    factory = sessionmaker(engine)
    embedder, name = provider.build_embedder(os.environ)
    return tools.ToolContext(
        memory=MemoryService(factory),
        clarification=ClarificationService(factory),
        blueprint=BlueprintService(factory),
        readiness=ReadinessService(factory),
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, embedder),
        ingestion=IngestionService(factory),
        assembly=AssemblyService(factory),
        classification=ClassificationService(factory),
        embedder_name=name,
        response_policy=response_policy.from_environment(os.environ),
    )


# -- tool surface ----------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "kae_list_projects",
        "description": "List the KAE projects this environment can read.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Page size. Defaults to 20; 100 is the ceiling.",
                },
                "cursor": {
                    "type": "string",
                    "description": (
                        "Continue from a previous response's cursor. Absent in a "
                        "response means the last page was reached."
                    ),
                },
            },
            "additionalProperties": False,
        },
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
                "tiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["durable", "operational", "evidence"]},
                    "description": (
                        "Retention tiers to include. Defaults to durable and "
                        "operational; evidence-tier text is preserved and "
                        "searchable but is not a claim about the project. "
                        "Orthogonal to `detail`, which decides how much of an "
                        "included tier is rendered."
                    ),
                },
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
                "cursor": {
                    "type": "string",
                    "description": "Continue from a previous response's cursor.",
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
        "description": (
            "Unresolved questions and findings that could affect the work. "
            "Paginated; `total` counts everything unresolved, not the page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Page size. Defaults to 20; 100 is the ceiling.",
                },
                "cursor": {
                    "type": "string",
                    "description": (
                        "Continue from a previous response's cursor. Absent in a "
                        "response means the last page was reached."
                    ),
                },
            },
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
                "classification_hint": {
                    "type": "string",
                    "description": (
                        "What the submitter believes this is. Recorded and "
                        "compared against what the classifier found; it never "
                        "overrides the classification."
                    ),
                },
            },
            "required": ["project_id", "observation", "idempotency_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_get_operational_state",
        "description": (
            "Where the work stands, as reported. Filterable by state, kind, and "
            "subject. Everything returned is a claim: `authority` says who made "
            "it and `state` says whether anyone has accepted it. A proposed "
            "record has been read by nobody, and no milestone is complete "
            "because a sentence said so."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "states": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["proposed", "active", "resolved", "expired", "rejected"],
                    },
                    "description": "Defaults to proposed and active - the current state of the work.",
                },
                "kinds": {"type": "array", "items": {"type": "string"}},
                "subject": {
                    "type": "string",
                    "description": "A milestone or target id, such as `M8` or `T1`.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "cursor": {"type": "string"},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_get_classifications",
        "description": (
            "Classified spans of this project's observations, with the range of "
            "stored text each came from. Classification says what a span was, "
            "not whether it is true; nothing listed is confirmed knowledge."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "tiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["durable", "operational", "evidence"]},
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "cursor": {"type": "string"},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_settle_operational_record",
        "description": (
            "Relay a person's decision about a reported operational record: "
            "accept it as active, resolve it, reject it, or let it expire. "
            "`actor` is required - a decision nobody is named for cannot be "
            "audited. Settling records that someone took responsibility for a "
            "claim; it does not verify the claim."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "operational_update_id": {"type": "string", "minLength": 1},
                "state": {
                    "type": "string",
                    "enum": ["active", "resolved", "expired", "rejected"],
                },
                "actor": {"type": "string", "minLength": 1},
                "note": {"type": "string"},
            },
            "required": ["project_id", "operational_update_id", "state", "actor"],
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
    {
        "name": "kae_get_clarifications",
        "description": (
            "Open questions this project's gaps justify asking a person, most "
            "severe first. Records the questions it returns, so each one has an "
            "id that kae_answer_clarification can answer; safe to call again, "
            "because questions are keyed on what they are about rather than "
            "their wording. Returns only gaps a person can answer, never review "
            "work such as confirming candidates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Default 10. The response reports what a bound left out.",
                },
                "profile": {"type": "string", "enum": ["economy", "regular", "detailed"]},
                "detail": {"type": "string", "enum": ["summary", "standard", "diagnostic"]},
                "max_output_tokens": {"type": "integer", "minimum": 1},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_answer_clarification",
        "description": (
            "Record a person's answer to an open question, verbatim. The answer "
            "is evidence, not knowledge: it is queued for extraction, and what "
            "that produces is proposed knowledge a person still confirms. The "
            "response reports the answer accepted, extraction scheduled, and "
            "knowledge unchanged — three separate facts. Supply an "
            "idempotency_key so a retry cannot record a second answer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "clarification_id": {
                    "type": "string",
                    "description": "The id returned by kae_get_clarifications.",
                },
                "answer": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "maxLength": 200},
                "actor_id": {
                    "type": "string",
                    "description": "Who answered. Omit if the person is not identified.",
                },
                "profile": {"type": "string", "enum": ["economy", "regular", "detailed"]},
                "detail": {"type": "string", "enum": ["summary", "standard", "diagnostic"]},
                "max_output_tokens": {"type": "integer", "minimum": 1},
            },
            "required": ["project_id", "clarification_id", "answer"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_correct_knowledge",
        "description": (
            "Record a person's corrected wording for one knowledge statement. "
            "The previous wording is kept, never overwritten. Correcting an "
            "unreviewed statement accepts the corrected form, because the "
            "reviewer wrote it; correcting a confirmed one returns it to "
            "proposed, because the old confirmation covered the old wording."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "knowledge_id": {"type": "string"},
                "expected_version": {"type": "integer", "minimum": 1},
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The corrected statement, in full.",
                },
                "note": {"type": "string", "description": "Why the wording changed."},
                "reviewer": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "The person who wrote this correction. Required: you are "
                        "relaying their wording, not authoring it."
                    ),
                },
                "idempotency_key": {"type": "string", "maxLength": 200},
            },
            "required": [
                "project_id",
                "knowledge_id",
                "expected_version",
                "content",
                "reviewer",
            ],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_ingest_document",
        "description": (
            "Record a document as evidence and queue it to be read. Every span "
            "is stored verbatim so statements can trace back to it. Nothing is "
            "known when this returns: extraction is queued, not finished, and "
            "no knowledge has changed. Idempotent per document and content."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "document": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Source name a span is quoted from, e.g. a file path.",
                },
                "text": {"type": "string", "minLength": 1},
                "max_chunks": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "How much of the document to read. Spans beyond this are "
                        "reported as truncated rather than dropped silently."
                    ),
                },
                "actor_id": {"type": "string"},
            },
            "required": ["project_id", "document", "text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kae_assemble_context",
        "description": (
            "Assemble the knowledge one purpose needs, pinned to one revision "
            "and hashed so the same inputs produce the same package. Bounded "
            "rather than complete. The manifest always states the confirmation "
            "split and every unresolved gap the package carries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "purpose": {
                    "type": "string",
                    "enum": ["discovery", "architecture", "implementation"],
                    "description": "Which areas the package reads. Defaults to implementation.",
                },
                "include_proposed": {
                    "type": "boolean",
                    "description": (
                        "Carry unconfirmed candidates as well. The manifest says "
                        "how much of the package is unconfirmed either way."
                    ),
                },
            },
            "required": ["project_id"],
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

READINESS_FIELD_LEVELS: dict[str, response_policy.DetailLevel] = {
    # ADR-0021 rule 15: the per-area confirmed/proposed counts are the
    # arithmetic behind the percentage, not an answer to "what state is this
    # in". A caller who wants to audit the number asks for it.
    "areas.confirmed": response_policy.DetailLevel.DIAGNOSTIC,
    "areas.proposed": response_policy.DetailLevel.DIAGNOSTIC,
}
"""What a readiness response withholds below `diagnostic`.

`state` and `mandatory` stay at every level: they say whether an area is
holding the project back, which is the question readiness exists to answer.
"""
"""Which briefing fields a detail level withholds.

Derived from the T1 measurements. `readiness.explanation` was 32% of the whole
response and justifies a number rather than answering "what state is this in";
`sections` was 21% and is the only field that grows with the corpus. Everything
else answers one of the six questions a briefing exists to answer, so it stays
at every level.
"""

CLARIFICATION_FIELD_LEVELS: dict[str, response_policy.DetailLevel] = {
    # Which knowledge a question concerns, and whether this call is what asked
    # it, are useful when tracing and noise when working through a queue.
    # Dotted, not `questions[]`: a path names the key, and the pruner reaches
    # inside a list the same way it reaches inside an object. The bracket form
    # these entries used matched nothing, so both fields shipped at every
    # detail level while this map said otherwise.
    "questions.knowledge_ids": response_policy.DetailLevel.DIAGNOSTIC,
    "questions.newly_asked": response_policy.DetailLevel.DIAGNOSTIC,
    "note": response_policy.DetailLevel.STANDARD,
}
"""What an economy profile may drop from a clarification list.

``truncation`` is absent deliberately: it is an integrity field, and a bound
that hid the fact it was a bound would make a partial queue read as the whole
one.
"""

ANSWER_FIELD_LEVELS: dict[str, response_policy.DetailLevel] = {}
"""What an economy profile may drop from an answer: nothing.

``knowledge_state``, ``knowledge_changed``, and ``readiness_changed`` are absent
deliberately: they are the response's whole integrity claim, and a compaction
that removed them would leave a caller reading "answered" as "knowledge
updated".

This map previously withheld ``next_steps`` below `standard`. It never did —
``next_steps`` is in the integrity registry, which the pruner honours first, so
the entry was a claim the code did not carry out. Removed rather than made to
work: what still has to happen before an answer becomes knowledge is exactly
the kind of statement the registry exists to protect.
"""

PROJECT_KEY_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": (
        "Name the project by key instead of id - `kae-memory` rather than a "
        "UUID. `project_id` accepts a key too; passing both when they disagree "
        "is an error rather than a guess."
    ),
}


def _accept_project_keys(definitions: list[dict[str, Any]]) -> None:
    """Let every project-scoped tool be called by key (T25.2).

    Applied to the declarations rather than written into each of them, so a
    tool added later cannot be the one that forgot. `project_id` also stops
    being schema-required: a call naming no project is answered by
    `resolve_project` with an `invalid_argument` that lists the keys this
    environment holds, which is more use to a caller than a schema violation.
    """

    for definition in definitions:
        schema = definition["inputSchema"]
        if "project_id" not in schema.get("properties", {}):
            continue
        schema["properties"]["project_key"] = dict(PROJECT_KEY_PROPERTY)
        required = [name for name in schema.get("required", []) if name != "project_id"]
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)


_accept_project_keys(TOOL_DEFINITIONS)


TOOL_FIELD_LEVELS: dict[str, dict[str, response_policy.DetailLevel]] = {
    "kae_get_project_briefing": BRIEFING_FIELD_LEVELS,
    "kae_get_readiness": READINESS_FIELD_LEVELS,
    "kae_get_clarifications": CLARIFICATION_FIELD_LEVELS,
    "kae_answer_clarification": ANSWER_FIELD_LEVELS,
}
"""Per-tool field maps. A tool absent from here is returned whole."""


def _resolve_project_argument(
    context: tools.ToolContext, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Normalise `project_id` / `project_key` into one canonical id (T25.2).

    Returns the rewritten arguments and, when a key did the resolving, the
    echo that says which project answered. A call naming neither is left alone:
    `kae_list_projects` takes no project, and a tool that needs one raises its
    own `invalid_argument` naming what is available.
    """

    supplied_id = str(arguments.get("project_id") or "").strip()
    supplied_key = str(arguments.get("project_key") or "").strip()
    if not supplied_id and not supplied_key:
        return arguments, None

    project = tools.resolve_project(context, supplied_id, supplied_key)
    rewritten = dict(arguments)
    rewritten["project_id"] = str(project.id)
    rewritten.pop("project_key", None)

    echo = tools.project_scope(project, supplied_id, supplied_key)
    return rewritten, None if echo["resolved_from"] == "project_id" else echo


def dispatch(context: tools.ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route one tool call, returning a structured payload either way.

    A raised exception becomes a structured error rather than a traceback: a
    traceback is not a tool result, and its text may embed a connection string.

    A project named by key is resolved to its id once, here, rather than in
    fourteen handlers (T25.2). Resolution is not authorisation: it decides
    which project a caller named, never whether they may read it.
    """

    try:
        arguments, resolved = _resolve_project_argument(context, arguments)
    except Exception as exception:
        LOGGER.warning("tool %s failed to resolve a project: %s", name, type(exception).__name__)
        return safe_error(exception)

    handlers = {
        "kae_list_projects": lambda: tools.kae_list_projects(
            context, arguments.get("limit"), arguments.get("cursor")
        ),
        "kae_ingest_document": lambda: tools.kae_ingest_document(
            context,
            arguments.get("project_id", ""),
            arguments.get("document", ""),
            arguments.get("text", ""),
            arguments.get("max_chunks"),
            arguments.get("actor_id"),
        ),
        "kae_assemble_context": lambda: tools.kae_assemble_context(
            context,
            arguments.get("project_id", ""),
            arguments.get("purpose", "implementation"),
            bool(arguments.get("include_proposed", False)),
        ),
        "kae_create_project": lambda: tools.kae_create_project(
            context,
            arguments.get("name", ""),
            arguments.get("key"),
            arguments.get("description"),
        ),
        "kae_get_project_briefing": lambda: tools.kae_get_project_briefing(
            context, arguments.get("project_id", ""), arguments.get("tiers")
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
            arguments.get("cursor"),
        ),
        "kae_get_open_decisions": lambda: tools.kae_get_open_decisions(
            context,
            arguments.get("project_id", ""),
            arguments.get("limit"),
            arguments.get("cursor"),
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
        "kae_answer_clarification": lambda: tools.kae_answer_clarification(
            context,
            arguments.get("project_id", ""),
            arguments.get("clarification_id", ""),
            arguments.get("answer"),
            arguments.get("idempotency_key"),
            arguments.get("actor_id"),
        ),
        "kae_get_clarifications": lambda: tools.kae_get_clarifications(
            context,
            arguments.get("project_id", ""),
            arguments.get("limit"),
        ),
        "kae_correct_knowledge": lambda: tools.kae_correct_knowledge(
            context,
            arguments.get("project_id", ""),
            arguments.get("knowledge_id", ""),
            arguments.get("expected_version"),
            arguments.get("content"),
            arguments.get("note"),
            arguments.get("reviewer"),
            arguments.get("idempotency_key"),
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
        "kae_get_operational_state": lambda: tools.kae_get_operational_state(
            context,
            arguments.get("project_id", ""),
            arguments.get("states"),
            arguments.get("kinds"),
            arguments.get("subject"),
            arguments.get("limit"),
            arguments.get("cursor"),
        ),
        "kae_get_classifications": lambda: tools.kae_get_classifications(
            context,
            arguments.get("project_id", ""),
            arguments.get("tiers"),
            arguments.get("limit"),
            arguments.get("cursor"),
        ),
        "kae_settle_operational_record": lambda: tools.kae_settle_operational_record(
            context,
            arguments.get("project_id", ""),
            arguments.get("operational_update_id", ""),
            arguments.get("state", ""),
            arguments.get("actor", ""),
            arguments.get("note"),
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

    if resolved is not None and not payload.get("error"):
        # Only when a key did the resolving. A caller who passed an id already
        # knows which project answered, and echoing it back on every response
        # would spend tokens restating the argument.
        payload["resolved_project"] = resolved

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

    def kae_list_projects(limit: int | None = None, cursor: str | None = None) -> dict[str, Any]:
        return dispatch(context, "kae_list_projects", {"limit": limit, "cursor": cursor})

    def kae_ingest_document(
        document: str,
        text: str,
        max_chunks: int | None = None,
        actor_id: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_ingest_document",
            {
                "project_id": project_id,
                "project_key": project_key,
                "document": document,
                "text": text,
                "max_chunks": max_chunks,
                "actor_id": actor_id,
            },
        )

    def kae_assemble_context(
        purpose: str = "implementation",
        include_proposed: bool = False,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_assemble_context",
            {
                "project_id": project_id,
                "project_key": project_key,
                "purpose": purpose,
                "include_proposed": include_proposed,
            },
        )

    def kae_create_project(
        name: str, key: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_create_project",
            {"name": name, "key": key, "description": description},
        )

    def kae_get_project_briefing(
        profile: str | None = None,
        detail: str | None = None,
        prose: str | None = None,
        max_output_tokens: int | None = None,
        tiers: list[str] | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_project_briefing",
            {
                "project_id": project_id,
                "project_key": project_key,
                "profile": profile,
                "detail": detail,
                "prose": prose,
                "max_output_tokens": max_output_tokens,
                "tiers": tiers,
            },
        )

    def kae_get_module_context(
        module: str,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_module_context",
            {"project_id": project_id, "project_key": project_key, "module": module},
        )

    def kae_search_knowledge(
        query: str,
        limit: int = 8,
        kinds: list[str] | None = None,
        mode: str = "auto",
        diagnostics: bool = False,
        cursor: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_search_knowledge",
            {
                "project_id": project_id,
                "project_key": project_key,
                "query": query,
                "limit": limit,
                "kinds": kinds,
                "mode": mode,
                "diagnostics": diagnostics,
                "cursor": cursor,
            },
        )

    def kae_get_open_decisions(
        limit: int | None = None,
        cursor: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_open_decisions",
            {
                "project_id": project_id,
                "project_key": project_key,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def kae_get_readiness(
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_readiness",
            {"project_id": project_id, "project_key": project_key},
        )

    def kae_submit_observation(
        observation: str,
        idempotency_key: str,
        source: dict[str, Any] | None = None,
        classification_hint: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_submit_observation",
            {
                "project_id": project_id,
                "project_key": project_key,
                "observation": observation,
                "idempotency_key": idempotency_key,
                "source": source,
                "classification_hint": classification_hint,
            },
        )

    def kae_get_operational_state(
        states: list[str] | None = None,
        kinds: list[str] | None = None,
        subject: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_operational_state",
            {
                "project_id": project_id,
                "project_key": project_key,
                "states": states,
                "kinds": kinds,
                "subject": subject,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def kae_get_classifications(
        tiers: list[str] | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_classifications",
            {
                "project_id": project_id,
                "project_key": project_key,
                "tiers": tiers,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def kae_settle_operational_record(
        operational_update_id: str,
        state: str,
        actor: str,
        note: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "project_key": project_key,
                "operational_update_id": operational_update_id,
                "state": state,
                "actor": actor,
                "note": note,
            },
        )

    def kae_confirm_knowledge(
        knowledge_id: str,
        expected_version: int,
        note: str | None = None,
        reviewer: str | None = None,
        idempotency_key: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_confirm_knowledge",
            {
                "project_id": project_id,
                "project_key": project_key,
                "knowledge_id": knowledge_id,
                "expected_version": expected_version,
                "note": note,
                "reviewer": reviewer,
                "idempotency_key": idempotency_key,
            },
        )

    def kae_reject_knowledge(
        knowledge_id: str,
        expected_version: int,
        reason_code: str,
        reviewer: str,
        note: str | None = None,
        idempotency_key: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_reject_knowledge",
            {
                "project_id": project_id,
                "project_key": project_key,
                "knowledge_id": knowledge_id,
                "expected_version": expected_version,
                "reason_code": reason_code,
                "note": note,
                "reviewer": reviewer,
                "idempotency_key": idempotency_key,
            },
        )

    def kae_answer_clarification(
        clarification_id: str,
        answer: str,
        idempotency_key: str | None = None,
        actor_id: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "project_key": project_key,
                "clarification_id": clarification_id,
                "answer": answer,
                "idempotency_key": idempotency_key,
                "actor_id": actor_id,
            },
        )

    def kae_get_clarifications(
        limit: int | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_get_clarifications",
            {"project_id": project_id, "project_key": project_key, "limit": limit},
        )

    def kae_correct_knowledge(
        knowledge_id: str,
        expected_version: int,
        content: str,
        reviewer: str,
        note: str | None = None,
        idempotency_key: str | None = None,
        project_id: str = "",
        project_key: str | None = None,
    ) -> dict[str, Any]:
        return dispatch(
            context,
            "kae_correct_knowledge",
            {
                "project_id": project_id,
                "project_key": project_key,
                "knowledge_id": knowledge_id,
                "expected_version": expected_version,
                "content": content,
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
            kae_ingest_document,
            kae_assemble_context,
            kae_get_project_briefing,
            kae_get_module_context,
            kae_search_knowledge,
            kae_get_open_decisions,
            kae_get_readiness,
            kae_submit_observation,
            kae_confirm_knowledge,
            kae_reject_knowledge,
            kae_get_operational_state,
            kae_get_classifications,
            kae_settle_operational_record,
            kae_correct_knowledge,
            kae_get_clarifications,
            kae_answer_clarification,
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
