"""Quality findings, derived from operational data.

FR-015: reporting is a view over operational data, not a separate analytics
platform. Every finding here is a function of knowledge, area links, blockers,
relationships, and the readiness template — computed on request, never stored
(ADR-0015). A stored copy could disagree with the state it describes, and keeping
it honest would need invalidation on every authoritative write.

So findings have no identity and cannot be dismissed. One disappears when the
condition that produced it does: confirm the knowledge, assign the area, resolve
the contradiction, close the blocker. Acting on a finding means changing the
state.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
from kae_memory.domain.lexical import is_near_duplicate
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, RelationshipType
from kae_memory.domain.readiness import (
    SOFTWARE_TEMPLATE,
    UNFINISHED_STATES,
    AreaState,
    BlockerSeverity,
    BlockerStatus,
    ReadinessTemplate,
)
from kae_memory.persistence.readiness_repositories import (
    BlockerRepository,
    KnowledgeAreaLinkRepository,
    RelationshipRepository,
)
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction

from .readiness_service import evaluate_area


class FindingKind(StrEnum):
    """What a finding is about."""

    MISSING_AREA = "missing_area"
    PARTIAL_AREA = "partial_area"
    UNCLASSIFIED_KNOWLEDGE = "unclassified_knowledge"
    UNCONFIRMED_KNOWLEDGE = "unconfirmed_knowledge"
    OPEN_QUESTION = "open_question"
    UNRESOLVED_CONTRADICTION = "unresolved_contradiction"
    DUPLICATE_KNOWLEDGE = "duplicate_knowledge"
    OPEN_BLOCKER = "open_blocker"


class Severity(StrEnum):
    """How much a finding matters.

    ``CRITICAL`` is reserved for conditions that block an implementation
    blueprint. A report where everything is urgent is a report nobody reads.
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a reviewer should know without inspecting the database."""

    kind: FindingKind
    severity: Severity
    summary: str
    recommended_action: str
    area_key: str | None = None
    knowledge_item_ids: tuple[KnowledgeItemId, ...] = ()
    subject_key: str = ""
    """What this finding is about, when the area alone does not say.

    A question's identity is `(finding_kind, area_key)` plus, for aggregates,
    nothing more — several unknowns in one area are one decision that grows
    (D-11). That is right for `open_question` and wrong for anything where each
    finding is its own decision.

    `open_blocker` is the case. Blockers carry no knowledge ids, so two
    different blockers in one area produced identical keys and the second was
    treated as already asked — it never reached anybody. This names the blocker
    instead.

    **Never wording.** The summary and the recommended action are prose that can
    be rephrased, and identity that moves when the words move is not identity.
    """


class ReviewService:
    """Derives quality findings for a project."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        policy: RetryPolicy | None = None,
        template: ReadinessTemplate = SOFTWARE_TEMPLATE,
    ) -> None:
        self._session_factory = session_factory
        self._policy = policy or RetryPolicy()
        self._template = template

    def _run[ResultT](self, operation: Callable[[DbSession], ResultT]) -> ResultT:
        return run_transaction(self._session_factory, operation, self._policy)

    def findings(self, project_id: ProjectId) -> tuple[Finding, ...]:
        """Return a project's findings, most severe first.

        Read in one transaction so the findings describe a single consistent
        state rather than a moving one.
        """

        def operation(session: DbSession) -> tuple[Finding, ...]:
            items = SqlAlchemyKnowledgeRepository(session).list_for_project(project_id, None)
            links = KnowledgeAreaLinkRepository(session).list_for_project(project_id)
            contradictions = RelationshipRepository(session).list_for_project(
                project_id, RelationshipType.CONTRADICTS, unresolved_only=True
            )
            blockers = BlockerRepository(session).list_for_project(project_id, BlockerStatus.OPEN)

            by_area: dict[str, list[KnowledgeItem]] = {}
            classified: set[str] = set()
            index = {str(item.id): item for item in items}
            for link in links:
                item = index.get(str(link.knowledge_item_id))
                if item is not None:
                    by_area.setdefault(link.area_key, []).append(item)
                    classified.add(str(item.id))

            found: list[Finding] = []

            for area in self._template.areas:
                result = evaluate_area(area, by_area.get(area.key, ()), frozenset())
                if result.state is AreaState.MISSING:
                    found.append(
                        Finding(
                            kind=FindingKind.MISSING_AREA,
                            # Only mandatory areas block a blueprint, so only they
                            # are critical. Flagging optional gaps as urgent would
                            # train a reader to ignore the colour.
                            severity=Severity.CRITICAL if area.mandatory else Severity.MINOR,
                            summary=f"{area.name} has no confirmed knowledge.",
                            recommended_action=(
                                f"Discuss {area.name.lower()} and confirm at least "
                                f"{area.minimum_confirmed} item(s)."
                            ),
                            area_key=area.key,
                        )
                    )
                elif result.state in UNFINISHED_STATES:
                    found.append(
                        Finding(
                            kind=FindingKind.PARTIAL_AREA,
                            severity=Severity.MAJOR if area.mandatory else Severity.MINOR,
                            summary=(
                                f"{area.name} has {result.confirmed_count} confirmed item(s); "
                                f"{area.minimum_confirmed} are required."
                            ),
                            recommended_action=f"Confirm more knowledge for {area.name.lower()}.",
                            area_key=area.key,
                        )
                    )

            for relationship in contradictions:
                found.append(
                    Finding(
                        kind=FindingKind.UNRESOLVED_CONTRADICTION,
                        severity=Severity.CRITICAL,
                        summary="Two knowledge items contradict each other.",
                        recommended_action=(
                            "Supersede one item, or resolve the contradiction with a note."
                        ),
                        knowledge_item_ids=(relationship.source_id, relationship.target_id),
                    )
                )

            for first, second in _near_duplicates(items):
                found.append(
                    Finding(
                        kind=FindingKind.DUPLICATE_KNOWLEDGE,
                        # Major, not critical. A duplicate overstates coverage,
                        # which misleads; it does not make the project
                        # undeliverable the way an empty mandatory area does.
                        severity=Severity.MAJOR,
                        summary=(
                            "Two statements say the same thing, so the area counts them twice."
                        ),
                        recommended_action=(
                            "Keep one and reject or supersede the other. Merging the "
                            "wording is a judgement about meaning, so it is not done "
                            "automatically."
                        ),
                        knowledge_item_ids=(first.id, second.id),
                    )
                )

            for blocker in blockers:
                found.append(
                    Finding(
                        kind=FindingKind.OPEN_BLOCKER,
                        severity=(
                            Severity.CRITICAL
                            if blocker.severity is BlockerSeverity.CRITICAL
                            else Severity.MAJOR
                        ),
                        summary=blocker.summary,
                        recommended_action="Close the blocker, or accept it as an assumption.",
                        area_key=blocker.area_key,
                        # Each blocker is its own decision. Without this, two in
                        # one area are one question and the second is silently
                        # treated as already asked.
                        subject_key=str(blocker.id),
                    )
                )

            live = [
                item
                for item in items
                if item.lifecycle in (LifecycleState.PROPOSED, LifecycleState.VALIDATED)
            ]
            unconfirmed = [item for item in live if item.lifecycle is LifecycleState.PROPOSED]
            if unconfirmed:
                found.append(
                    Finding(
                        kind=FindingKind.UNCONFIRMED_KNOWLEDGE,
                        severity=Severity.MAJOR,
                        summary=f"{len(unconfirmed)} candidate(s) await human review.",
                        recommended_action=(
                            "Confirm or reject each candidate. Unconfirmed knowledge "
                            "never completes an area."
                        ),
                        knowledge_item_ids=tuple(item.id for item in unconfirmed),
                    )
                )

            unclassified = [item for item in live if str(item.id) not in classified]
            if unclassified:
                found.append(
                    Finding(
                        kind=FindingKind.UNCLASSIFIED_KNOWLEDGE,
                        severity=Severity.MAJOR,
                        summary=(
                            f"{len(unclassified)} item(s) belong to no discovery area, so they "
                            "contribute nothing to readiness."
                        ),
                        recommended_action="Assign each item to the area it serves.",
                        knowledge_item_ids=tuple(item.id for item in unclassified),
                    )
                )

            questions = [item for item in live if item.kind == KnowledgeKind.UNKNOWN.value]
            if questions:
                found.append(
                    Finding(
                        kind=FindingKind.OPEN_QUESTION,
                        severity=Severity.MAJOR,
                        summary=f"{len(questions)} open question(s) the project recorded.",
                        recommended_action=(
                            "Answer each question and record the answer, or accept it "
                            "as an assumption."
                        ),
                        knowledge_item_ids=tuple(item.id for item in questions),
                    )
                )

            order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
            return tuple(sorted(found, key=lambda finding: order[finding.severity]))

        return self._run(operation)

    def summary(self, project_id: ProjectId) -> dict[str, int]:
        """Return finding counts by severity, for a report header."""

        found = self.findings(project_id)
        return {
            "total": len(found),
            **{
                severity.value: sum(1 for finding in found if finding.severity is severity)
                for severity in Severity
            },
        }


