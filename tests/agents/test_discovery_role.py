"""The discovery extraction role (N46).

`requirements.v1` reads "a stakeholder's own words" and is deliberately
disciplined: *"Do not infer requirements the speaker did not express."* Correct
for a specification, and it reads an early description almost to nothing —
which is what the failed manual test found after the extraction edge existed.

Discovery is the role for the other job: turning a short, informal, incomplete
description into what a project now knows it is discussing. Same extraction
path, same provenance chain, same review model. Only the instruction differs,
and these tests hold that difference to being an instruction rather than a
licence.

**No test here asserts a particular candidate.** The prompt's output depends on
the extractor and the model, and asserting "produces an actor" would be
asserting the model's taste — it would fail on a better answer and pass on a
worse one that happened to match. What is asserted is the contract the prompt
must keep whatever it produces.
"""

from __future__ import annotations

import pytest

from kae_memory.agents.prompts import prompt_for
from kae_memory.domain.execution import AgentRole


@pytest.fixture
def discovery() -> str:
    """The prompt with its line wrapping removed.

    Prose assertions must not depend on where a line happens to break. The
    first version of this fixture returned the raw text and a phrase that
    wrapped mid-sentence failed a test about its meaning.
    """

    version, text = prompt_for(AgentRole.DISCOVERY)
    assert version == "discovery.v1"
    return " ".join(text.split())


class TestTheRoleExists:
    def test_discovery_is_authorised(self) -> None:
        assert AgentRole.DISCOVERY.value == "discovery"

    def test_it_has_its_own_prompt(self) -> None:
        """Sharing `requirements.v1` was the bug, not the design."""

        assert prompt_for(AgentRole.DISCOVERY)[0] != prompt_for(AgentRole.REQUIREMENTS)[0]

    def test_every_role_has_a_prompt(self) -> None:
        for role in AgentRole:
            version, text = prompt_for(role)
            assert version and text

    def test_the_worker_executes_it(self) -> None:
        """A role the worker cannot run is a queue that fills and never drains."""

        import inspect

        from kae_memory.worker import execution

        source = inspect.getsource(execution.AgentStepExecutor)

        assert "AgentRole.DISCOVERY" in source

    def test_it_shares_the_requirements_execution_path(self) -> None:
        """One path, two instructions.

        Duplicating the method to change one argument would give the two ways
        to drift apart — different provenance handling, different limits, and
        one of them quietly wrong.
        """

        from kae_memory.agents.roles import DiscoveryAgent, RequirementsAgent

        assert issubclass(DiscoveryAgent, RequirementsAgent)
        assert DiscoveryAgent.role is AgentRole.DISCOVERY


class TestThePromptKeepsTheEpistemicRules:
    """What separates useful interpretation from invention."""

    def test_it_requires_a_verbatim_quote(self, discovery: str) -> None:
        """Provenance is what proves KAE produced a candidate rather than a
        model asserting something about a project it never read."""

        assert "source_quote" in discovery
        assert "verbatim" in discovery

    def test_inference_must_be_recorded_as_an_assumption(self, discovery: str) -> None:
        assert "assumption" in discovery
        assert "what it would cost if you" in discovery.lower()

    def test_an_open_question_must_be_recorded_as_an_unknown(self, discovery: str) -> None:
        assert "unknown" in discovery

    def test_it_forbids_answering_its_own_unknowns(self, discovery: str) -> None:
        """The failure that would look like helpfulness."""

        assert "do not answer your own unknowns" in discovery.lower()

    def test_it_forbids_dressing_an_assumption_as_a_statement(self, discovery: str) -> None:
        assert "as though the speaker had stated it" in discovery.lower()

    def test_it_prefers_few_grounded_items_to_invented_coverage(self, discovery: str) -> None:
        assert "invented to look thorough" in discovery.lower()


class TestThePromptAllowsSparseInput:
    """The behaviour `requirements.v1` correctly refuses and this role needs."""

    def test_incompleteness_is_named_as_normal(self, discovery: str) -> None:
        assert "normal" in discovery.lower()
        assert "not a reason to return nothing" in discovery.lower()

    def test_it_reads_intent_rather_than_requiring_specification_grammar(
        self, discovery: str
    ) -> None:
        """A goal is a goal even when phrased as a wish.

        This is the whole difference from the requirements prompt, and the
        reason a rule for any particular phrasing would be the wrong fix: the
        criterion is ordinary product conversation, not one sentence shape.
        """

        assert "phrased as a wish" in discovery.lower()

    def test_it_names_no_particular_phrasing(self, discovery: str) -> None:
        """No pattern for "I want…" — that would pass the acceptance scenario
        while failing the requirement it stands for."""

        assert "i want" not in discovery.lower()
