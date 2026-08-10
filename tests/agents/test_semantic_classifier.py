"""Classification by meaning, and what it refuses to guess (N43).

The deterministic classifier files anything it has no rule for as
`unclassified`, which is honest and is also most sentences people write. This
adapter reads meaning instead — and reading meaning is exactly where a
classifier acquires the ability to be confidently wrong, so most of what is
asserted here is what it declines to do.

No model runs in these tests. A fake client returns the payloads a model would,
including the malformed ones, because the failure modes worth testing are the
ones that only appear when a provider misbehaves — and those never appear in a
run that costs money and passes.
"""

from __future__ import annotations

from typing import Any

import pytest

from kae_memory.agents.observation_classifier import DeterministicObservationClassifier
from kae_memory.agents.provider import (
    CLASSIFIER_DETERMINISTIC,
    ProviderConfigurationError,
    build_classifier,
    classifier_name,
    classifies_by_meaning,
    describe,
)
from kae_memory.agents.semantic_classifier import (
    BedrockObservationClassifier,
    parse_assignments,
    split_sentences,
)
from kae_memory.domain.observation import ObservationClass, RetentionTier

SENTENCE = "I want an inbox where I can dump thoughts."
TWO = "I want an inbox where I can dump thoughts. Tests passed on M8."


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [_Block(text)]
        self.stop_reason = stop_reason
        self.model = "fake"


