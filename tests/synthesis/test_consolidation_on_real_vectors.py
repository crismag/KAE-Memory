"""Consolidation, proved on the vectors a deployment actually produces.

`SYN-3b-VECTORS` was raised because clustering had never run end-to-end: the
corpus fixture writes rows whose chunks stay `pending`, so `embeddings_for`
returned nothing and every observation stood alone. The judge did the work and
the compaction never happened — which `D-102` recorded as a correction to the
`SYN-3b` claim.

`D-103` gave synthesis a statement-space measurement of its own. This is the
test that shows it works, and it needs the real embedding model, so it skips
without one. Everything else about these synthesizers is asserted with stubs;
**this one claim cannot be**, because what is being tested is whether real
sentences land near each other.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.ollama import EMBEDDING_MODEL, OllamaEmbeddingAdapter
from kae_memory.application import MemoryService
from kae_memory.application.reconciliation_service import ReconciliationService
from kae_memory.application.unknown_synthesis_service import UnknownSynthesisService
from tests.synthesis.corpus import READINESS_CRITERIA, WHAT_ARE_WE_BUILDING, observations_for
from tests.synthesis.load import load_golden_corpus

pytestmark = pytest.mark.synthesis_gate

OLLAMA = os.environ.get("KAE_OLLAMA_URL", "http://127.0.0.1:11434")


def _embedder_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as response:
            names = {tag["name"] for tag in json.loads(response.read()).get("models", [])}
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError):
        return False
    return any(name.startswith(EMBEDDING_MODEL) for name in names)


@pytest.mark.skipif(not _embedder_ready(), reason=f"{EMBEDDING_MODEL} is not available on {OLLAMA}")
def test_paraphrased_questions_consolidate_into_themes(
    factory: sessionmaker[Session],
) -> None:
    """The claim `SYN-3b` made and could not support.

    The corpus asks *what does development-ready mean* eight ways. With no
    vectors those are eight themes; with statement-space vectors they are
    fewer, and the difference is the whole point of the package — evidence
    volume rising while human workload does not.

    Asserted as a reduction rather than an exact count. `02-GOALS-SYNTHESIS.md`
    is explicit that cardinality is not the acceptance criterion, and pinning a
    number here would make a better clusterer fail.
    """

    memory = MemoryService(factory)
    project = memory.create_project("consolidation on real vectors", key="real-vectors")
    load_golden_corpus(memory, project.id)
    ReconciliationService(factory).reconcile(project.id)

    unembedded = UnknownSynthesisService(factory).synthesize(project.id)
    embedded = UnknownSynthesisService(factory, embedder=OllamaEmbeddingAdapter()).synthesize(
        project.id
    )

    assert not unembedded.clustered
    assert embedded.clustered
    assert embedded.themes < unembedded.themes, (
        f"{embedded.themes} themes with vectors against {unembedded.themes} without — "
        "clustering ran and consolidated nothing"
    )

    # And it is the paraphrases that merged, not an arbitrary reduction.
    #
    # **Not down to one, and that is correct.** Eight wordings reach a person as
    # two, and reading them shows why: *when is a plan development-ready* is a
    # definition, *who decides that planning is finished* is an authority — the
    # same distinction doc 03 draws between a subject and its accountable role.
    # An earlier version of this test demanded one theme, and the honest fix was
    # the assertion rather than a lower radius. `D-102`: not a threshold to
    # lower.
    readiness = {item.content for item in observations_for(READINESS_CRITERIA)}
    raised = {question for _, question in embedded.attention}
    assert len(raised & readiness) * 2 < len(readiness), (
        f"{len(raised & readiness)} of {len(readiness)} readiness wordings reached a "
        "person; the paraphrases are one theme even where the questions are two"
    )


@pytest.mark.skipif(not _embedder_ready(), reason=f"{EMBEDDING_MODEL} is not available on {OLLAMA}")
def test_consolidation_does_not_revive_an_answered_question(
    factory: sessionmaker[Session],
) -> None:
    """Clustering must not undo reconciliation.

    A resolved unknown that merged into a live theme would come back as a
    question the project already answered — the exact defect doc 09 names,
    reintroduced by the mechanism meant to prevent it.
    """

    memory = MemoryService(factory)
    project = memory.create_project("resolved stays resolved", key="resolved-stays")
    load_golden_corpus(memory, project.id)
    ReconciliationService(factory).reconcile(project.id)

    report = UnknownSynthesisService(factory, embedder=OllamaEmbeddingAdapter()).synthesize(
        project.id
    )

    stale = {item.content for item in observations_for(WHAT_ARE_WE_BUILDING)}
    raised = {question for _, question in report.attention}

    assert report.resolved >= len(stale)
    assert stale.isdisjoint(raised)
