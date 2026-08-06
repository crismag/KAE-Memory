"""Preliminary context: what a project has when it has almost nothing (N44).

A manual test asked KAE to produce the most useful project output it could from
one sentence. Every subsystem behaved correctly and the result was still a
failure, because nothing composed what they each held. The candidates were in
one place, the assumptions in another, the questions in a third, and the
assembled package showed only confirmed knowledge — of which there was none.

This service composes them. It **reads and never writes**, which is what makes
it safe to call at any readiness: it cannot confirm, cannot accept, and cannot
promote, so there is no state in which producing preliminary context is a risk
worth gating. Incomplete project knowledge is a normal project condition.

The one rule the shape enforces is that **known, assumed, and unknown never
merge**. They are three separate collections, each entry carries its own
epistemic status, and there is no field a reader can consult that blends them.
A preliminary context whose reader cannot tell a confirmed requirement from a
plausible guess is worse than no preliminary context: it is the same document
with the warning removed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.assumptions import Assumption, disclosure
from kae_memory.domain.generation import GenerationMode
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.workspace import MessageType

from .assembly_service import (
    AssembledStatement,
    AssemblyPurpose,
    AssemblyService,
    ContextAssembly,
)
from .assumption_service import AssumptionService
from .clarification_service import ClarificationService, OpenQuestion
from .memory_service import MemoryService
from .readiness_service import ReadinessService

STATED_TYPES: frozenset[MessageType] = frozenset(
    {MessageType.INPUT, MessageType.ANSWER, MessageType.PROPOSAL}
)
"""Message kinds that record something someone said about the project.

`PROPOSAL` is here because that is how `kae_submit_observation` records an
observation — a person's sentence, relayed by an agent. Excluding it would drop
the only thing a one-sentence project has.

Excluded: review findings and confirmations, which are KAE's own output. A
document that quoted those back as things that were said would be citing itself.
"""

MATERIAL_SEVERITIES: frozenset[str] = frozenset({"critical"})
"""Severities that make an unknown material rather than deferrable.

A material unknown is one whose answer would change the shape of the work, not
one that would merely improve it. The distinction exists so that a project with
twenty open questions does not read as twenty reasons to stop — the register's
words: ten helpful questions never make a project look blocked.

**Material is not blocking.** Nothing here refuses anything; the split tells a
reader which questions to spend a person's attention on first.
"""


@dataclass(frozen=True, slots=True)
class AssumedEntry:
    """One assumption, rendered with what it would cost to be wrong."""

    assumption_id: str
    subject: str
    assumed_value: str
    reason: str
    origin: str
    consequence: str
    state: str
    reversible: bool
    material: bool
    """Architectural, unsafe, or irreversible. The ones worth a person's time."""
    accepted_by: str | None
    disclosure: str
    """A line a reader can act on, including the consequence (see `disclosure`).

    Rendered here rather than by each caller so that no adapter can quietly
    render an assumption without its consequence, which is the sentence that
    turns a nod into a decision.
    """


@dataclass(frozen=True, slots=True)
class UnknownEntry:
    """One thing nobody has decided, and whether it is worth deciding now."""

    clarification_id: str
    question: str
    area_key: str | None
    severity: str
    finding_kind: str
    material: bool
    disposition: str
    """`open` means nobody was asked. Anything else means someone was asked and
    did not decide — which is different, and must stay visible (N36)."""


@dataclass(frozen=True, slots=True)
class StatedEntry:
    """One thing that was said, exactly as it was recorded.

    `actor_type` is carried rather than flattened away because an observation
    an agent relayed and a sentence a person typed are not the same evidence,
    and a document that presents them identically is overstating the second.
    """

    message_id: str
    text: str
    actor_type: str
    message_type: str


