"""Classifying with a local model, and the failures it must stay honest about.

`OFF-OLLAMA-LLM`, `D-122`. The adapter is a transport: what a class *means* comes
from `semantic_classifier`, so most of what is worth asserting here is that it
did not quietly acquire its own opinion — and that a machine with no Ollama
running degrades visibly rather than reporting rules as meaning.

A mocked transport proves our end of the protocol; the live test at the end
proves the model, and skips with its reason when there is none.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from kae_memory.agents.ollama_classifier import (
    OLLAMA_CLASSIFIER_NAME,
    OllamaObservationClassifier,
)
from kae_memory.agents.semantic_classifier import (
    CLASSIFICATION_PROMPT,
    CLASSIFICATION_SCHEMA,
    SEMANTIC_CLASSIFIER_NAME,
)
from kae_memory.domain.observation import ObservationClass

TWO_SENTENCES = "The system must support search. I merged the branch this morning."


def responding(handler: Any) -> OllamaObservationClassifier:
    return OllamaObservationClassifier(transport=httpx.MockTransport(handler))


def answering(*classes: str) -> Callable[[httpx.Request], httpx.Response]:
    """A transport replying with one entry per sentence index."""

    payload = {
        "spans": [
            {"index": index, "classification": value, "confidence": 0.9}
            for index, value in enumerate(classes)
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"message": {"content": json.dumps(payload)}, "model": "qwen2.5:14b"}
        )

    return handler


class TestWhatItClassifies:
    def test_each_sentence_gets_the_class_the_model_named(self) -> None:
        classifier = responding(answering("requirement", "progress_update"))

        spans = classifier.classify(TWO_SENTENCES)

        assert [span.classification for span in spans] == [
            ObservationClass.REQUIREMENT,
            ObservationClass.PROGRESS_UPDATE,
        ]
        assert classifier.semantic is True
        assert classifier.last_degraded is False

    def test_the_offsets_come_from_the_split_and_never_from_the_model(self) -> None:
        """The one failure a provenance system cannot tolerate: a span that
        points at text other than the sentence it classified."""

        classifier = responding(answering("requirement", "progress_update"))

        spans = classifier.classify(TWO_SENTENCES)

        for span in spans:
            assert TWO_SENTENCES[span.span.start : span.span.end] == span.normalized_text

    def test_a_sentence_the_model_skipped_is_unclassified_rather_than_guessed(self) -> None:
        classifier = responding(answering("requirement"))

        spans = classifier.classify(TWO_SENTENCES)

        assert spans[1].classification is ObservationClass.UNCLASSIFIED
        assert spans[1].confidence == 0.0

    def test_empty_text_asks_the_model_nothing(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no sentence, so there was nothing to classify")

        classifier = responding(refuse)

        assert classifier.classify("   ") == ()
        assert classifier.last_degraded is False


class TestItIsATransportAndNotASecondClassifier:
    """`D-122`. A second prompt or a second parser here would be a second
    definition of the twenty-six classes."""

    def test_it_sends_the_shared_prompt_and_the_shared_schema(self) -> None:
        seen: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return answering("requirement", "progress_update")(request)

        responding(capture).classify(TWO_SENTENCES)

        assert seen["messages"][0]["content"] == CLASSIFICATION_PROMPT
        assert seen["format"] == CLASSIFICATION_SCHEMA
        assert seen["stream"] is False

    def test_the_model_is_given_numbered_sentences_and_not_the_raw_text(self) -> None:
        seen: dict[str, Any] = {}

        def capture(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return answering("requirement", "progress_update")(request)

        responding(capture).classify(TWO_SENTENCES)

        assert seen["messages"][1]["content"] == (
            "0. The system must support search.\n1. I merged the branch this morning."
        )

    def test_it_reports_its_own_name_so_provenance_can_tell_the_two_apart(self) -> None:
        classifier = responding(answering("requirement", "progress_update"))

        assert classifier.name == OLLAMA_CLASSIFIER_NAME
        assert classifier.name != SEMANTIC_CLASSIFIER_NAME


class TestItDegradesVisibly:
    """Ollama not running is the ordinary state of a machine nobody started it
    on, so this is the common path rather than the exceptional one."""

    def test_an_unreachable_ollama_falls_back_to_rules_and_says_so(self) -> None:
        def unreachable(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        classifier = responding(unreachable)

        spans = classifier.classify(TWO_SENTENCES)

        assert spans, "the observation keeps a classification rather than losing one"
        assert classifier.last_degraded is True
        assert classifier.semantic is False

    def test_a_missing_model_degrades_rather_than_raising(self) -> None:
        classifier = responding(lambda request: httpx.Response(404, json={}))

        assert classifier.classify(TWO_SENTENCES)
        assert classifier.last_degraded is True

    def test_a_truncated_answer_degrades_rather_than_being_half_read(self) -> None:
        classifier = responding(
            lambda request: httpx.Response(
                200, json={"done_reason": "length", "message": {"content": '{"spans": ['}}
            )
        )

        assert classifier.classify(TWO_SENTENCES)
        assert classifier.last_degraded is True

    def test_a_recovered_call_stops_reporting_as_degraded(self) -> None:
        """`AUD-007`'s defect from the other side: a classifier that latched
        `degraded` would under-report meaning for the rest of its life."""

        calls: list[int] = []

        def failing_once(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ConnectError("connection refused")
            return answering("requirement", "progress_update")(request)

        classifier = responding(failing_once)

        classifier.classify(TWO_SENTENCES)
        assert classifier.last_degraded is True

        classifier.classify(TWO_SENTENCES)
        assert classifier.last_degraded is False


@pytest.mark.skipif(
    not os.environ.get("KAE_OLLAMA_LIVE"),
    reason="needs a running Ollama; set KAE_OLLAMA_LIVE=1",
)
class TestAgainstARealModel:
    def test_it_reads_a_requirement_no_regular_expression_would_find(self) -> None:
        """The sentence `semantic_classifier` opens by naming as the reason this
        path exists at all."""

        classifier = OllamaObservationClassifier()

        spans = classifier.classify("we'll probably want some way to search the old ones.")

        assert classifier.last_degraded is False
        assert spans[0].classification is not ObservationClass.UNCLASSIFIED