class _Messages:
    """Returns each outcome in turn, then repeats the last one.

    A sequence rather than a single value so a test can say "fails, then
    works" — which is the case that proves the degraded flag clears.
    """

    def __init__(self, *outcomes: Any) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self._outcomes[min(len(self.calls) - 1, len(self._outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Client:
    """The smallest thing shaped like the Anthropic client."""

    def __init__(self, *outcomes: Any) -> None:
        self.messages = _Messages(*outcomes)

    def with_options(self, **_: Any) -> _Client:
        return self


def _classifier(outcome: Any) -> BedrockObservationClassifier:
    return _built(outcome)[0]


def _built(outcome: Any) -> tuple[BedrockObservationClassifier, _Client]:
    """The classifier and the fake it will call, so a test can read both."""

    client = _Client(outcome)
    return BedrockObservationClassifier(region="us-east-1", client=client), client


def _answer(*entries: dict[str, Any]) -> _Response:
    import json

    return _Response(json.dumps({"spans": list(entries)}))


class TestItClassifiesByMeaning:
    def test_a_casual_requirement_is_a_requirement(self) -> None:
        """The whole point. "I want somewhere to dump thoughts" is a
        requirement written the way people actually write them, and no regular
        expression is going to find it."""

        classifier = _classifier(
            _answer({"index": 0, "classification": "requirement", "confidence": 0.8})
        )

        spans = classifier.classify(SENTENCE)

        assert [span.classification for span in spans] == [ObservationClass.REQUIREMENT]
        assert spans[0].tier is RetentionTier.DURABLE

    def test_it_says_it_is_semantic(self) -> None:
        """`semantic` is what a caller reads to decide whether `unclassified`
        means "there was nothing there" or "this classifier does not know that
        phrasing"."""

        assert _classifier(_answer()).semantic is True

    def test_each_sentence_gets_its_own_class(self) -> None:
        """One submission producing differently-routed spans is the normal
        case, not an edge case."""

        classifier = _classifier(
            _answer(
                {"index": 0, "classification": "requirement", "confidence": 0.8},
                {"index": 1, "classification": "test_result", "confidence": 0.9},
            )
        )

        spans = classifier.classify(TWO)

        assert [span.tier for span in spans] == [
            RetentionTier.DURABLE,
            RetentionTier.OPERATIONAL,
        ]

    def test_empty_text_asks_nothing(self) -> None:
        """A model call for no sentences is money for nothing."""

        classifier, client = _built(_answer())

        assert classifier.classify("   ") == ()
        assert client.messages.calls == []


class TestOffsetsAreNeverModelDerived:
    def test_the_span_points_at_the_real_text(self) -> None:
        """A span that does not line up sends a reviewer to the wrong sentence,
        which is the one failure a provenance system cannot tolerate."""

        classifier = _classifier(
            _answer({"index": 0, "classification": "requirement", "confidence": 0.8})
        )

        span = classifier.classify(TWO)[0].span

        assert TWO[span.start : span.end] == "I want an inbox where I can dump thoughts."

    def test_the_model_is_shown_numbers_not_offsets(self) -> None:
        """It cannot return an offset it was never asked for."""

        classifier, client = _built(
            _answer({"index": 0, "classification": "requirement", "confidence": 0.8})
        )

        classifier.classify(TWO)

        sent = client.messages.calls[0]["messages"][0]["content"]
        assert sent.startswith("0. I want an inbox")
        assert "1. Tests passed on M8." in sent

    def test_the_split_matches_the_deterministic_one(self) -> None:
        """Both adapters must point at the same spans, or a project that
        switched classifiers would find its old spans subtly misaligned."""

        semantic = [span for _, span in split_sentences(TWO)]
        rule_based = [span.span for span in DeterministicObservationClassifier().classify(TWO)]

        assert semantic == rule_based

    def test_the_original_text_is_never_rewritten(self) -> None:
        classifier = _classifier(
            _answer({"index": 0, "classification": "requirement", "confidence": 0.8})
        )

        span = classifier.classify(SENTENCE)[0]

        assert span.normalized_text == SENTENCE


class TestItRefusesToGuess:
    def test_an_unknown_class_becomes_unclassified(self) -> None:
        """The model read something this version cannot route. The nearest
        match would file it confidently in the wrong tier."""

        assignments = parse_assignments(
            {"spans": [{"index": 0, "classification": "vibe", "confidence": 0.9}]}, 1
        )

        assert assignments[0][0] is ObservationClass.UNCLASSIFIED
        assert assignments[0][1] == 0.0

    def test_an_index_naming_no_sentence_is_dropped(self) -> None:
        """It would otherwise become a class attached to nothing, or worse, to
        whatever happened to be at that position."""

        assert parse_assignments({"spans": [{"index": 7, "classification": "task"}]}, 2) == {}

    def test_a_confidence_outside_the_range_is_zeroed(self) -> None:
        """Zero routes it to a person, which is what an impossible confidence
        deserves."""

        assignments = parse_assignments(
            {"spans": [{"index": 0, "classification": "task", "confidence": 4.2}]}, 1
        )

        assert assignments[0][1] == 0.0

    def test_a_skipped_sentence_becomes_unclassified(self) -> None:
        """Not dropped. A sentence nothing read still exists in the observation
        and still needs a route."""

        classifier = _classifier(
            _answer({"index": 0, "classification": "requirement", "confidence": 0.8})
        )

        spans = classifier.classify(TWO)

        assert len(spans) == 2
        assert spans[1].classification is ObservationClass.UNCLASSIFIED

    def test_low_confidence_still_reaches_a_person(self) -> None:
        """The routing rule is the domain's, and reading by meaning does not
        earn an exemption from it."""

        classifier = _classifier(
            _answer({"index": 0, "classification": "requirement", "confidence": 0.2})
        )

        assert classifier.classify(SENTENCE)[0].review_required is True


class TestItDegradesRatherThanBlocks:
    def test_a_provider_failure_falls_back_to_rules(self) -> None:
        """Classification is a convenience over evidence already recorded.
        Losing an observation because a model was unreachable would invert
        what matters."""

        classifier = _classifier(RuntimeError("bedrock is unreachable"))

        spans = classifier.classify("Tests passed on M8.")

        assert spans
        assert classifier.last_degraded is True

    def test_the_fallback_is_visible(self) -> None:
        """A classifier that silently degraded would report semantic output
        that was produced by rules — the exact confusion `semantic` exists to
        prevent."""

        classifier = BedrockObservationClassifier(
            region="us-east-1",
            client=_Client(
                RuntimeError("down"),
                _answer({"index": 0, "classification": "requirement", "confidence": 0.8}),
            ),
        )

        classifier.classify(SENTENCE)
        assert classifier.last_degraded is True

        classifier.classify(SENTENCE)

        assert classifier.last_degraded is False

    def test_a_refusal_falls_back_too(self) -> None:
        classifier = _classifier(_Response("{}", stop_reason="refusal"))

        classifier.classify(SENTENCE)

        assert classifier.last_degraded is True

    def test_unparseable_output_falls_back(self) -> None:
        classifier = _classifier(_Response("not json at all"))

        classifier.classify(SENTENCE)

        assert classifier.last_degraded is True


class TestSelectionIsExplicit:
    def test_the_default_is_deterministic(self) -> None:
        """A cloned repository must walk the whole workflow with no account, no
        credentials, and no bill."""

        assert classifier_name({}) == CLASSIFIER_DETERMINISTIC
        built, name = build_classifier({})
        assert built.semantic is False
        assert classifies_by_meaning(name) is False

    def test_semantic_needs_a_region_rather_than_falling_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Separate from the runtime fallback. A deployment that asked for
        semantic classification and silently received rules would report
        `semantic_classification: false` correctly while nobody understood
        why.

        The profile is stubbed out: a developer with a working `~/.aws/config`
        would otherwise resolve a region and never see this refusal, which is
        a test that passes on the machine least likely to need it.
        """

        monkeypatch.setattr("kae_memory.agents.provider.resolve_region", lambda environ=None: None)

        with pytest.raises(ProviderConfigurationError, match="requires an AWS region"):
            build_classifier({"KAE_OBSERVATION_CLASSIFIER": "semantic"})

    def test_semantic_builds_when_a_region_is_configured(self) -> None:
        built, name = build_classifier(
            {"KAE_OBSERVATION_CLASSIFIER": "semantic", "AWS_REGION": "us-east-1"}
        )

        assert built.semantic is True
        assert classifies_by_meaning(name) is True

    def test_an_unknown_selection_is_refused(self) -> None:
        with pytest.raises(ProviderConfigurationError, match="unknown"):
            build_classifier({"KAE_OBSERVATION_CLASSIFIER": "magic"})

    def test_classification_is_reported_apart_from_embedding(self) -> None:
        """A deployment can rank by meaning and classify by rule, or the
        reverse. One capability must not answer for the other."""

        described = describe({"KAE_OBSERVATION_CLASSIFIER": "deterministic"})

        assert described["ranks_by_meaning"] is False
        assert described["classifies_by_meaning"] is False
        assert described["classifier"] == CLASSIFIER_DETERMINISTIC


class TestSemanticReportsWhatActuallyHappened:
    """`semantic` must describe the call, not the class.

    AUD-007. It returned a hard-coded `True`, so a provider timeout fell back
    to regexes and the span was still persisted — and served over
    `GET /classifications` — as semantically classified. The class docstring
    names this as the exact confusion `semantic` exists to prevent, and it was
    the behaviour.

    False provenance in the system of record is the one class of defect that
    does not decay: the row outlives the incident, and nothing marks it.
    """

    def test_a_successful_call_reports_semantic(self) -> None:
        classifier = _classifier(
            _answer({"text": "Individual founders are the first users.", "kind": "actor"})
        )

        classifier.classify("Individual founders are the first users.")

        assert classifier.semantic is True
        assert classifier.last_degraded is False

    def test_a_degraded_call_does_not_report_semantic(self) -> None:
        classifier = _classifier(RuntimeError("provider unavailable"))

        classifier.classify("Individual founders are the first users.")

        assert classifier.last_degraded is True
        # The assertion the finding is about. Rules ran; saying otherwise puts a
        # claim into a durable row that nothing downstream can question.
        assert classifier.semantic is False

    def test_it_recovers_when_the_provider_does(self) -> None:
        """A single failure must not permanently mark a classifier as degraded.

        `_degraded` is per-call state. If it latched, one timeout would make
        every later span report rule-based classification, which is the same
        defect pointing the other way.
        """

        classifier = _classifier(RuntimeError("provider unavailable"))
        classifier.classify("Individual founders are the first users.")
        assert classifier.semantic is False

        classifier._client = _Client(
            _answer({"text": "Individual founders are the first users.", "kind": "actor"})
        )
        classifier.classify("Individual founders are the first users.")

        assert classifier.semantic is True
