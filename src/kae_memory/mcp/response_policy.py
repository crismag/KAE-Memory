"""How much a response says, and what it may never stop admitting.

Implements the model in `docs/06_architecture/MCP_RESPONSE_POLICY.md`. Three
things live here and nothing else: the resolved policy, the two registries that
constrain it, and the projection that applies it.

Handlers stay authoritative. Each renders everything it can support, and this
module decides what a particular caller receives — one place rather than one per
tool, because four controls across eight tools is thirty-two chances to diverge.

The rule that shapes the rest:

    A profile may reduce what a response says.
    It may never reduce what a response admits.

Fields that stop a caller over-trusting a result are integrity fields. No
profile, budget, or prose level removes them. An economy response that dropped
``semantic_search_available`` would cost fewer tokens and mislead the agent
reading it, which is worse than spending them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from kae_memory.domain.chunks import estimate_tokens


class DetailLevel(StrEnum):
    """How much factual coverage a response carries.

    Three levels, settled 2026-08-03. Each is a superset of the one above, and a
    lower level omits whole fields — never a partial object, a truncated list
    without a count, or a shortened statement.
    """

    SUMMARY = "summary"
    STANDARD = "standard"
    DIAGNOSTIC = "diagnostic"


class ProseLevel(StrEnum):
    """How explanatory strings are worded.

    Independent of :class:`DetailLevel`: every fact with no explanation is a
    legitimate request, and so is a brief overview written for a person.
    """

    NONE = "none"
    MINIMAL = "minimal"
    CONCISE = "concise"
    STANDARD = "standard"


class ResponseProfile(StrEnum):
    """A named preset that resolves into explicit values."""

    ECONOMY = "economy"
    REGULAR = "regular"
    DETAILED = "detailed"
    CUSTOM = "custom"


_DETAIL_ORDER = (DetailLevel.SUMMARY, DetailLevel.STANDARD, DetailLevel.DIAGNOSTIC)


def includes(level: DetailLevel, required: DetailLevel) -> bool:
    """Return whether ``level`` reaches ``required``."""

    return _DETAIL_ORDER.index(level) >= _DETAIL_ORDER.index(required)


INTEGRITY_FIELDS: frozenset[str] = frozenset(
    {
        # What a search did, and what it could not do
        "search_mode",
        "semantic_search_available",
        "ranking",
        "warnings",
        "indexing",
        # What a capability gap is
        "error",
        "message",
        "capability",
        "missing_capabilities",
        "guidance",
        "subject",
        "next_steps",
        # What an offer of substitute data is not
        "caveat",
        "match_type",
        "available",
        "reason",
        # What a figure does and does not answer
        "scope",
        "scope_note",
        "module_scope_available",
        # Whether a person has ruled on a statement (T13). Stripping these to
        # save tokens would leave a caller reading unreviewed proposals as
        # established fact — the single most expensive thing a compaction here
        # could get wrong.
        "state",
        "authoritative",
        # What a package would carry (T21)
        "confirmation_state",
        "unresolved_critical_gaps",
        "source_knowledge",
        # What this response itself left out
        "truncation",
        # Questions a limit left out. Distinct from `truncation`, which is
        # about fields a detail level dropped — a caller needs to tell
        # "work you have not seen" from "detail we compacted away".
        "omitted",
        # An answer is recorded; knowledge is not yet changed. Dropping these
        # to save tokens would let "answered" read as "the project now knows
        # this", which is the one thing the clarification loop must not imply.
        "knowledge_state",
        "knowledge_changed",
        # Where a caller actually is in the loop. Compacting it away would
        # leave them inferring progress from fields that do not carry it.
        "workflow_state",
    }
)
"""Fields no profile, budget, or prose level may remove.