@dataclass(frozen=True, slots=True)
class PreliminaryContext:
    """What a project knows, what it is guessing, and what nobody has decided.

    The three are separate fields rather than one annotated list because a
    reader under time pressure reads structure before labels.
    """

    project_id: str
    project_name: str
    generated_at: datetime
    knowledge_revision: int
    readiness_percentage: int
    stated_verbatim: tuple[StatedEntry, ...]
    """What a person actually said, unparaphrased.

    First because everything else in this object is derived from it, and because
    a preliminary context is most often wrong in its interpretation rather than
    in its transcription. A reader who can see the original sentence can catch
    that; one who cannot, cannot.
    """
    known: tuple[AssembledStatement, ...]
    """Confirmed by a person. Frequently empty, and that is not an error."""
    proposed: tuple[AssembledStatement, ...]
    """Extracted from real evidence and **not** confirmed by anyone."""
    assumed: tuple[AssumedEntry, ...]
    material_unknowns: tuple[UnknownEntry, ...]
    deferrable_unknowns: tuple[UnknownEntry, ...]
    assembly: ContextAssembly
    """The package this context was composed over, with its manifest.

    Carried rather than summarised so that a caller who records a deliverable
    from preliminary context pins the same statement versions that were read
    (N20.1). A preliminary package that could not be pinned would be
    reproducible in appearance only.
    """
    warnings: tuple[str, ...]

    @property
    def is_preliminary(self) -> bool:
        """Whether anything here rests on something nobody has confirmed.

        Almost always true, and asserted rather than assumed: a context that
        stopped calling itself preliminary because a single statement was
        confirmed would be overstating what the project has settled.
        """

        return bool(self.proposed or self.assumed or self.material_unknowns)

    @property
    def has_content(self) -> bool:
        """Whether this says anything at all.

        False is a legitimate answer for a project nobody has told anything.
        The distinction that matters is between "nothing is known" and "nothing
        was produced because knowledge was judged insufficient" — the second is
        the gate this system does not have.
        """

        return bool(self.stated_verbatim or self.known or self.proposed or self.assumed)


