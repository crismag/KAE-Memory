"""Deterministic evidence-graph reconciliation (Phase 2).

This module classifies how extracted rows relate to each other. It does not
mint synthesized objects, raise attention, or change ``LifecycleState``.
Paraphrases that share no stems — the planning-expertise cluster — stay
unlinked; that is Phase 3, not a threshold to lower here.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .identifiers import KnowledgeItemId
from .lexical import (
    MIN_COVERAGE,
    NEAR_DUPLICATE_SIMILARITY,
    content_words,
    is_near_duplicate,
    is_negated,
    match,
    overlap_coefficient,
    similarity,
    stem,
    terms,
)
from .lifecycle import LifecycleState
from .models import KnowledgeItem, KnowledgeKind
from .relationships import KnowledgeRelation
from .synthesis import EvidenceRole

SUPPORT_OVERLAP = 0.55
"""Minimum overlap coefficient for a conservative same-kind support pair.

Lower than near-duplicate Jaccard on purpose: overlap handles length
asymmetry. Safeguards (minimum stems, length ratio, same kind, same polarity)
exist because a two-word actor otherwise scores 1.00 against every mention.
"""

MIN_SHARED_STEMS = 2
MIN_SIDE_STEMS = 3
MAX_LENGTH_RATIO = 3.0
NEIGHBORHOOD_LIMIT = 12

_QUESTION_PREFIXES = (
    "what ",
    "which ",
    "who ",
    "where ",
    "when ",
    "why ",
    "how ",
    "is this ",
    "are we ",
    "is it ",
)

_IDENTITY_CORE = frozenset(
    stem(word)
    for word in (
        "build",
        "building",
        "product",
        "project",
        "problem",
        "software",
        "idea",
        "plan",
        "planned",
        "planning",
    )
)
_IDENTITY_FILLER = frozenset(
    stem(word)
    for word in (
        "we",
        "us",
        "our",
        "still",
        "same",
        "current",
        "now",
        "thing",
        "being",
        "name",
        "conversation",
        "discuss",
        "discussing",
    )
)
_IDENTITY_ALLOWED = _IDENTITY_CORE | _IDENTITY_FILLER

_TURNS = re.compile(r"\bturns?\b")
_IS_A = re.compile(r"\bis an?\b")

_ENUMERATION = "—"
_CANDIDATE_SPLIT = re.compile(r"\s*,\s*|\s+or\s+")
_LEADING_OR = re.compile(r"^or\s+")
_CANDIDATE_FRAME = re.compile(
    r"^(?:is|are|does|do|should|will)\s+\w+\s+\w+(?:\s+by|\s+as|\s+through)\s+"
)
"""The interrogative frame the first candidate carries and the rest share.

*"is it defined by task completion, result publication, or …"* enumerates three
answers, and only the first one wears the verb. Left in place it adds ``defined``
to that candidate's words, which no answering statement contains.
"""

_GRAMMAR_NOT_SUBJECT = frozenset(
    stem(word) for word in ("could", "did", "do", "does", "shall", "should", "where", "would")
)
"""Modals and interrogatives :data:`_STOPWORDS` happens to omit.

