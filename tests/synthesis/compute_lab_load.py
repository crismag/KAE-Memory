"""Load the AWS Compute Lab corpus the way repository ingestion did.

Two steps, because the live failure took two: extraction wrote every
observation as a proposed candidate, and a later review run assigned discovery
areas. The 692 unclassified items are the second step declining to guess on six
of the eight kinds, not the first step failing.

Both steps use the product's own code. Nothing here asserts the pathology; it
reproduces it and lets the tests measure what comes out.

**Which classifier is a parameter, because the two of them are the before and
after of `EPI-3b`.** The default is what the product runs offline today;
``test_compute_lab_baseline.py`` passes ``classify_offline`` by name, so the
kind-only rule that stranded 85% of the corpus stays reproducible instead of
becoming a paragraph about what used to happen.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.application.review_service import classify_offline_by_content as classify_by_content
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import KnowledgeItemId, ProjectId
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


Classifier = Callable[[Sequence[KnowledgeItem]], Sequence[tuple[KnowledgeItemId, str]]]


def _by_content(items: Sequence[KnowledgeItem]) -> tuple[tuple[KnowledgeItemId, str], ...]:
    return tuple((item_id, placement.area_key) for item_id, placement in classify_by_content(items))


def load_compute_lab_corpus(
    memory: MemoryService,
    readiness: ReadinessService,
    project_id: ProjectId,
    classifier: Classifier = _by_content,
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
    for item_id, area_key in classifier(stored):
        readiness.assign_area(project_id, item_id, area_key)

    return LoadedRepositoryCorpus(
        project_id=project_id,
        items=memory.retrieve_knowledge(project_id, lifecycle=None),
        observations=OBSERVATIONS,
        area_links=readiness.area_links(project_id),
    )
