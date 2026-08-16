"""Load the AWS Compute Lab corpus the way repository ingestion did.

Two steps, because the live failure took two: extraction wrote every
observation as a proposed candidate, and a later review run assigned discovery
areas with ``classify_offline`` — which assigns only the kinds exactly one area
accepts. The 692 unclassified items are the second step declining to guess on
the other six kinds, not the first step failing.

Both steps use the product's own code. Nothing here asserts the pathology; it
reproduces it and lets the tests measure what comes out.
"""

from __future__ import annotations

from dataclasses import dataclass

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.review_service import classify_offline
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem, KnowledgeSourceType
from kae_memory.domain.readiness import KnowledgeAreaLink
from tests.synthesis.compute_lab import OBSERVATIONS, ExtractedObservation


@dataclass(frozen=True, slots=True)
class LoadedRepositoryCorpus:
    """The fixture after extraction wrote it and offline review classified it."""

    project_id: ProjectId
    items: tuple[KnowledgeItem, ...]
    observations: tuple[ExtractedObservation, ...]
    area_links: tuple[KnowledgeAreaLink, ...]

    @property
    def unclassified(self) -> tuple[KnowledgeItem, ...]:
        """Items with no discovery area — the 692, at this fixture's scale."""

        linked = {str(link.knowledge_item_id) for link in self.area_links}
        return tuple(item for item in self.items if str(item.id) not in linked)


def load_compute_lab_corpus(
    memory: MemoryService, readiness: ReadinessService, project_id: ProjectId
) -> LoadedRepositoryCorpus:
    """Write every observation, confirm the two a person got to, classify offline.

    The two confirmations are not a synthesizer and not a pathology of their
    own. They are what the live project shows: six of 809 rows validated, which
    is a person starting a queue of hundreds and stopping.
    """

    run = memory.start_run(
        project_id,
        AgentRole.REQUIREMENTS,
        "aws-compute-lab-ingest",
        # The live case is a repository read, and ADR-0008 makes what its areas
        # may reach depend on saying so. A fixture that declared a paste would
        # reproduce the counts and not the epistemics.
        input_context={
            "document": "aws-compute-lab",
            "source_type": KnowledgeSourceType.REPOSITORY.value,
        },
    )
    items = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                kind=observation.kind.value,
                content=observation.content,
                source=observation.source,
            )
            for observation in OBSERVATIONS
        ],
        output_summary={"fixture": "aws-compute-lab", "items_written": len(OBSERVATIONS)},
    )
    by_content = {item.current_version.content: item for item in items}
    for observation in OBSERVATIONS:
        if observation.confirm:
            memory.confirm_knowledge(by_content[observation.content].id)

    readiness.install_template()
    stored = memory.retrieve_knowledge(project_id, lifecycle=None)
    for item_id, area_key in classify_offline(stored):
        readiness.assign_area(project_id, item_id, area_key)

    return LoadedRepositoryCorpus(
        project_id=project_id,
        items=memory.retrieve_knowledge(project_id, lifecycle=None),
        observations=OBSERVATIONS,
        area_links=readiness.area_links(project_id),
    )