Each exists to stop a caller believing more than the response supports. This is
a registry rather than a rule in prose so that a test can assert it, which is
what makes the guarantee real rather than aspirational.
"""

SHORT_FORMS: Mapping[str, str] = {
    "Semantic ranking is unavailable because no semantic embedding model is "
    "configured. Matched on query terms instead, so conceptual queries that share "
    "no wording with the stored text will not be found.": (
        "Lexical match only; no semantic model configured."
    ),
    "These statements match the wording of the requested name. That is a term "
    "match, not module membership — no record of which knowledge belongs to this "
    "module exists in this version.": ("Term match, not module membership."),
    "Nothing matched. This is a result, not a failure: no stored knowledge met "
    "the relevance threshold for this query.": ("No match; nothing met the threshold."),
    # T4/ADR-0021: `note` is an integrity statement, so it shortens rather than
    # disappearing at a lower prose level. `why` is explanatory and gates.
    "Recorded verbatim as evidence. Nothing is confirmed by this call; a "
    "person confirms what becomes project knowledge.": ("Recorded as evidence; not confirmed."),
    "These are unresolved. Do not choose an answer on the project's behalf; if "
    "one blocks the work, report it and stop.": (
        "Unresolved; do not answer on the project's behalf."
    ),
}
"""Registered short wordings for integrity statements.

