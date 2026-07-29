"""Blueprint generation and knowledge traceability.

Every statement is a confirmed knowledge item's own text, grouped by the area it
was assigned to. **No model writes blueprint prose** (ADR-0016): a model asked to
write the blueprint would produce fluent connective text that no knowledge item
supports, and every sentence of it would be unattributable — the exact failure
FR-008's labelling exists to prevent.

Like findings, a blueprint is derived rather than stored. It is a function of
confirmed knowledge, area links, and the readiness template, so a stored copy
would go stale against the knowledge it claims to describe.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.identifiers import (
    AgentRunId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    SessionId,
)
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import (
    KnowledgeItem,
    KnowledgeKind,
    ProvenanceLink,
    ProvenanceLinkType,
)
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE, ReadinessTemplate
from kae_memory.persistence.readiness_repositories import KnowledgeAreaLinkRepository
from kae_memory.persistence.repositories import SqlAlchemyKnowledgeRepository
from kae_memory.persistence.transactions import RetryPolicy, run_transaction
from kae_memory.persistence.workspace_repositories import (
    MessageRepository,
    ProvenanceLinkRepository,
    SessionRepository,
)


class StatementLabel(StrEnum):
    """Where a statement's authority comes from.

    Computed from provenance, never asserted.
    """

    GROUNDED = "grounded"
    DERIVED = "derived"
    ASSUMPTION = "assumption"


@dataclass(frozen=True, slots=True)
class BlueprintStatement:
    """One statement, with everything needed to justify it."""

    id: str
    text: str
    label: StatementLabel
    kind: str
    knowledge_item_id: KnowledgeItemId
    knowledge_version: int
    source_message_id: MessageId | None
    produced_by_run_id: AgentRunId | None


@dataclass(frozen=True, slots=True)
class BlueprintSection:
    """One discovery area's statements."""

    area_key: str
    area_name: str
    statements: tuple[BlueprintStatement, ...]


@dataclass(frozen=True, slots=True)
class Blueprint:
    """A rendering of confirmed knowledge, with its own limits attached."""

    project_id: ProjectId
    project_name: str
    sections: tuple[BlueprintSection, ...]
    complete: bool
    draft_eligible: bool
    implementation_eligible: bool
    readiness_percentage: int
    missing_mandatory_areas: tuple[str, ...]
    open_questions: tuple[str, ...]
    unassigned_confirmed_count: int

    @property
    def statement_count(self) -> int:
        """How many statements the blueprint contains."""

        return sum(len(section.statements) for section in self.sections)


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One link in a knowledge item's chain of custody."""

    relation: str
    reference: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeTrace:
    """The full chain: project, session, message, run, knowledge, versions."""

    knowledge_item_id: KnowledgeItemId
    project_id: ProjectId
    kind: str
    lifecycle: str
    current_content: str
    produced_by_run_id: AgentRunId | None
    used_by_run_ids: tuple[AgentRunId, ...]
    source_message_ids: tuple[MessageId, ...]
    session_ids: tuple[SessionId, ...]
    steps: tuple[TraceStep, ...]


def statement_id(project_id: ProjectId, area_key: str, item_id: KnowledgeItemId) -> str:
    """Return a stable identifier for a statement.

    Deterministic rather than random: the same statement keeps its identifier
    across regenerations, so a client can link to one, and a statement that
    disappears did so because its knowledge changed — not because the identifier
    churned.
    """

    return str(uuid5(NAMESPACE_URL, f"kae:blueprint:{project_id}:{area_key}:{item_id}"))


def label_for(item: KnowledgeItem, links: tuple[ProvenanceLink, ...]) -> StatementLabel:
    """Return a statement's label from its provenance.

    ``assumption`` wins over the others: something the project assumed stays an
    assumption even when a message prompted it, and calling it ``grounded`` would
    overstate its standing.
    """

    if item.kind == KnowledgeKind.ASSUMPTION.value:
        return StatementLabel.ASSUMPTION
    if any(link.link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE for link in links):
        return StatementLabel.GROUNDED
    return StatementLabel.DERIVED


