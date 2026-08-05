"""What a project can do right now (N34).

Composes facts that already exist — readiness, deliverables, publication
targets when they arrive — into an answer to "what can I do", rather than
"how complete are you".

The rule this service exists to hold: **knowledge quality never appears as a
block.** It appears as a warning, as an assumption to accept, or as something
that would improve the output — and the operation stays available. Only
authorisation, integrity, provider availability, an unmade choice, or an
unsupported feature produce a state a caller cannot proceed from.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from kae_memory.domain.acquisition import (
    AcquisitionState,
    CapabilityReadiness,
    CapabilityState,
    ReadinessReport,
    quality_never_blocks,
)
from kae_memory.domain.identifiers import ProjectId

from .deliverable_service import DeliverableService
from .readiness_service import ReadinessService

SPARSE_KNOWLEDGE_THRESHOLD = 40
"""Below this, output is qualified more heavily. **Not a gate.**

Named so the number has one home and one meaning. It changes wording and
warnings; it never changes what a caller is allowed to do, and a test asserts
that a project below it retains every generation capability.
"""


class CapabilityReadinessService:
    """Report readiness per capability rather than as a verdict."""

    def __init__(
        self,
        session_factory: sessionmaker[DbSession],
        readiness: ReadinessService | None = None,
        deliverables: DeliverableService | None = None,
    ) -> None:
        self._readiness = readiness or ReadinessService(session_factory)
        self._deliverables = deliverables or DeliverableService(session_factory)

    def report(self, project_id: ProjectId) -> ReadinessReport:
        """Return what this project can do now, and what would improve it."""

        snapshot = self._readiness.latest(project_id) or self._readiness.calculate(project_id)
        percentage = snapshot.percentage
        sparse = percentage < SPARSE_KNOWLEDGE_THRESHOLD

        capabilities = [
            CapabilityReadiness(
                capability="acquisition.continue",
                state=CapabilityState.AVAILABLE,
                improves_with=("more sources", "answered questions", "resolved contradictions"),
            ),
            self._assemble(percentage, sparse),
            CapabilityReadiness(
                capability="deliverable.record",
                state=CapabilityState.AVAILABLE,
                improves_with=("confirmed knowledge in the areas this purpose reads",),
            ),
            *self._render(project_id),
            *self._publish(),
        ]

        report = ReadinessReport(
            project_id=str(project_id),
            acquisition_state=self._acquisition_state(snapshot.percentage),
            percentage=percentage,
            capabilities=tuple(capabilities),
        )
        # Checked here rather than trusted. The invariant is easy to break by
        # accident and impossible to notice from a passing test suite that does
        # not look for it.
        quality_never_blocks(report)
        return report

    def _assemble(self, percentage: int, sparse: bool) -> CapabilityReadiness:
        if not sparse:
            return CapabilityReadiness(
                capability="knowledge.assemble",
                state=CapabilityState.AVAILABLE,
            )
        return CapabilityReadiness(
            capability="knowledge.assemble",
            state=CapabilityState.AVAILABLE_WITH_WARNINGS,
            reason=(
                f"readiness is {percentage}%, so the assembled context will be thin "
                f"and will carry more open questions than confirmed statements"
            ),
            next_action="generate now and read the disclosed gaps, or answer the important questions first",
            improves_with=("answers to the questions marked important",),
        )

    def _render(self, project_id: ProjectId) -> tuple[CapabilityReadiness, ...]:
        """Rendering is blocked only where reproduction cannot be proven."""

        ineligible = [
            deliverable
            for deliverable in self._deliverables.list_for_project(project_id)
            if not deliverable.publication_eligible
        ]
        if not ineligible:
            return (
                CapabilityReadiness(
                    capability="deliverable.render",
                    state=CapabilityState.AVAILABLE,
                ),
            )
        return (
            CapabilityReadiness(
                capability="deliverable.render",
                state=CapabilityState.AVAILABLE,
            ),
            CapabilityReadiness(
                capability="deliverable.republish_historical",
                state=CapabilityState.BLOCKED_BY_INTEGRITY,
                reason=(
                    f"{len(ineligible)} recorded deliverable(s) predate pinned render "
                    f"inputs, so re-rendering them cannot be proven identical to what "
                    f"was originally produced"
                ),
                next_action=(
                    "record a new deliverable from current knowledge; the historical "
                    "ones stay readable and are not republished under their original identity"
                ),
            ),
        )

    def _publish(self) -> tuple[CapabilityReadiness, ...]:
        """Publication targets do not exist yet (N27), and that is not a failure.

        Reported as unsupported rather than blocked: the difference is whether
        the caller can do something about it, and here they cannot until the
        registry ships.
        """

        return (
            CapabilityReadiness(
                capability="deliverable.publish",
                state=CapabilityState.UNSUPPORTED,
                reason="no publication target registry exists in this version (N27)",
                next_action=(
                    "record and render the deliverable; publication becomes available "
                    "once a target can be registered and authorised"
                ),
            ),
        )

    def _acquisition_state(self, percentage: int) -> AcquisitionState:
        if percentage == 0:
            return AcquisitionState.NOT_STARTED
        if percentage < SPARSE_KNOWLEDGE_THRESHOLD:
            return AcquisitionState.AWAITING_IMPORTANT
        return AcquisitionState.AWAITING_OPTIONAL
