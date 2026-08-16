"""Both corpora read through the epistemic rule, which is doc 17's complaint measured.

`EPI-1`, `D-134`. The rule itself is `tests/domain/test_epistemics.py`. These
are the readings, taken through the provenance the acquisition path actually
wrote rather than through a fixture field, because the whole claim of `EPI-5a`
is that only the path that acquired the text knows what kind of source it was.

**No `strict=True` gate in `test_compute_lab_contract.py` moves here.** Those
gates are shared with `EPI-6` and cannot pass until repository ingest routes
through reconciliation; a vocabulary does not reconcile anything.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService
from kae_memory.domain.epistemics import EpistemicClass, EpistemicSubject, classify
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, KnowledgeSourceType
from kae_memory.persistence.workspace_repositories import ProvenanceLinkRepository
from tests.synthesis.compute_lab_load import load_compute_lab_corpus
from tests.synthesis.load import load_golden_corpus


def _reading(
    factory: sessionmaker[Session], project_id: ProjectId, items: tuple[KnowledgeItem, ...]
) -> Counter[EpistemicClass]:
    with factory() as session:
        source_types = ProvenanceLinkRepository(session).source_types_by_item(project_id)
    return Counter(
        classify(
            EpistemicSubject(
                KnowledgeKind(item.kind),
                LifecycleState(item.lifecycle),
                frozenset(
                    KnowledgeSourceType(one) for one in source_types.get(str(item.id), frozenset())
                ),
            )
        )
        for item in items
    )


class TestARepositoryIngestIsAlmostEntirelyObserved:
    def test_the_compute_lab_reading_is_pinned(self, factory: sessionmaker[Session]) -> None:
        """180 rows, and **not one of them is undetermined or derived**. Doc 17's
        opening example is this corpus: the repository is sufficient evidence
        that the file declares what it declares, and the product asked a person
        about all 180 anyway."""

        memory = MemoryService(factory)
        readiness = ReadinessService(factory)
        project = memory.create_project("AWS Compute Lab", key="compute-lab-epistemics")
        corpus = load_compute_lab_corpus(memory, readiness, project.id)

        reading = _reading(factory, project.id, corpus.items)

        assert sum(reading.values()) == 180
        assert reading[EpistemicClass.OBSERVED] == 166
        assert reading[EpistemicClass.ASSUMED] == 12
        assert reading[EpistemicClass.ACCEPTED] == 2
        assert reading[EpistemicClass.DERIVED] == 0
        assert reading[EpistemicClass.UNDETERMINED] == 0
        assert reading[EpistemicClass.PROPOSED] == 0

    def test_the_two_accepted_rows_are_the_two_a_person_reached(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Six of 809 on the live project, two of 180 here: a person starting a
        queue of hundreds and stopping. Acceptance is what a person did, and it
        is the only class in this corpus that a person produced."""

        memory = MemoryService(factory)
        readiness = ReadinessService(factory)
        project = memory.create_project("AWS Compute Lab", key="compute-lab-accepted")
        corpus = load_compute_lab_corpus(memory, readiness, project.id)

        reading = _reading(factory, project.id, corpus.items)
        validated = [one for one in corpus.items if one.lifecycle is LifecycleState.VALIDATED]

        assert reading[EpistemicClass.ACCEPTED] == len(validated)


class TestAConversationCorpusReadsTheSameWayForADifferentReason:
    def test_the_golden_corpus_reading_is_pinned(self, factory: sessionmaker[Session]) -> None:
        """175 rows of a person's own statements. Observed here means *the user
        wrote this sentence*, which doc 17 lists as observed alongside a
        configuration file — the class says the evidence exists, never that it
        is current project intent."""

        memory = MemoryService(factory)
        project = memory.create_project("KAE synthesis corpus", key="golden-epistemics")
        corpus = load_golden_corpus(memory, project.id)

        reading = _reading(factory, project.id, corpus.items)

        assert sum(reading.values()) == 175
        assert reading[EpistemicClass.OBSERVED] == 161
        assert reading[EpistemicClass.ASSUMED] == 13
        assert reading[EpistemicClass.ACCEPTED] == 1
        assert reading[EpistemicClass.UNDETERMINED] == 0

    def test_neither_corpus_reaches_derived_because_nothing_infers_yet(
        self, factory: sessionmaker[Session]
    ) -> None:
        """`KAE_INFERENCE` is written only by the architecture role, which
        neither fixture runs. The absence is the honest reading and not a gap in
        the rule — a synthesizer that wrote inferences would move it."""

        memory = MemoryService(factory)
        project = memory.create_project("KAE synthesis corpus", key="golden-derived")
        corpus = load_golden_corpus(memory, project.id)

        assert _reading(factory, project.id, corpus.items)[EpistemicClass.DERIVED] == 0
