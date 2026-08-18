"""A classification is current only while the reviewer that made it is.

`REV-STALE`, `D-271`. Readiness reports `is_stale` against the knowledge
revision, so a deployment that swaps `KAE_REVIEW=deterministic` for `ollama`
changes what a classification *means* while changing no knowledge at all — and
every project already classified stays on the fixture's answer for ever, because
classifying again is refused on unchanged knowledge. Found by hitting it:
`D-270` had to go round the product to re-classify a live project.
"""

import pytest

from kae_memory import runtime_profile
from kae_memory.agents.review import (
    REVIEWER_CLAIMS,
    UNKNOWN_REVIEWER_CLAIM,
    configured_reviewer_claim,
    judges,
)
from kae_memory.api.schemas import ClassificationResponse
from kae_memory.application.readiness_service import ClassificationReport
from kae_memory.worker.execution import default_reviewer


class TestTheTableIsTiedToTheAdapters:
    """`REVIEWER_CLAIMS` restates `judges` and must not be free to drift.

    `AUD-039` is the whole reason the word exists: a fixture satisfies
    `ReviewPort` like anything else, so `reviewed_by_model` was reported about
    recorded payloads. A literal table describing adapters that had changed
    their minds would rebuild that defect one layer further out.
    """

    @pytest.mark.parametrize("setting", ["ollama", "deterministic"])
    def test_each_named_adapter_claims_what_the_table_says(
        self, setting: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(runtime_profile.VARIABLE, runtime_profile.LOCAL)
        monkeypatch.setenv("KAE_REVIEW", setting)
        monkeypatch.setenv("KAE_OLLAMA_URL", "http://127.0.0.1:11434")

        reviewer = default_reviewer()

        assert reviewer is not None
        expected = "model" if judges(reviewer) else "fixture"
        assert REVIEWER_CLAIMS[setting] == expected

    def test_bedrock_claims_a_model_without_a_region_to_build_one(self) -> None:
        """Asked of the class, because constructing it needs AWS.

        `judges` reads an attribute, so the class answers the same question the
        instance does — which is what makes this table checkable at all on a
        machine with no credentials.
        """

        from kae_memory.agents.bedrock import BedrockReviewAdapter

        assert judges(BedrockReviewAdapter) is True
        assert REVIEWER_CLAIMS["bedrock"] == "model"

    @pytest.mark.parametrize("setting", ["off", "none", ""])
    def test_a_switched_off_reviewer_is_none_and_not_a_fixture(
        self, setting: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A reviewer nobody configured is a different fact from one that does
        not judge, and `default_reviewer` agrees by returning nothing."""

        monkeypatch.setenv(runtime_profile.VARIABLE, runtime_profile.PRODUCTION)
        monkeypatch.setenv("KAE_REVIEW", setting)

        assert default_reviewer() is None
        assert REVIEWER_CLAIMS[setting] == "none"


class TestWhatTheDeploymentWouldClaimNow:
    def test_the_default_is_the_fixture_because_default_reviewer_says_so(self) -> None:
        assert configured_reviewer_claim({}) == "fixture"

    def test_a_setting_this_build_does_not_recognise_is_unknown(self) -> None:
        """Not an exception. `default_reviewer` refuses `bedrok` where choosing
        the wrong reviewer costs something; a readiness read is not that place,
        and 500ing the number because a setting is misspelt would hide the
        project behind the typo."""

        assert configured_reviewer_claim({"KAE_REVIEW": "bedrok"}) == UNKNOWN_REVIEWER_CLAIM

    def test_the_setting_is_read_the_way_default_reviewer_reads_it(self) -> None:
        assert configured_reviewer_claim({"KAE_REVIEW": "  Ollama  "}) == "model"


class TestTheRecordedClaim:
    """Claims are compared, not adapter names, because a claim is what is
    stored. `bedrock` and `ollama` both write `reviewed_by_model`."""

    @pytest.mark.parametrize(
        ("engine", "expected"),
        [
            ("reviewed_by_model", "model"),
            ("partially_reviewed_by_model", "model"),
            ("reviewed_by_fixture", "fixture"),
            ("partially_reviewed_by_fixture", "fixture"),
            ("offline_by_content", "none"),
            ("offline_by_content_after_reviewer_error", "none"),
            ("offline_by_kind", "none"),
            (None, None),
        ],
    )
    def test_every_engine_word_maps(self, engine: str | None, expected: str | None) -> None:
        assert ClassificationReport(engine=engine, reviewed_at=None).claim == expected


class TestTheSecondStaleness:
    def test_a_fixture_classification_under_a_model_reviewer_is_not_current(self) -> None:
        response = ClassificationResponse.of(
            ClassificationReport(engine="reviewed_by_fixture", reviewed_at=None),
            current_reviewer="model",
        )

        assert response.engine_is_current is False
        assert response.current_reviewer == "model"
        assert "no longer uses" in response.note

    def test_a_model_classification_under_a_model_reviewer_is_current(self) -> None:
        response = ClassificationResponse.of(
            ClassificationReport(engine="reviewed_by_model", reviewed_at=None),
            current_reviewer="model",
        )

        assert response.engine_is_current is True
        assert "no longer uses" not in response.note

    def test_a_run_whose_reviewer_failed_entirely_is_not_current(self) -> None:
        """The state this also unfreezes. Every batch reached the configured
        reviewer and failed, the offline fallback placed what it could, and
        placing it bumped the revision — so the pass could never be run again on
        the knowledge it failed over."""

        response = ClassificationResponse.of(
            ClassificationReport(
                engine="offline_by_content_after_reviewer_error", reviewed_at=None
            ),
            current_reviewer="model",
        )

        assert response.engine_is_current is False

    def test_a_partial_pass_still_counts_as_current(self) -> None:
        """Deliberately left alone. Some batches were judged by the reviewer
        this deployment still uses, and re-running for the rest is the retry
        question rather than the reviewer question."""

        response = ClassificationResponse.of(
            ClassificationReport(engine="partially_reviewed_by_model", reviewed_at=None),
            current_reviewer="model",
        )

        assert response.engine_is_current is True

    def test_nothing_classified_is_unknown_rather_than_stale(self) -> None:
        response = ClassificationResponse.of(
            ClassificationReport(engine=None, reviewed_at=None), current_reviewer="model"
        )

        assert response.engine_is_current is None

    def test_an_unrecognised_setting_leaves_the_question_unanswered(self) -> None:
        """Unknown is not stale. A typo must not make every project in the
        deployment permanently re-reviewable, which is a cost."""

        response = ClassificationResponse.of(
            ClassificationReport(engine="reviewed_by_model", reviewed_at=None),
            current_reviewer=UNKNOWN_REVIEWER_CLAIM,
        )

        assert response.engine_is_current is None

    def test_the_environment_answers_when_the_caller_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The route passes nothing, so this is the path the product uses."""

        monkeypatch.setenv("KAE_REVIEW", "ollama")

        response = ClassificationResponse.of(
            ClassificationReport(engine="reviewed_by_fixture", reviewed_at=None)
        )

        assert response.current_reviewer == "model"
        assert response.engine_is_current is False