class BlueprintService:
    """Generates blueprints and traces statements back to their evidence."""

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

    def generate(
        self,
        project_id: ProjectId,
        project_name: str,
        readiness_percentage: int,
        draft_eligible: bool,
        implementation_eligible: bool,
        missing_mandatory_areas: tuple[str, ...],
    ) -> Blueprint:
        """Render confirmed knowledge as a blueprint.

        Rendered even below the draft threshold, marked incomplete. Refusing
        would tell a user nothing about *what is missing*, and the missing-area
        list is the most useful thing an early blueprint can say.
        """

        def operation(session: DbSession) -> Blueprint:
            knowledge = SqlAlchemyKnowledgeRepository(session)
            links_repo = ProvenanceLinkRepository(session)
            confirmed = knowledge.list_for_project(project_id, LifecycleState.VALIDATED)
            by_id = {str(item.id): item for item in confirmed}
            assignments = KnowledgeAreaLinkRepository(session).list_for_project(project_id)

            assigned: dict[str, list[KnowledgeItem]] = {}
            seen: set[str] = set()
            for link in assignments:
                item = by_id.get(str(link.knowledge_item_id))
                if item is not None:
                    assigned.setdefault(link.area_key, []).append(item)
                    seen.add(str(item.id))

            sections = []
            for area in self._template.areas:
                items = assigned.get(area.key, [])
                if not items:
                    continue
                statements = tuple(
                    self._statement(project_id, area.key, item, links_repo.list_for_item(item.id))
                    for item in items
                )
                sections.append(
                    BlueprintSection(area_key=area.key, area_name=area.name, statements=statements)
                )

            questions = tuple(
                item.current_version.content
                for item in knowledge.list_for_project(project_id, None)
                if item.kind == KnowledgeKind.UNKNOWN.value
                and item.lifecycle in (LifecycleState.PROPOSED, LifecycleState.VALIDATED)
            )

            return Blueprint(
                project_id=project_id,
                project_name=project_name,
                sections=tuple(sections),
                complete=implementation_eligible,
                draft_eligible=draft_eligible,
                implementation_eligible=implementation_eligible,
                readiness_percentage=readiness_percentage,
                missing_mandatory_areas=missing_mandatory_areas,
                open_questions=questions,
                unassigned_confirmed_count=len(confirmed) - len(seen),
            )

        return self._run(operation)

    def _statement(
        self,
        project_id: ProjectId,
        area_key: str,
        item: KnowledgeItem,
        links: tuple[ProvenanceLink, ...],
    ) -> BlueprintStatement:
        message = next(
            (
                link.message_id
                for link in links
                if link.link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE
            ),
            None,
        )
        produced_by = next(
            (
                link.agent_run_id
                for link in links
                if link.link_type is ProvenanceLinkType.PRODUCED_BY
            ),
            None,
        )
        return BlueprintStatement(
            id=statement_id(project_id, area_key, item.id),
            text=item.current_version.content,
            label=label_for(item, links),
            kind=item.kind,
            knowledge_item_id=item.id,
            knowledge_version=item.current_version.number,
            source_message_id=message,
            produced_by_run_id=produced_by,
        )

    def trace(self, item_id: KnowledgeItemId) -> KnowledgeTrace | None:
        """Return a knowledge item's full chain of custody.

        Assembled from ``knowledge_provenance_links``, which M5 created for
        exactly this question and which nothing had read until now.
        """

        def operation(session: DbSession) -> KnowledgeTrace | None:
            item = SqlAlchemyKnowledgeRepository(session).get(item_id)
            if item is None:
                return None
            links = ProvenanceLinkRepository(session).list_for_item(item_id)
            messages = MessageRepository(session)
            sessions = SessionRepository(session)

            produced_by = next(
                (
                    link.agent_run_id
                    for link in links
                    if link.link_type is ProvenanceLinkType.PRODUCED_BY
                ),
                None,
            )
            used_by = tuple(
                link.agent_run_id
                for link in links
                if link.link_type is ProvenanceLinkType.USED_BY and link.agent_run_id
            )
            message_ids = tuple(
                link.message_id
                for link in links
                if link.link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE and link.message_id
            )

            steps: list[TraceStep] = [
                TraceStep("project", str(item.project_id)),
            ]
            session_ids: list[SessionId] = []
            for message_id in message_ids:
                message = messages.get(message_id)
                if message is None:  # pragma: no cover - messages are never deleted
                    continue
                session_ids.append(message.session_id)
                working = sessions.get(message.session_id)
                if working is not None:
                    steps.append(TraceStep("session", str(working.id), working.type.value))
                steps.append(TraceStep("source_message", str(message.id), message.content))
            if produced_by is not None:
                steps.append(TraceStep("produced_by_run", str(produced_by)))
            for run_id in used_by:
                steps.append(TraceStep("used_by_run", str(run_id)))
            for version in item.versions:
                steps.append(
                    TraceStep(
                        "knowledge_version",
                        str(version.number),
                        version.provenance.source,
                    )
                )

            return KnowledgeTrace(
                knowledge_item_id=item.id,
                project_id=item.project_id,
                kind=item.kind,
                lifecycle=item.lifecycle.value,
                current_content=item.current_version.content,
                produced_by_run_id=produced_by,
                used_by_run_ids=used_by,
                source_message_ids=message_ids,
                session_ids=tuple(dict.fromkeys(session_ids)),
                steps=tuple(steps),
            )

        return self._run(operation)


