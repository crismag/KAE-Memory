"""The requirements role's prompt, and the rule that a shipped one is frozen.

`REV-EMPTY` measured the loss on two real repositories: of 190 extraction runs,
**56 were abandoned**, and 47 of the 56 failed because `verify_quotes` refused a
citation. The classification is in `D-270`; the part this file exists for is that
the failures are overwhelmingly *quoting* failures rather than reading failures —
a span stitched from lines that are not adjacent, or a signature copied nearly
but not exactly — and `ollama_extraction`'s own docstring names the remedy:
*"a better prompt or a larger model — never a looser check."*

**No test here asserts a candidate the model produced.** The output depends on
the model, and asserting an extraction would be asserting its taste. What is
asserted is the instruction the prompt must carry, and — the guard that matters
more — that a version already recorded on a run is never edited afterwards.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from kae_memory.agents import prompts
from kae_memory.agents.prompts import prompt_for
from kae_memory.domain.execution import AgentRole


@pytest.fixture
def requirements() -> str:
    """The active requirements prompt, unwrapped.

    Prose assertions must not depend on where a line happens to break.
    """

    version, text = prompt_for(AgentRole.REQUIREMENTS)
    assert version == "requirements.v2"
    return " ".join(text.split())


class TestItTellsTheModelHowToQuote:
    """47 of 56 abandoned runs cited a span that is not in the text."""

    def test_it_requires_a_contiguous_span(self, requirements: str) -> None:
        """Twelve of the failures quoted lines that every one existed and that
        together occur nowhere — a list joined across the text between them."""

        assert "contiguous" in requirements
        assert "do not join two lines that are not next to each other" in requirements.lower()

    def test_it_forbids_eliding_the_middle(self, requirements: str) -> None:
        assert "ellipsis" in requirements.lower()

    def test_it_asks_for_the_shortest_span_that_carries_the_point(self, requirements: str) -> None:
        """The lever with the most reach: the near-misses are long quotes, one
        of them 69 words with 65 of them matching."""

        assert "shortest" in requirements.lower()

    def test_it_says_code_is_copied_rather_than_tidied(self, requirements: str) -> None:
        """Every near-verbatim failure on the repository corpus was a
        signature, a call or a path the model reformatted while copying."""

        assert "never tidied" in requirements.lower()

    def test_it_offers_leaving_the_item_out(self, requirements: str) -> None:
        """The batch is all-or-nothing, so one unquotable item is worth less
        than the nineteen it would discard."""

        assert "leave the item out" in requirements.lower()

    def test_it_says_the_whole_batch_is_lost(self, requirements: str) -> None:
        """The consequence, stated. A rule whose cost is invisible reads as a
        style preference."""

        assert "discards the whole batch" in requirements.lower()

    def test_it_states_the_one_difference_that_is_forgiven(self, requirements: str) -> None:
        """`_normalise` collapses whitespace before comparing, so a re-wrapped
        quote passes. Saying so is what makes the rest of the rule credible."""

        assert "line breaks and indentation" in requirements.lower()
        assert "need not match" in requirements.lower()


class TestItKeepsWhatV1Said:
    """A new version corrects one thing; it does not quietly drop the rest."""

    def test_inference_is_recorded_as_an_assumption(self, requirements: str) -> None:
        assert "record it as an assumption" in requirements.lower()

    def test_an_open_question_is_recorded_as_an_unknown(self, requirements: str) -> None:
        assert "record that as an unknown" in requirements.lower()

    def test_it_still_refuses_to_infer_unexpressed_requirements(self, requirements: str) -> None:
        assert "do not infer requirements the speaker did not express" in requirements.lower()

    def test_it_still_prefers_fewer_grounded_items(self, requirements: str) -> None:
        assert "prefer fewer, well-grounded items" in requirements.lower()


#: Every prompt version that has ever been selectable, by the SHA-256 of its
#: text. A prompt version is recorded on every run, so editing one rewrites what
#: historical knowledge claims to have been produced by (ADR-0006).
FROZEN_PROMPTS = {
    "REQUIREMENTS_V1": "9eb8aa4c41264f423b75097e6d1c741d4f3b5e48c1d726d53a37be191fe0e945",
    "REQUIREMENTS_V2": "5063e6b0f574cad7d0493d2053ca372485fabaf8447a50215676b1ee7607c1be",
    "ARCHITECTURE_V1": "4d874367d3f34e3dea83c482336fd311da10b9cd8a569a7e2ec1d19b60e99b66",
    "REVIEW_V1": "d67711f7813cd16da48fa34672b998fe1db057b2f9b2ea2e94d20c0a25919fae",
    "DISCOVERY_V1": "91bb9d4afdb06ca06655f7009bf2fb0ac7bf3d137928fab40a558e74f0f6ee9d",
}

_VERSIONED = re.compile(r"^[A-Z][A-Z_]*_V\d+$")


def _prompt_constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(prompts).items()
        if _VERSIONED.match(name) and isinstance(value, str)
    }


class TestAShippedPromptIsNeverEdited:
    """`ADR-0006`: corrections are new versions, never edits to an existing one.

    The rule was prose in a module docstring, and prose does not fail. This is
    the same rule as a failing test: a character changed in a prompt that has
    already produced knowledge fails here, naming the version whose provenance
    it would rewrite.
    """

    def test_every_versioned_prompt_is_registered(self) -> None:
        """A new version must be registered, which is where somebody notices
        they are adding one rather than editing one."""

        assert set(_prompt_constants()) == set(FROZEN_PROMPTS)

    @pytest.mark.parametrize("name", sorted(FROZEN_PROMPTS))
    def test_its_text_is_unchanged(self, name: str) -> None:
        digest = hashlib.sha256(_prompt_constants()[name].encode()).hexdigest()

        assert digest == FROZEN_PROMPTS[name], (
            f"{name} has been edited. A prompt version is recorded on every run "
            f"it produced, so editing it rewrites what that knowledge says it "
            f"came from. Add a new version instead (ADR-0006)."
        )


class TestTheVersionsAreDistinct:
    def test_v2_replaced_v1_for_the_role(self) -> None:
        assert prompt_for(AgentRole.REQUIREMENTS)[1] == prompts.REQUIREMENTS_V2

    def test_v1_is_still_present(self) -> None:
        """Kept, not deleted: 683 statements in the estate name it, and their
        provenance resolves to the text that produced them."""

        assert prompts.REQUIREMENTS_V1

    def test_the_other_roles_did_not_move(self) -> None:
        assert prompt_for(AgentRole.DISCOVERY)[0] == "discovery.v1"
        assert prompt_for(AgentRole.ARCHITECTURE)[0] == "architecture.v1"
        assert prompt_for(AgentRole.REVIEW)[0] == "review.v1"