def unambiguous_area_for(kind: str, template: ReadinessTemplate = SOFTWARE_TEMPLATE) -> str | None:
    """Return the one area that accepts ``kind``, or ``None`` if several do.

    Refusing to guess is the point. Choosing between "functional requirements"
    and "quality attributes" for a `requirement` is exactly the discrimination a
    model is for, and inventing it offline would manufacture coverage a user
    would then have to unpick (ADR-0015).
    """

    accepting = [
        area.key for area in template.areas if any(member.value == kind for member in area.kinds)
    ]
    return accepting[0] if len(accepting) == 1 else None


def classify_offline(
    items: Sequence[KnowledgeItem], template: ReadinessTemplate = SOFTWARE_TEMPLATE
) -> tuple[tuple[KnowledgeItemId, str], ...]:
    """Return the area assignments that need no judgement."""

    assignments = []
    for item in items:
        area = unambiguous_area_for(item.kind, template)
        if area is not None:
            assignments.append((item.id, area))
    return tuple(assignments)


__all__ = [
    "Finding",
    "FindingKind",
    "ReviewService",
    "Severity",
    "classify_offline",
    "unambiguous_area_for",
]


def _near_duplicates(
    items: Sequence[KnowledgeItem],
) -> tuple[tuple[KnowledgeItem, KnowledgeItem], ...]:
    """Return statement pairs that say the same thing.

    Only among knowledge a human has confirmed. Two unconfirmed candidates
    overlapping is the extractor doing its job on overlapping input, and the
    review queue already shows them side by side; a duplicate matters once it is
    confirmed, because that is when it starts counting toward an area twice.

    Identical statements never reach here — those collapse on write. What is
    left is genuine near-duplication, which needs a person.
    """

    confirmed = [item for item in items if item.lifecycle is LifecycleState.VALIDATED]
    pairs: list[tuple[KnowledgeItem, KnowledgeItem]] = []
    for index, first in enumerate(confirmed):
        for second in confirmed[index + 1 :]:
            if first.kind != second.kind:
                continue
            if is_near_duplicate(first.current_version.content, second.current_version.content):
                pairs.append((first, second))
    return tuple(pairs)