A table, not runtime summarisation. Generating the short form with a model would
make the guarantee non-deterministic, and an integrity statement that varies is
not a guarantee. An unregistered string is left at full length rather than
shortened by guesswork.
"""


@dataclass(frozen=True, slots=True)
class ResponsePolicy:
    """The resolved controls for one call."""

    detail: DetailLevel = DetailLevel.SUMMARY
    prose: ProseLevel = ProseLevel.CONCISE
    max_output_tokens: int | None = 2_500
    max_entities: int | None = 25
    max_text_length: int | None = None
    profile: ResponseProfile = ResponseProfile.REGULAR

    def resolved(self) -> dict[str, Any]:
        """Return the values applied, for echoing back to the caller.

        A custom profile is irreproducible unless the response says what it
        resolved to, so this ships with every projected payload.
        """

        return {
            "profile": self.profile.value,
            "detail": self.detail.value,
            "prose": self.prose.value,
            "max_output_tokens": self.max_output_tokens,
            "max_entities": self.max_entities,
        }


PROFILES: Mapping[ResponseProfile, ResponsePolicy] = {
    ResponseProfile.ECONOMY: ResponsePolicy(
        detail=DetailLevel.SUMMARY,
        prose=ProseLevel.NONE,
        max_output_tokens=800,
        max_entities=10,
        max_text_length=200,
        profile=ResponseProfile.ECONOMY,
    ),
    ResponseProfile.REGULAR: ResponsePolicy(profile=ResponseProfile.REGULAR),
    ResponseProfile.DETAILED: ResponsePolicy(
        detail=DetailLevel.DIAGNOSTIC,
        prose=ProseLevel.STANDARD,
        max_output_tokens=8_000,
        max_entities=100,
        profile=ResponseProfile.DETAILED,
    ),
}
"""Presets, expanded at resolution time. A profile is never a runtime behaviour."""

SERVER_MAXIMUMS = ResponsePolicy(
    max_output_tokens=20_000,
    max_entities=200,
    max_text_length=10_000,
)
"""Ceilings a caller may request less than and never more than."""


class InvalidPolicyError(ValueError):
    """A requested profile or control is not one this server offers."""


def from_environment(environ: Mapping[str, str]) -> ResponsePolicy:
    """Return the deployment default, with ``KAE_MCP_*`` overrides applied.

    Read where the server is wired rather than inside a tool, matching how
    ingestion and the worker are already configured.
    """

    base = PROFILES[_profile(environ.get("KAE_MCP_PROFILE", "regular"))]
    changes: dict[str, Any] = {}
    if detail := environ.get("KAE_MCP_DETAIL", "").strip():
        changes["detail"] = _detail(detail)
    if prose := environ.get("KAE_MCP_PROSE", "").strip():
        changes["prose"] = _prose(prose)
    if tokens := environ.get("KAE_MCP_MAX_TOKENS", "").strip():
        changes["max_output_tokens"] = int(tokens)
    if entities := environ.get("KAE_MCP_MAX_ENTITIES", "").strip():
        changes["max_entities"] = int(entities)
    return clamp(replace(base, **changes) if changes else base)


def from_arguments(arguments: Mapping[str, Any], base: ResponsePolicy) -> ResponsePolicy:
    """Return ``base`` with this call's overrides applied and clamped.

    An unrecognised control is an error rather than something ignored: silently
    dropping one lets a caller believe a budget applied when it did not.
    """

    # Optional tool arguments arrive as None when unset; an absent control
    # must mean "use the default", not "reset to it".
    arguments = {k: v for k, v in arguments.items() if v is not None}
    profile_name = arguments.get("profile")
    policy = PROFILES[_profile(str(profile_name))] if profile_name else base

    changes: dict[str, Any] = {}
    if (detail := arguments.get("detail")) is not None:
        changes["detail"] = _detail(str(detail))
    if (prose := arguments.get("prose")) is not None:
        changes["prose"] = _prose(str(prose))
    if (tokens := arguments.get("max_output_tokens")) is not None:
        changes["max_output_tokens"] = int(tokens)
    if (entities := arguments.get("max_entities")) is not None:
        changes["max_entities"] = int(entities)
    if (changes and profile_name is None) or changes:
        changes["profile"] = ResponseProfile.CUSTOM
    return clamp(replace(policy, **changes) if changes else policy)


def clamp(policy: ResponsePolicy) -> ResponsePolicy:
    """Hold a policy inside the server maximums.

    A caller may ask for less than the ceiling and never more. Clamping rather
    than rejecting keeps an over-ambitious request working, and the resolved
    values ship in the response so the caller can see what it actually got.
    """

    changes: dict[str, Any] = {}
    for field, ceiling in (
        ("max_output_tokens", SERVER_MAXIMUMS.max_output_tokens),
        ("max_entities", SERVER_MAXIMUMS.max_entities),
        ("max_text_length", SERVER_MAXIMUMS.max_text_length),
    ):
        requested = getattr(policy, field)
        if ceiling is not None and requested is not None and requested > ceiling:
            changes[field] = ceiling
        if requested is not None and requested < 1:
            raise InvalidPolicyError(f"{field} must be at least 1")
    return replace(policy, **changes) if changes else policy


def project(
    payload: Mapping[str, Any],
    policy: ResponsePolicy,
    field_levels: Mapping[str, DetailLevel],
) -> dict[str, Any]:
    """Return ``payload`` reduced to what ``policy`` allows.

    ``field_levels`` says the lowest detail level at which each field appears;
    a field absent from the map is always included. Keys may be dotted —
    ``readiness.explanation`` prunes inside a nested object — because the fields
    worth dropping are not all at the top level. Integrity fields are kept
    regardless of either.

    Dropped fields are reported rather than silently removed — a response that
    quietly omits a section is indistinguishable from one whose project had
    nothing to put there.
    """

    kept, dropped = _prune(payload, policy, field_levels, prefix="")

    if policy.prose is not ProseLevel.STANDARD:
        kept = _shorten(kept, policy.prose)

    kept["response_policy"] = policy.resolved()
    if dropped:
        kept["truncation"] = {
            "applied": True,
            # Deduplicated: a field withheld from every element of a list is one
            # withheld field, not one per element. Reporting it per element made
            # a compacted readiness response *larger* than the full one, which
            # is the reduction defeating itself.
            "dropped": sorted(set(dropped)),
            "reason": f"detail={policy.detail.value}",
            "retrieve_with": f"the same call with detail={DetailLevel.DIAGNOSTIC.value}",
        }
    return kept


def _prune(
    payload: Mapping[str, Any],
    policy: ResponsePolicy,
    field_levels: Mapping[str, DetailLevel],
    prefix: str,
) -> tuple[dict[str, Any], list[str]]:
    """Return ``payload`` without fields this detail level excludes."""

    kept: dict[str, Any] = {}
    dropped: list[str] = []

    for key, value in payload.items():
        path = f"{prefix}{key}"
        if key in INTEGRITY_FIELDS:
            kept[key] = value
            continue
        required = field_levels.get(path)
        if required is not None and not includes(policy.detail, required):
            dropped.append(path)
            continue
        has_nested = any(k.startswith(f"{path}.") for k in field_levels)
        if isinstance(value, dict) and has_nested:
            nested, nested_dropped = _prune(value, policy, field_levels, prefix=f"{path}.")
            kept[key] = nested
            dropped.extend(nested_dropped)
            continue
        if isinstance(value, list) and has_nested:
            # A field map entry like `areas.confirmed` names a key inside every
            # element, not a key on the list. Descending only into dicts would
            # silently keep per-element fields that a detail level excludes,
            # which is the quiet half of a pruning bug: the response looks
            # compacted and is not.
            elements: list[Any] = []
            for element in value:
                if not isinstance(element, dict):
                    elements.append(element)
                    continue
                pruned, element_dropped = _prune(element, policy, field_levels, f"{path}.")
                elements.append(pruned)
                dropped.extend(element_dropped)
            kept[key] = elements
            continue
        kept[key] = value

    return kept, dropped


def within_budget(payload: Mapping[str, Any], policy: ResponsePolicy) -> bool:
    """Return whether a payload fits its token budget.

    Uses the repository's own estimator, which under-counts JSON. Budgets are
    advisory ceilings with margin rather than exact contracts, and the estimator
    is named in the response so a caller is not misled about precision.
    """

    if policy.max_output_tokens is None:
        return True
    import json

    return estimate_tokens(json.dumps(payload, ensure_ascii=False)) <= policy.max_output_tokens


DEFAULT_PAGE_SIZE = 20
"""How many results a read returns when the caller does not say.