def render_markdown(blueprint: Blueprint) -> str:
    """Render a blueprint as Markdown (FR-008).

    A rendering of the same structure the JSON exposes, so the two cannot
    disagree. Every statement carries its label and its knowledge identifier, so
    an exported document is as traceable as the API response.
    """

    status = (
        "Implementation blueprint"
        if blueprint.implementation_eligible
        else "Draft blueprint — incomplete"
    )
    lines = [
        f"# {blueprint.project_name}",
        "",
        f"**{status}** · readiness {blueprint.readiness_percentage}%"
        f" · {blueprint.statement_count} statement(s)",
        "",
    ]

    if not blueprint.implementation_eligible:
        lines += [
            "> This blueprint is not authorised for implementation. Everything below",
            "> traces to confirmed knowledge, but the gaps listed at the end are open.",
            "",
        ]

    for section in blueprint.sections:
        lines += [f"## {section.area_name}", ""]
        for statement in section.statements:
            lines.append(
                f"- {statement.text} "
                f"*[{statement.label.value}; knowledge {statement.knowledge_item_id}]*"
            )
        lines.append("")

    if not blueprint.sections:
        lines += [
            "## No sections yet",
            "",
            "No confirmed knowledge is assigned to a discovery area, so there is",
            "nothing to render. Confirm knowledge and assign it to an area.",
            "",
        ]

    if blueprint.missing_mandatory_areas:
        lines += ["## Missing mandatory areas", ""]
        lines += [f"- {area}" for area in blueprint.missing_mandatory_areas]
        lines.append("")

    if blueprint.open_questions:
        lines += ["## Open questions", ""]
        lines += [f"- {question}" for question in blueprint.open_questions]
        lines.append("")

    if blueprint.unassigned_confirmed_count:
        lines += [
            "## Not represented",
            "",
            f"{blueprint.unassigned_confirmed_count} confirmed item(s) belong to no "
            "discovery area and therefore appear in no section above.",
            "",
        ]

    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "Blueprint",
    "BlueprintSection",
    "BlueprintService",
    "BlueprintStatement",
    "KnowledgeTrace",
    "StatementLabel",
    "TraceStep",
    "label_for",
    "render_markdown",
    "statement_id",
]
