"""Measure the size and internal duplication of every MCP read response.

The baseline behind `docs/09_development/MCP_RESPONSE_BASELINE.md`, and the way
to reproduce it after a change. Measurement is structural — field counts,
repeated identifiers, repeated renderings — because a token total on its own
cannot say *why* a response is large, and the why is what a later target has to
act on.

Usage::

    KAE_DATABASE_URL=... python scripts/development/measure-mcp-responses.py [project_id]

With no project id it measures every project the database holds. Nothing is
written and no tool that mutates state is called: `kae_submit_observation` is
deliberately excluded, because measuring a write by performing one would leave
evidence behind in whatever project was measured.
"""

import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kae_memory.agents import DeterministicEmbeddingAdapter
from kae_memory.application import (
    BlueprintService,
    MemoryService,
    ReadinessService,
    RetrievalService,
    ReviewService,
)
from kae_memory.domain.chunks import estimate_tokens
from kae_memory.domain.identifiers import ProjectId
from kae_memory.mcp import tools
from kae_memory.mcp.response_policy import INTEGRITY_FIELDS
from kae_memory.mcp.server import dispatch

READ_TOOLS = (
    "kae_list_projects",
    "kae_get_project_briefing",
    "kae_get_module_context",
    "kae_search_knowledge",
    "kae_get_open_decisions",
    "kae_get_readiness",
)
"""The enabled tools that only read. Every write is excluded.

The surface is now fifteen tools, but the other reads either need a document
argument or would materialise clarification questions, and materialising is a
write in everything but name. Measuring a write by performing one would leave
evidence behind in whatever project was measured.
"""

PROFILES = ("economy", "regular", "detailed")
"""The three presets, measured together.

T1 measured one shape because there was only one. What T5 has to show is the
distance between them — a reduction is only demonstrated by the pair.
"""

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_BPE_ISH = re.compile(r"[A-Za-z]+|[0-9]+|[^\sA-Za-z0-9]")
"""Letters, digits, and single punctuation marks as separate units.

A second estimator, not a better one. It exists to show the *direction* of the
error in the primary estimate: JSON is punctuation-dense and full of
identifiers, both of which a characters-per-token rule under-counts.
"""


@dataclass(frozen=True, slots=True)
class Measurement:
    """One tool's response, measured."""

    tool: str
    bytes_utf8: int
    characters: int
    tokens_chars_per_4: int
    tokens_structural: int
    top_level_fields: int
    total_nodes: int
    entity_ids: int
    distinct_entity_ids: int
    repeated_texts: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def repeated_id_count(self) -> int:
        """How many identifier occurrences are repeats of one already present."""

        return self.entity_ids - self.distinct_entity_ids


def measure(tool: str, payload: Mapping[str, Any]) -> Measurement:
    """Return the structural measurements for one response."""

    serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    ids = _identifiers(payload)
    return Measurement(
        tool=tool,
        bytes_utf8=len(serialised.encode("utf-8")),
        characters=len(serialised),
        # The repository's own approximation, reused so that a measurement here
        # and a chunking decision elsewhere do not disagree about what a token is.
        tokens_chars_per_4=estimate_tokens(serialised),
        tokens_structural=len(_BPE_ISH.findall(serialised)),
        top_level_fields=len(payload),
        total_nodes=sum(1 for _ in _walk(payload)),
        entity_ids=len(ids),
        distinct_entity_ids=len(set(ids)),
        repeated_texts=_repeated_texts(payload),
        error=str(payload.get("error")) if isinstance(payload, dict) else None,
    )


def section_sizes(payload: Mapping[str, Any]) -> list[tuple[str, int, int]]:
    """Return ``(field, characters, share)`` per top-level field, largest first.

    Shares are of the whole serialised response, so they sum to slightly under
    100: the enclosing braces and key names are not attributed to any field.
    """

    total = len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    rows = [
        (key, len(json.dumps(value, ensure_ascii=False, sort_keys=True)))
        for key, value in payload.items()
    ]
    rows.sort(key=lambda row: row[1], reverse=True)
    return [(key, size, round(size * 100 / total)) for key, size in rows]


def _walk(node: Any) -> Iterator[Any]:
    """Yield every node in a JSON tree, containers included."""

    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _identifiers(payload: Any) -> list[str]:
    """Return every UUID occurrence, in document order.

    Counted as occurrences rather than as a set, because a knowledge identifier
    appearing four times is exactly the signal this measurement exists to find.
    """

    return _UUID.findall(json.dumps(payload, ensure_ascii=False))


def _repeated_texts(payload: Any, minimum_length: int = 24) -> tuple[tuple[str, int], ...]:
    """Return substantial string values that occur more than once.

    A short string repeating is usually an enum. A long one repeating is usually
    the same fact rendered twice, which is what a later target has to remove.
    """

    counts: Counter[str] = Counter(
        node for node in _walk(payload) if isinstance(node, str) and len(node) >= minimum_length
    )
    repeats = [(text, count) for text, count in counts.items() if count > 1]
    repeats.sort(key=lambda row: (-row[1], -len(row[0])))
    return tuple(repeats)