Large enough to answer most questions in one call, small enough that a project
with hundreds of statements does not arrive as a single unreadable response.
"""

MAX_PAGE_SIZE = 100
"""The ceiling a caller cannot raise. A page is a budget, not a suggestion."""


def paginate(
    items: Sequence[Any],
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return one page of ``items`` in the wrapper ADR-0021 fixed.

    ``{total, page, cursor, results}``. The shape was decided in ADR-0021
    §Coordination so that T4 populates it rather than designing it, and so a
    caller learns one wrapper instead of one per tool.

    ``total`` is the full count *before* limiting, which is the number a caller
    needs to decide whether to keep reading. Returning only the page size would
    make "20 results" and "20 of 400 results" indistinguishable — the reading
    that leads an agent to act on a fraction of a project believing it saw all
    of it.

    ``cursor`` is the offset of the next page, or ``None`` when the last page
    has been reached. Absent means finished, not "unknown".
    """

    total = len(items)
    size = DEFAULT_PAGE_SIZE if limit is None else max(1, min(limit, MAX_PAGE_SIZE))
    offset = _offset(cursor)
    window = list(items[offset : offset + size])
    consumed = offset + len(window)

    return {
        "total": total,
        "page": offset // size + 1,
        "cursor": str(consumed) if consumed < total else None,
        "results": window,
    }


def _offset(cursor: str | None) -> int:
    """Read a cursor, refusing one that would silently start from the top.

    A malformed cursor treated as zero would re-read the first page while the
    caller believed it was advancing, so it is an error rather than a default.
    """

    if cursor is None or not str(cursor).strip():
        return 0
    try:
        offset = int(cursor)
    except (TypeError, ValueError):
        raise InvalidPolicyError(
            f"unusable cursor {cursor!r}: pass the value a previous response "
            f"returned, or omit it to start from the beginning"
        ) from None
    if offset < 0:
        raise InvalidPolicyError("cursor must not be negative")
    return offset


def _shorten(payload: dict[str, Any], prose: ProseLevel) -> dict[str, Any]:
    """Replace registered integrity statements with their short forms."""

    def convert(node: Any) -> Any:
        if isinstance(node, str):
            return SHORT_FORMS.get(node, node)
        if isinstance(node, dict):
            return {key: convert(value) for key, value in node.items()}
        if isinstance(node, list):
            return [convert(value) for value in node]
        return node

    return {key: convert(value) for key, value in payload.items()}


def _profile(name: str) -> ResponseProfile:
    try:
        return ResponseProfile(name.strip().lower())
    except ValueError as error:
        valid = ", ".join(p.value for p in ResponseProfile)
        raise InvalidPolicyError(f"unknown profile {name!r}. Valid: {valid}") from error


def _detail(name: str) -> DetailLevel:
    try:
        return DetailLevel(name.strip().lower())
    except ValueError as error:
        valid = ", ".join(d.value for d in DetailLevel)
        raise InvalidPolicyError(f"unknown detail level {name!r}. Valid: {valid}") from error


def _prose(name: str) -> ProseLevel:
    try:
        return ProseLevel(name.strip().lower())
    except ValueError as error:
        valid = ", ".join(p.value for p in ProseLevel)
        raise InvalidPolicyError(f"unknown prose level {name!r}. Valid: {valid}") from error


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "INTEGRITY_FIELDS",
    "MAX_PAGE_SIZE",
    "PROFILES",
    "SERVER_MAXIMUMS",
    "SHORT_FORMS",
    "DetailLevel",
    "InvalidPolicyError",
    "ProseLevel",
    "ResponsePolicy",
    "ResponseProfile",
    "clamp",
    "from_arguments",
    "from_environment",
    "includes",
    "paginate",
    "project",
    "within_budget",
]