class PreliminaryContextService:
    """Compose the useful preliminary view of a sparse project."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        memory: MemoryService | None = None,
        assembly: AssemblyService | None = None,
        assumptions: AssumptionService | None = None,
        clarifications: ClarificationService | None = None,
        readiness: ReadinessService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._memory = memory or MemoryService(session_factory)
        self._assembly = assembly or AssemblyService(session_factory)
        self._assumptions = assumptions or AssumptionService(session_factory)
        self._clarifications = clarifications or ClarificationService(session_factory)
        self._readiness = readiness or ReadinessService(session_factory)
        self._clock = clock

    def compose(
        self,
        project_id: ProjectId,
        purpose: AssemblyPurpose = AssemblyPurpose.DISCOVERY,
        mode: GenerationMode | None = None,
    ) -> PreliminaryContext:
        """Return the most useful context this project's current state supports.

        Unconfirmed candidates are **included**, always. That is the difference
        between this and `assemble`: an assembly defaults to what a person has
        confirmed, which is the right default for building against, and the
        wrong one for a project where nobody has confirmed anything yet.

        Nothing here refuses. There is no readiness at which this returns less
        than it has, and no state in which it declines — the empty answer for an
        empty project is an empty answer, not a refusal.
        """

        project = self._memory.get_project(project_id)
        if project is None:
            raise LookupError(f"unknown project: {project_id}")

        assembly = self._assembly.assemble(project_id, purpose, include_proposed=True, mode=mode)
        known = tuple(s for s in assembly.statements if s.inclusion_class == "confirmed")
        proposed = tuple(s for s in assembly.statements if s.inclusion_class != "confirmed")

        assumed = tuple(
            _assumed(assumption)
            for assumption in self._assumptions.list_for_project(project_id)
            if assumption.is_active
        )
        # Deferred questions included deliberately. They are held back from the
        # *asking* list so a person is not re-asked every call (N36); a context
        # document is not asking, it is disclosing, and an unknown omitted from
        # a disclosure reads as an unknown that does not exist.
        questions = self._clarifications.open_questions(project_id, include_deferred=True)
        material, deferrable = _split(questions)

        snapshot = self._readiness.latest(project_id) or self._readiness.calculate(project_id)

        return PreliminaryContext(
            project_id=str(project_id),
            project_name=project.name,
            generated_at=self._clock(),
            knowledge_revision=assembly.manifest.knowledge_revision,
            readiness_percentage=snapshot.percentage,
            stated_verbatim=self._stated(project_id),
            known=known,
            proposed=proposed,
            assumed=assumed,
            material_unknowns=material,
            deferrable_unknowns=deferrable,
            assembly=assembly,
            warnings=_warnings(known, proposed, assumed, material),
        )

    def _stated(self, project_id: ProjectId) -> tuple[StatedEntry, ...]:
        """Everything anyone said about this project, in the order it was said.

        Verbatim and unparaphrased. Answers count: "I don't know yet, but not
        for a prototype" is a statement about the project even though it decided
        nothing. Submitted observations count too — they are how a person's
        words reach KAE through an agent — and each entry says which it was, so
        relayed and first-hand never read as the same evidence.

        Review findings and proposals KAE generated are **not** included: those
        are the system's own output, and echoing them back as things that were
        said is how a document starts citing itself.
        """

        said: list[StatedEntry] = []
        for session in self._memory.sessions_for_project(project_id):
            for message in self._memory.messages_for_session(session.id):
                if message.message_type not in STATED_TYPES:
                    continue
                said.append(
                    StatedEntry(
                        message_id=str(message.id),
                        text=message.content,
                        actor_type=message.actor_type.value,
                        message_type=message.message_type.value,
                    )
                )
        return tuple(said)


def _assumed(assumption: Assumption) -> AssumedEntry:
    return AssumedEntry(
        assumption_id=str(assumption.id),
        subject=assumption.subject,
        assumed_value=assumption.assumed_value,
        reason=assumption.reason,
        origin=assumption.origin.value,
        consequence=assumption.consequence.value,
        state=assumption.state.value,
        reversible=assumption.reversible,
        material=assumption.material,
        accepted_by=assumption.accepted_by,
        disclosure=disclosure(assumption),
    )


def _split(
    questions: Sequence[OpenQuestion],
) -> tuple[tuple[UnknownEntry, ...], tuple[UnknownEntry, ...]]:
    """Separate the unknowns worth a person's attention now from the rest.

    Both halves are returned. Dropping the deferrable ones would make the
    context look more settled than the project is, and merging them would make
    every question look equally urgent — which is the same as making none of
    them urgent.
    """

    material: list[UnknownEntry] = []
    deferrable: list[UnknownEntry] = []
    for question in questions:
        entry = UnknownEntry(
            clarification_id=str(question.id),
            question=question.question,
            area_key=question.area_key,
            severity=question.severity,
            finding_kind=question.finding_kind,
            material=question.severity in MATERIAL_SEVERITIES,
            disposition=question.disposition.value,
        )
        (material if entry.material else deferrable).append(entry)
    return tuple(material), tuple(deferrable)


def _warnings(
    known: Sequence[AssembledStatement],
    proposed: Sequence[AssembledStatement],
    assumed: Sequence[AssumedEntry],
    material: Sequence[UnknownEntry],
) -> tuple[str, ...]:
    """Say what this context rests on, in the words a reader needs.

    Warnings, not blocks. Each one names something that is true about the
    output; none of them changes what the caller may do with it. That is the
    whole posture: generation may be incomplete, it may never be silent.
    """

    warnings: list[str] = []
    if not known:
        warnings.append(
            "Nothing here has been confirmed by a person. Everything below is "
            "proposed, assumed, or open."
        )
    if proposed:
        warnings.append(
            f"{len(proposed)} statement(s) were extracted from evidence and not "
            "confirmed. They are candidates, not project decisions."
        )
    material_assumptions = [entry for entry in assumed if entry.material]
    if material_assumptions:
        warnings.append(
            f"{len(material_assumptions)} assumption(s) would be expensive to "
            "reverse. Read their consequences before building on them."
        )
    if material:
        warnings.append(
            f"{len(material)} material question(s) are unanswered. This context "
            "was produced anyway; answering them would change what it says."
        )
    return tuple(warnings)