def build_context(url: str) -> tools.ToolContext:
    """Construct the same services the MCP server wires, against ``url``."""

    factory = sessionmaker(create_engine(url, pool_pre_ping=True))
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=ReadinessService(factory),
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        embedder_name="deterministic",
    )


def arguments_for(tool: str, project_id: str) -> dict[str, Any]:
    """Return representative arguments for ``tool``.

    The search and module queries use a term the corpus actually contains.
    Measuring a query that matches nothing would understate every response that
    carries results.
    """

    if tool == "kae_list_projects":
        return {}
    if tool == "kae_search_knowledge":
        return {"project_id": project_id, "query": "approval"}
    if tool == "kae_get_module_context":
        return {"project_id": project_id, "module": "approval workflow"}
    return {"project_id": project_id}


def measure_project(
    context: tools.ToolContext, project_id: str, profile: str | None = None
) -> list[Measurement]:
    """Measure every read tool against one project, at one profile."""

    results = []
    for tool in READ_TOOLS:
        arguments = arguments_for(tool, project_id)
        if profile is not None:
            arguments["profile"] = profile
        payload = dispatch(context, tool, arguments)
        results.append(measure(tool, payload))
    return results


def integrity_paths(payload: Any, prefix: str = "") -> set[str]:
    """Return every dotted path whose leaf is a registered integrity field."""

    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}{key}"
            if key in INTEGRITY_FIELDS:
                found.add(path)
            found |= integrity_paths(value, f"{path}.")
    elif isinstance(payload, list):
        for element in payload:
            found |= integrity_paths(element, prefix)
    return found


def survival(context: tools.ToolContext, project_id: str) -> list[tuple[str, int, list[str]]]:
    """Return, per tool, how many integrity fields economy kept and which it lost.

    The half of this measurement that matters. A response can always be made
    smaller by deleting what carries meaning, so a size table on its own cannot
    distinguish a reduction from a loss. A field withheld as part of a section
    the response declared dropped is not counted as lost: that absence is
    stated, and a caller can ask for it back.
    """

    rows = []
    for tool in READ_TOOLS:
        arguments = arguments_for(tool, project_id)
        detailed = dispatch(context, tool, {**arguments, "profile": "detailed"})
        economy = dispatch(context, tool, {**arguments, "profile": "economy"})
        withheld = tuple(economy.get("truncation", {}).get("dropped", ()))
        present = integrity_paths(detailed)
        kept = integrity_paths(economy)
        lost = sorted(
            path
            for path in present - kept
            if not any(path.startswith(f"{section}.") for section in withheld)
        )
        rows.append((tool, len(present), lost))
    return rows


def main() -> int:
    """Measure and print the baseline."""

    url = os.environ.get("KAE_DATABASE_URL", "").strip()
    if not url:
        print("KAE_DATABASE_URL is not set", file=sys.stderr)
        return 2

    context = build_context(url)
    requested = sys.argv[1] if len(sys.argv) > 1 else None
    projects = (
        [requested]
        if requested
        else [str(project.id) for project in context.memory.list_projects()]
    )
    if not projects:
        print("no projects to measure", file=sys.stderr)
        return 1

    for project_id in projects:
        project = context.memory.get_project(ProjectId(project_id))
        label = project.name if project else project_id
        print(f"\n=== {label} ({project_id}) ===")
        for profile in PROFILES:
            print(f"\n  profile: {profile}")
            print(
                f"  {'tool':<28}{'chars':>8}{'~tok/4':>8}{'~struct':>9}"
                f"{'fields':>8}{'nodes':>7}{'ids':>6}{'dup ids':>9}{'dup text':>10}"
            )
            for row in measure_project(context, project_id, profile):
                print(
                    f"  {row.tool:<28}{row.characters:>8}{row.tokens_chars_per_4:>8}"
                    f"{row.tokens_structural:>9}{row.top_level_fields:>8}{row.total_nodes:>7}"
                    f"{row.entity_ids:>6}{row.repeated_id_count:>9}{len(row.repeated_texts):>10}"
                )

        print("\n  integrity fields at economy (present at detailed -> lost):")
        for tool, present, lost in survival(context, project_id):
            verdict = "all kept" if not lost else f"LOST {lost}"
            print(f"    {tool:<28}{present:>4} present   {verdict}")

        briefing = dispatch(context, "kae_get_project_briefing", {"project_id": project_id})
        print("\n  kae_get_project_briefing — by field:")
        for key, size, share in section_sizes(briefing):
            print(f"    {key:<28}{size:>7} chars{share:>5}%")

        repeats = _repeated_texts(briefing)
        if repeats:
            print("\n  repeated strings (>=24 chars) in the briefing:")
            for text, count in repeats[:12]:
                shortened = text if len(text) <= 62 else text[:59] + "..."
                print(f"    {count}x  {shortened}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
