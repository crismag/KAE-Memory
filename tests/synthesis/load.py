"""Load the golden corpus into a Memory project the way extraction does."""

from __future__ import annotations

from dataclasses import dataclass

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem
from tests.synthesis.corpus import OBSERVATIONS, ExtractedObservation


@dataclass(frozen=True, slots=True)
class LoadedCorpus:
    """The fixture after it has been written as proposed (and one confirmed) knowledge."""

    project_id: ProjectId
    items: tuple[KnowledgeItem, ...]
    observations: tuple[ExtractedObservation, ...]


def load_golden_corpus(memory: MemoryService, project_id: ProjectId) -> LoadedCorpus:
    """Write every extracted observation as a knowledge item of this project.

    One decision is confirmed afterwards: the corpus includes an area marked
    sufficient while related candidates remain proposed. That is the
    conflicting-state pathology, not a synthesizer.
    """

    run = memory.start_run(project_id, AgentRole.REQUIREMENTS, "golden-corpus-extract")
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
        output_summary={"fixture": "golden-corpus", "items_written": len(OBSERVATIONS)},
    )
    by_content = {item.current_version.content: item for item in items}
    for observation in OBSERVATIONS:
        if observation.confirm:
            memory.confirm_knowledge(by_content[observation.content].id)
    stored = memory.retrieve_knowledge(project_id, lifecycle=None)
    return LoadedCorpus(project_id, stored, OBSERVATIONS)
