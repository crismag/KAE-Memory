"""Load the AWS Compute Lab corpus, and record what the kind-only rule did to it.

Doc 17's failure was a screenshot, and a screenshot cannot regress. Running the
product's own write path and ``classify_offline`` over a fixture in the live
project's shape turns *803 candidates await review, 692 items need
classification* into something a test suite can watch stop being true.

**These pin the classifier by name, and that is now load-bearing.** `EPI-3b`
made content classification the offline default, so the corpus no longer strands
85% of itself unless the kind-only rule is asked for explicitly — which is what
these ask for. They characterise the state the gates in
`test_compute_lab_contract.py` describe the exit from; they are not a claim
about what the product does now.

They also guard the fixture from the other direction. A later phase that
satisfied those gates by making the corpus smaller or tamer would break these
first.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, SynthesisService
from kae_memory.application.review_service import classify_offline
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, Project
from kae_memory.domain.readiness import AreaState
from tests.synthesis.compute_lab import (
    HEADLINE_COUNTS,
    LIVE_ITEM_COUNT,
    LIVE_UNCLASSIFIED_COUNT,
    OBSERVATIONS,
)
from tests.synthesis.compute_lab_load import load_compute_lab_corpus


@pytest.fixture
def project(factory: sessionmaker[Session]) -> tuple[MemoryService, ReadinessService, Project]:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    return memory, readiness, memory.create_project("AWS Compute Lab", key="compute-lab-baseline")


class TestTheRepositoryCorpusLoadsIntact:
    def test_every_extracted_row_becomes_a_knowledge_item(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)

        assert len(loaded.items) == len(OBSERVATIONS)

    def test_headline_kind_counts_survive_the_write(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        """Near-duplicates are the pathology, so none of them may collapse."""

        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)
        stored: dict[str, int] = dict.fromkeys(HEADLINE_COUNTS, 0)
        for item in loaded.items:
            stored[item.kind] += 1

        assert stored == dict(HEADLINE_COUNTS)

    def test_every_stored_item_keeps_its_repository_provenance(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)

        assert all(
            item.current_version.provenance.source.startswith("repository:aws-compute-lab:")
            for item in loaded.items
        )


class TestTodayConsumingARepositoryProducesABacklog:
    def test_the_review_queue_is_the_proposed_row_count(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        """809 rows in, 803 awaiting review. That is the defect `EPI-6` names."""

        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)
        proposed = [item for item in loaded.items if item.lifecycle is LifecycleState.PROPOSED]
        validated = [item for item in loaded.items if item.lifecycle is LifecycleState.VALIDATED]

        assert len(validated) == 2
        assert len(proposed) == len(OBSERVATIONS) - 2

    def test_most_of_the_corpus_is_unclassified(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        """The 692, reproduced through `classify_offline` rather than asserted.

        `EPI-3`: this is KAE's processing backlog presented as the user's
        filing job."""

        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)

        share = len(loaded.unclassified) / len(loaded.items)
        assert abs(share - LIVE_UNCLASSIFIED_COUNT / LIVE_ITEM_COUNT) < 0.02

    def test_only_two_discovery_areas_receive_anything(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)

        assert {link.area_key for link in loaded.area_links} == {
            "users_and_stakeholders",
            "constraints_and_assumptions",
        }

    def test_the_open_questions_are_all_still_open(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        """103 questions, none of them reconciled against the evidence that
        answers them. `EPI-4`."""

        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)
        unknowns = [item for item in loaded.items if item.kind == KnowledgeKind.UNKNOWN.value]

        assert len(unknowns) == HEADLINE_COUNTS[KnowledgeKind.UNKNOWN.value]
        assert all(item.lifecycle is LifecycleState.PROPOSED for item in unknowns)

    def test_readiness_reports_areas_absent_after_a_full_ingest(
        self, project: tuple[MemoryService, ReadinessService, Project]
    ) -> None:
        """Doc 17's *absurd outcome*: extensive evidence consumed, areas still
        reported as having nothing. `EPI-5`."""

        memory, readiness, proj = project
        load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)
        snapshot = readiness.calculate(proj.id)

        missing = [area for area in snapshot.areas if area.state is AreaState.MISSING]
        assert len(missing) >= 7
        assert snapshot.implementation_eligible is False


class TestTheSynthesizedLayerStartsEmpty:
    def test_consuming_a_repository_creates_no_model_and_no_attention(
        self,
        project: tuple[MemoryService, ReadinessService, Project],
        factory: sessionmaker[Session],
    ) -> None:
        """Evidence volume is not model volume. Today it is not model volume
        because there is no model — every one of the 180 rows is the model."""

        memory, readiness, proj = project
        loaded = load_compute_lab_corpus(memory, readiness, proj.id, classify_offline)
        synthesis = SynthesisService(factory)

        assert len(loaded.items) == len(OBSERVATIONS)
        assert synthesis.list_objects(proj.id) == ()
        assert synthesis.list_attention(proj.id) == ()