Local rather than added to the lexical stopword list, which every search in the
estate reads. A question's subject is what it asks *about*, and ``should`` is
grammar — without this, *"Where **should** domain synthesizers live — Memory or
CIE?"* counts *"Home **should** say what the project is"* as being on its topic.
"""


class PairRelation(StrEnum):
    """How two evidence rows relate, before persistence."""

    SUPPORT = "support"
    CONTRADICT = "contradict"
    RESOLVE = "resolve"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """The fields reconciliation reads from an extracted row."""

    id: KnowledgeItemId
    kind: str
    content: str
    lifecycle: LifecycleState


@dataclass(frozen=True, slots=True)
class IntendedEdge:
    """One evidence-graph edge the cycle would write."""

    source_id: KnowledgeItemId
    target_id: KnowledgeItemId
    type: KnowledgeRelation
    reason: str


@dataclass(frozen=True, slots=True)
class AffectedSection:
    """A knowledge kind whose evidence graph changed, and why."""

    domain: str
    item_ids: tuple[KnowledgeItemId, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntendedGraph:
    """The evidence graph a reconciliation pass intends to persist."""

    edges: tuple[IntendedEdge, ...]
    roles: tuple[tuple[KnowledgeItemId, EvidenceRole], ...]
    affected: tuple[AffectedSection, ...]
    resolved_item_ids: tuple[KnowledgeItemId, ...]


class NeighborhoodMeasure(StrEnum):
    """How a neighbourhood was found, reported rather than assumed.

    `PHASE-2-RECONCILIATION.md` states the lexical limit plainly: the corpus's
    `planning-expertise` paraphrases share no stems (`plan` vs `plann`), so
    stem coverage cannot see them. Vectors can. A caller that cannot tell which
    measure answered cannot tell an unrelated item from an unindexed one, and
    would read *no neighbours* off a deployment that simply has no embeddings.
    """

    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Neighbor:
    """One related evidence row, for bounded LLM context later."""

    item_id: KnowledgeItemId
    score: float
    relation: str | None = None
    measure: NeighborhoodMeasure = NeighborhoodMeasure.LEXICAL


@dataclass(frozen=True, slots=True)
class Neighborhood:
    """What was found, and how — never one without the other."""

    measure: NeighborhoodMeasure
    neighbors: tuple[Neighbor, ...]

    @property
    def searchable(self) -> bool:
        """False when nothing could compare this item, by any measure."""

        return self.measure is not NeighborhoodMeasure.NONE


def snapshot_from_item(item: KnowledgeItem) -> EvidenceSnapshot:
    """Project a knowledge item onto the fields reconciliation uses."""

    return EvidenceSnapshot(
        id=item.id,
        kind=item.kind,
        content=item.current_version.content,
        lifecycle=item.lifecycle,
    )


def is_question(text: str) -> bool:
    """Return whether ``text`` is asking something rather than stating it."""

    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    lowered = stripped.lower()
    return lowered.startswith(_QUESTION_PREFIXES)


def is_identity_unknown(kind: str, text: str) -> bool:
    """Return whether this unknown is an unanswered identity question.

    Typed, not lexical-against-the-identity-statement: those questions share
    almost no stems with a long product-identity sentence. Extra content stems
    (``development-ready``, ``evidence``, ``close``) keep neighbouring unknowns
    open.
    """

    if kind != KnowledgeKind.UNKNOWN.value:
        return False
    if not is_question(text):
        return False
    words = content_words(text)
    if not words or not words <= _IDENTITY_ALLOWED:
        return False
    return bool(words & _IDENTITY_CORE)


def is_identity_statement(kind: str, text: str) -> bool:
    """Return whether this row states what the project or product is."""

    if kind not in {
        KnowledgeKind.GOAL.value,
        KnowledgeKind.DECISION.value,
        KnowledgeKind.ASSUMPTION.value,
    }:
        return False
    if is_question(text):
        return False
    lowered = text.lower()
    if _TURNS.search(lowered):
        return True
    if "is the name of" in lowered:
        return True
    named_kind = any(token in lowered for token in ("product", "system", "platform"))
    return bool(_IS_A.search(lowered) and named_kind)


def enumerated_candidates(text: str) -> tuple[str, ...]:
    """Return the answers a question offers itself, empty when it offers none.

    `EPI-4`, `D-138`. An extractor working one chunk at a time writes questions
    the rest of the corpus already answers, and the hard part is that it also
    writes questions the corpus only shares a *topic* with. Enumeration is what
    separates them: *"— at-least-once delivery, idempotency, or visibility
    timeout handling?"* names what would count as an answer, and *"what threshold
    of delivery attempts triggers the redrive policy?"* names only its subject,
    which nine statements share and none answers.
    """

    if _ENUMERATION not in text:
        return ()
    _, tail = text.split(_ENUMERATION, 1)
    candidates: list[str] = []
    for part in _CANDIDATE_SPLIT.split(tail.strip().rstrip("?").strip()):
        candidate = _CANDIDATE_FRAME.sub("", _LEADING_OR.sub("", part.strip()))
        if candidate:
            candidates.append(candidate)
    return tuple(candidates)


def question_subject(text: str) -> frozenset[str]:
    """Return the words naming what a question asks about, grammar removed."""

    subject = text.split(_ENUMERATION, 1)[0] if _ENUMERATION in text else text
    return content_words(subject) - _GRAMMAR_NOT_SUBJECT


def asserts_candidate(statement: str, candidate: str) -> bool:
    """Return whether ``statement`` supplies the whole of ``candidate``.

    Whole, not a share of it: a partial match is a statement about the same
    subject as the candidate, which is the thing this rule exists to refuse.
    """

    wanted = content_words(candidate)
    return bool(wanted) and wanted <= content_words(statement)


def is_candidate_resolution(statement: EvidenceSnapshot, unknown: EvidenceSnapshot) -> bool:
    """Return whether a statement answers an unknown that enumerated its answers.

    Two conditions, no threshold. The unknown must offer candidates, and a
    statement must assert one **and** be about what was asked — at least one word
    shared with the question's subject. The second condition is not decoration:
    without it *"Where should domain synthesizers live — Memory or CIE?"*
    resolves against *"Memory must not become a blob warehouse"*, because the
    bare candidate ``Memory`` is asserted whole by any sentence naming it.
    """

    if unknown.kind != KnowledgeKind.UNKNOWN.value or not is_question(unknown.content):
        return False
    if statement.kind == KnowledgeKind.UNKNOWN.value or is_question(statement.content):
        return False
    candidates = enumerated_candidates(unknown.content)
    if not candidates:
        return False
    if not question_subject(unknown.content) & content_words(statement.content):
        return False
    return any(asserts_candidate(statement.content, candidate) for candidate in candidates)


def claims_area_sufficient(kind: str, text: str, lifecycle: LifecycleState) -> bool:
    """Return whether a validated decision claims a discovery area is done."""

    return (
        kind == KnowledgeKind.DECISION.value
        and lifecycle is LifecycleState.VALIDATED
        and "sufficient" in text.lower()
    )


def claims_open_candidate_review(kind: str, text: str, lifecycle: LifecycleState) -> bool:
    """Return whether a proposed decision still asks to Confirm/Reject each row."""

    lowered = text.lower()
    return (
        kind == KnowledgeKind.DECISION.value
        and lifecycle is LifecycleState.PROPOSED
        and "confirm" in lowered
        and "reject" in lowered
    )


def is_support_pair(left: EvidenceSnapshot, right: EvidenceSnapshot) -> bool:
    """Return whether two same-kind, same-polarity rows support each other."""

    if left.kind != right.kind or left.id == right.id:
        return False
    if is_negated(left.content) != is_negated(right.content):
        return False
    if is_near_duplicate(left.content, right.content):
        return True
    left_words, right_words = content_words(left.content), content_words(right.content)
    shared = left_words & right_words
    if len(shared) < MIN_SHARED_STEMS:
        return False
    if min(len(left_words), len(right_words)) < MIN_SIDE_STEMS:
        return False
    longer = max(len(left_words), len(right_words))
    shorter = min(len(left_words), len(right_words))
    if shorter == 0 or longer / shorter > MAX_LENGTH_RATIO:
        return False
    return overlap_coefficient(left.content, right.content) >= SUPPORT_OVERLAP


def is_polarity_conflict(left: EvidenceSnapshot, right: EvidenceSnapshot) -> bool:
    """Return whether two same-kind rows are near-duplicates with opposite polarity."""

    if left.kind != right.kind or left.id == right.id:
        return False
    if is_negated(left.content) == is_negated(right.content):
        return False
    return similarity(left.content, right.content) >= NEAR_DUPLICATE_SIMILARITY


def is_sufficiency_conflict(left: EvidenceSnapshot, right: EvidenceSnapshot) -> bool:
    """Return whether a settled 'area sufficient' clashes with leftover review process."""

    return (
        claims_area_sufficient(left.kind, left.content, left.lifecycle)
        and claims_open_candidate_review(right.kind, right.content, right.lifecycle)
    ) or (
        claims_area_sufficient(right.kind, right.content, right.lifecycle)
        and claims_open_candidate_review(left.kind, left.content, left.lifecycle)
    )


def is_identity_resolution(left: EvidenceSnapshot, right: EvidenceSnapshot) -> bool:
    """Return whether one row is identity evidence and the other a stale identity unknown."""

    return (
        is_identity_statement(left.kind, left.content)
        and is_identity_unknown(right.kind, right.content)
    ) or (
        is_identity_statement(right.kind, right.content)
        and is_identity_unknown(left.kind, left.content)
    )


def classify_pair(left: EvidenceSnapshot, right: EvidenceSnapshot) -> PairRelation:
    """Classify one pair. Conflict outranks resolution, which outranks support."""

    if left.id == right.id:
        return PairRelation.NONE
    if is_polarity_conflict(left, right) or is_sufficiency_conflict(left, right):
        return PairRelation.CONTRADICT
    if is_identity_resolution(left, right):
        return PairRelation.RESOLVE
    if is_candidate_resolution(left, right) or is_candidate_resolution(right, left):
        return PairRelation.RESOLVE
    if is_support_pair(left, right):
        return PairRelation.SUPPORT
    return PairRelation.NONE


def lexical_neighborhood(
    focus: EvidenceSnapshot,
    candidates: Sequence[EvidenceSnapshot],
    *,
    limit: int = NEIGHBORHOOD_LIMIT,
) -> tuple[Neighbor, ...]:
    """Return same-kind lexical neighbours, highest coverage first."""

    query = terms(focus.content)
    scored: list[Neighbor] = []
    for candidate in candidates:
        if candidate.id == focus.id or candidate.kind != focus.kind:
            continue
        result = match(query, candidate.content)
        if result.score >= MIN_COVERAGE:
            scored.append(Neighbor(item_id=candidate.id, score=result.score))
    scored.sort(key=lambda neighbor: (-neighbor.score, str(neighbor.item_id)))
    return tuple(scored[:limit])


def semantic_neighborhood(
    distances: Sequence[tuple[KnowledgeItemId, float]],
    *,
    limit: int = NEIGHBORHOOD_LIMIT,
) -> tuple[Neighbor, ...]:
    """Turn cosine distances into neighbours scored the way lexical ones are.

    Both measures must read the same direction — higher is closer — or a caller
    merging them silently ranks the least related first. Cosine distance over
    normalised vectors is in `[0, 2]`; `1 - distance` is the similarity, floored
    at zero so an opposed pair scores nothing rather than negatively.
    """

    scored = [
        Neighbor(
            item_id=item_id,
            score=max(0.0, 1.0 - float(distance)),
            measure=NeighborhoodMeasure.SEMANTIC,
        )
        for item_id, distance in distances
    ]
    scored.sort(key=lambda neighbor: (-neighbor.score, str(neighbor.item_id)))
    return tuple(scored[:limit])


def plan_reconciliation(
    snapshots: Sequence[EvidenceSnapshot],
    focus_ids: frozenset[KnowledgeItemId] | None = None,
) -> IntendedGraph:
    """Compute support, conflict, and resolution edges without touching storage.

    ``focus_ids`` restricts which pairs are considered (incremental). ``None``
    is a full pass. Canonical support members stay ``active``; duplicates become
    ``supporting``. Identity unknowns become ``resolved``. Lifecycle is not
    consulted except for sufficiency conflicts.
    """

    items = {item.id: item for item in snapshots}
    edges: list[IntendedEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def _consider(left: EvidenceSnapshot, right: EvidenceSnapshot) -> bool:
        if focus_ids is None:
            return True
        return left.id in focus_ids or right.id in focus_ids

    def _add(edge: IntendedEdge) -> None:
        key = (str(edge.source_id), str(edge.target_id), edge.type.value)
        if key in seen:
            return
        seen.add(key)
        edges.append(edge)

    consider = _consider
    add_edge = _add
    _add_support_edges(tuple(snapshots), consider, add_edge)
    _add_conflict_edges(tuple(snapshots), consider, add_edge)
    _add_resolution_edges(tuple(snapshots), consider, add_edge)

    roles = _roles_for(edges)
    resolved = tuple(item_id for item_id, role in roles if role is EvidenceRole.RESOLVED)
    affected = _affected_sections(edges, items)
    return IntendedGraph(
        edges=tuple(edges),
        roles=roles,
        affected=affected,
        resolved_item_ids=resolved,
    )


def _add_support_edges(
    snapshots: tuple[EvidenceSnapshot, ...],
    consider: Callable[[EvidenceSnapshot, EvidenceSnapshot], bool],
    add: Callable[[IntendedEdge], None],
) -> None:
    parent = {item.id: item.id for item in snapshots}

    def root(item_id: KnowledgeItemId) -> KnowledgeItemId:
        while parent[item_id] != item_id:
            parent[item_id] = parent[parent[item_id]]
            item_id = parent[item_id]
        return item_id

    for index, left in enumerate(snapshots):
        for right in snapshots[index + 1 :]:
            if not consider(left, right):
                continue
            if not is_support_pair(left, right):
                continue
            parent[root(right.id)] = root(left.id)

    clustered: dict[KnowledgeItemId, list[EvidenceSnapshot]] = {}
    for item in snapshots:
        clustered.setdefault(root(item.id), []).append(item)
    for members in clustered.values():
        if len(members) < 2:
            continue
        canonical = _canonical(members)
        for member in members:
            if member.id == canonical.id:
                continue
            add(
                IntendedEdge(
                    source_id=member.id,
                    target_id=canonical.id,
                    type=KnowledgeRelation.SUPPORTS,
                    reason="support",
                )
            )


def _add_conflict_edges(
    snapshots: tuple[EvidenceSnapshot, ...],
    consider: Callable[[EvidenceSnapshot, EvidenceSnapshot], bool],
    add: Callable[[IntendedEdge], None],
) -> None:
    for index, left in enumerate(snapshots):
        for right in snapshots[index + 1 :]:
            if not consider(left, right):
                continue
            if is_polarity_conflict(left, right):
                source, target = _conflict_direction(left, right)
                add(
                    IntendedEdge(
                        source_id=source.id,
                        target_id=target.id,
                        type=KnowledgeRelation.CONTRADICTS,
                        reason="polarity",
                    )
                )
            elif is_sufficiency_conflict(left, right):
                settled = (
                    left
                    if claims_area_sufficient(left.kind, left.content, left.lifecycle)
                    else right
                )
                leftover = right if settled is left else left
                add(
                    IntendedEdge(
                        source_id=settled.id,
                        target_id=leftover.id,
                        type=KnowledgeRelation.CONTRADICTS,
                        reason="sufficiency",
                    )
                )


def _add_resolution_edges(
    snapshots: tuple[EvidenceSnapshot, ...],
    consider: Callable[[EvidenceSnapshot, EvidenceSnapshot], bool],
    add: Callable[[IntendedEdge], None],
) -> None:
    _add_identity_resolution_edges(snapshots, consider, add)
    _add_candidate_resolution_edges(snapshots, consider, add)


def _add_identity_resolution_edges(
    snapshots: tuple[EvidenceSnapshot, ...],
    consider: Callable[[EvidenceSnapshot, EvidenceSnapshot], bool],
    add: Callable[[IntendedEdge], None],
) -> None:
    statements = [item for item in snapshots if is_identity_statement(item.kind, item.content)]
    unknowns = [item for item in snapshots if is_identity_unknown(item.kind, item.content)]
    if not statements or not unknowns:
        return
    resolver = _canonical(statements)
    for unknown in unknowns:
        if not consider(resolver, unknown):
            continue
        add(
            IntendedEdge(
                source_id=resolver.id,
                target_id=unknown.id,
                type=KnowledgeRelation.SUPERSEDES,
                reason="identity_resolution",
            )
        )


def _add_candidate_resolution_edges(
    snapshots: tuple[EvidenceSnapshot, ...],
    consider: Callable[[EvidenceSnapshot, EvidenceSnapshot], bool],
    add: Callable[[IntendedEdge], None],
) -> None:
    """`EPI-4`: one edge per unknown that enumerated its answers and got one.

    Only the canonical resolver, the way identity resolution takes one: a
    question answered by three statements is answered once, and three edges would
    make the same fact read as corroboration.
    """

    unknowns = [item for item in snapshots if enumerated_candidates(item.content)]
    if not unknowns:
        return
    for unknown in unknowns:
        resolvers = [
            item
            for item in snapshots
            if item.id != unknown.id
            and consider(item, unknown)
            and is_candidate_resolution(item, unknown)
        ]
        if not resolvers:
            continue
        add(
            IntendedEdge(
                source_id=_canonical(resolvers).id,
                target_id=unknown.id,
                type=KnowledgeRelation.SUPERSEDES,
                reason="candidate_resolution",
            )
        )


def _canonical(members: Sequence[EvidenceSnapshot]) -> EvidenceSnapshot:
    return sorted(members, key=lambda item: (-len(item.content), str(item.id)))[0]


def _conflict_direction(
    left: EvidenceSnapshot, right: EvidenceSnapshot
) -> tuple[EvidenceSnapshot, EvidenceSnapshot]:
    validated = LifecycleState.VALIDATED
    if left.lifecycle is validated and right.lifecycle is not validated:
        return left, right
    if right.lifecycle is validated and left.lifecycle is not validated:
        return right, left
    ordered = sorted((left, right), key=lambda item: str(item.id))
    return ordered[0], ordered[1]


def _roles_for(
    edges: Sequence[IntendedEdge],
) -> tuple[tuple[KnowledgeItemId, EvidenceRole], ...]:
    roles: dict[KnowledgeItemId, EvidenceRole] = {}

    def assign(item_id: KnowledgeItemId, role: EvidenceRole) -> None:
        current = roles.get(item_id)
        if current is None or _role_rank(role) >= _role_rank(current):
            roles[item_id] = role

    for edge in edges:
        if edge.type is KnowledgeRelation.SUPPORTS:
            assign(edge.source_id, EvidenceRole.SUPPORTING)
        elif edge.type is KnowledgeRelation.CONTRADICTS:
            if edge.reason == "sufficiency":
                assign(edge.target_id, EvidenceRole.CONFLICTING)
            else:
                assign(edge.source_id, EvidenceRole.CONFLICTING)
                assign(edge.target_id, EvidenceRole.CONFLICTING)
        elif edge.type is KnowledgeRelation.SUPERSEDES:
            assign(edge.target_id, EvidenceRole.RESOLVED)
    return tuple(sorted(roles.items(), key=lambda pair: str(pair[0])))


def _role_rank(role: EvidenceRole) -> int:
    return {
        EvidenceRole.ACTIVE: 0,
        EvidenceRole.SUPPORTING: 1,
        EvidenceRole.SUPERSEDED: 2,
        EvidenceRole.CONFLICTING: 3,
        EvidenceRole.RESOLVED: 4,
        EvidenceRole.HISTORICAL: 5,
        EvidenceRole.NOISE: 6,
        EvidenceRole.ARCHIVED: 7,
    }[role]


def _affected_sections(
    edges: Sequence[IntendedEdge], items: dict[KnowledgeItemId, EvidenceSnapshot]
) -> tuple[AffectedSection, ...]:
    by_kind: dict[str, dict[str, list[KnowledgeItemId]]] = {}
    for edge in edges:
        for item_id in (edge.source_id, edge.target_id):
            snapshot = items.get(item_id)
            if snapshot is None:
                continue
            bucket = by_kind.setdefault(snapshot.kind, {})
            bucket.setdefault(edge.reason, []).append(item_id)
    sections: list[AffectedSection] = []
    for kind in sorted(by_kind):
        reasons = tuple(sorted(by_kind[kind]))
        unique_ids = {item_id for ids in by_kind[kind].values() for item_id in ids}
        item_ids = tuple(sorted(unique_ids, key=str))
        sections.append(AffectedSection(domain=kind, item_ids=item_ids, reasons=reasons))
    return tuple(sections)


__all__ = [
    "MAX_LENGTH_RATIO",
    "MIN_SHARED_STEMS",
    "MIN_SIDE_STEMS",
    "NEIGHBORHOOD_LIMIT",
    "SUPPORT_OVERLAP",
    "AffectedSection",
    "EvidenceSnapshot",
    "IntendedEdge",
    "IntendedGraph",
    "Neighbor",
    "PairRelation",
    "asserts_candidate",
    "claims_area_sufficient",
    "claims_open_candidate_review",
    "classify_pair",
    "enumerated_candidates",
    "is_candidate_resolution",
    "is_identity_resolution",
    "is_identity_statement",
    "is_identity_unknown",
    "is_polarity_conflict",
    "is_question",
    "is_sufficiency_conflict",
    "is_support_pair",
    "lexical_neighborhood",
    "plan_reconciliation",
    "question_subject",
    "snapshot_from_item",
]
