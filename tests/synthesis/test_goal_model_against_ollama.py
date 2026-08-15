"""The claim CI cannot make: that a local model judges goal membership well.

`D-101` split two claims that are easy to blur. The corpus gate asserts the
**pipeline honours a judgement** — it uses a stub, and it runs everywhere. This
asserts the **judgement is any good**, which needs the model the deployment
actually runs (`ADR-0006`: `qwen2.5:14b` on Ollama) and therefore skips when it
is not there.

It exercises `agents.goal_judge`, the adapter the product uses. A test with its
own copy of the prompt would measure something nothing ships.

Kept as a test rather than a script so the measurement is repeatable and its
result is not a sentence somebody typed into a document once.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.goal_judge import OllamaGoalJudge
from kae_memory.application import MemoryService
from kae_memory.application.goal_synthesis_service import GoalSynthesisService
from kae_memory.application.synthesis_service import SynthesisService
from tests.synthesis.corpus import HOLD_MOON_TEXT, observations_for
from tests.synthesis.load import load_golden_corpus

pytestmark = pytest.mark.synthesis_gate

OLLAMA = "http://127.0.0.1:11434"
MODEL = "qwen2.5:14b"


def _ollama_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as response:
            names = {tag["name"] for tag in json.loads(response.read()).get("models", [])}
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError):
        return False
    return any(name.startswith(MODEL) for name in names)


@pytest.mark.skipif(not _ollama_ready(), reason=f"{MODEL} is not available on {OLLAMA}")
def test_the_local_model_keeps_the_garbage_out_and_the_goals_in(
    factory: sessionmaker[Session],
) -> None:
    """Measured, and recorded in the phase document rather than assumed.

    Two failure directions matter and they are not symmetric. Letting
    `hold-moon` through puts nonsense in the project model, which is the defect
    the corpus exists to catch. Dropping real goals quietly loses the project,
    which is worse — so the second assertion is the loose one and the first is
    exact.
    """

    memory = MemoryService(factory)
    project = memory.create_project("goal judge against ollama", key="goal-judge-live")
    load_golden_corpus(memory, project.id)

    report = GoalSynthesisService(factory, judge=OllamaGoalJudge()).synthesize(project.id)
    goals = [obj.statement for obj in SynthesisService(factory).list_objects(project.id, "goal")]

    assert report.judged
    assert not any(HOLD_MOON_TEXT.casefold() in goal.casefold() for goal in goals)

    local = {item.content for item in observations_for("conversation-local")}
    assert set(goals).isdisjoint(local)

    # The model must still be a model. A judge that refuses everything passes
    # the assertions above and has destroyed the project.
    assert len(goals) >= 8, f"only {len(goals)} goals survived judging: {goals}"
