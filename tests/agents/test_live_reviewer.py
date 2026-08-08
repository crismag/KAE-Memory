"""EM-6b — review can be done by a model, and says when it cannot (F-019).

The reviewer that ships is `DeterministicReviewAdapter`, which classifies only
where a knowledge kind leaves no choice. Measured across four real projects
holding 1,575 statements it populated **two discovery areas out of ten**: 242
requirements, 197 rules, 66 goals and 36 decisions were assigned nowhere,
because deciding whether a requirement is about *scope* or about *quality
attributes* is a judgement a lookup will not make.

Readiness counts statements per area. The consequence was therefore not a wrong
number — it was a number **correct about a fifth of the taxonomy**, on every
project in the system, and it took four real projects to notice.

These tests use a fake client rather than Bedrock. What is being checked is the
adapter's contract — what it sends, what it refuses, what it does with a reply —
and none of that is a claim about the model. Whether the model classifies *well*
is measured by running it over the reference corpus, which a test cannot assert.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from kae_memory.agents.bedrock import BedrockReviewAdapter
from kae_memory.agents.extraction import (
    InvalidOutputError,
    OutputTruncatedError,
    ProviderRefusedError,
)
from kae_memory.agents.review import (
    REVIEW_SCHEMA,
    ReviewedStatement,
    ReviewFindingKind,
    ReviewRequest,
    UnverifiableReviewError,
)
from kae_memory.domain.identifiers import KnowledgeItemId

AREAS = ("users_and_stakeholders", "scope_and_boundaries", "quality_attributes")

STATEMENTS = (
    ReviewedStatement(
        knowledge_id=KnowledgeItemId("k-1"),
        text="A single freelancer is the only person who uses the system.",
        kind="actor",
    ),
    ReviewedStatement(
        knowledge_id=KnowledgeItemId("k-2"),
        text="An invoice must be sent within three days of a job finishing.",
        kind="rule",
    ),
)


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, payload: Any, stop_reason: str | None = None) -> None:
        self.content = [_Block(json.dumps(payload) if not isinstance(payload, str) else payload)]
        self.stop_reason = stop_reason
        self.model = "test-model"
        self.usage = None


class _Messages:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.last_call: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.last_call = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _Client:
    def __init__(self, response: Any) -> None:
        self.messages = _Messages(response)

    def with_options(self, **_: Any) -> _Client:
        return self


def _adapter(response: Any) -> tuple[BedrockReviewAdapter, _Client]:
    client = _Client(response)
    return BedrockReviewAdapter(region="ca-central-1", client=client), client


def _request() -> ReviewRequest:
    return ReviewRequest(statements=STATEMENTS, area_keys=AREAS)


class TestItClassifiesIntoAreas:
    def test_a_classification_becomes_a_finding(self) -> None:
        """The capability F-019 is about.

        The fixture reviewer cannot produce this for a `rule`, which is why 197
        rules went unassigned.
        """

        adapter, _ = _adapter(
            _Response(
                {
                    "findings": [
                        {
                            "kind": "area_classification",
                            "statement_quote": STATEMENTS[1].text,
                            "area_key": "scope_and_boundaries",
                            "confidence": "high",
                            "rationale": "It bounds when invoicing must happen.",
                        }
                    ]
                }
            )
        )

        result = adapter.review(_request())

        (finding,) = result.findings
        assert finding.kind is ReviewFindingKind.AREA_CLASSIFICATION
        assert finding.area_key == "scope_and_boundaries"
        assert finding.subject_id == STATEMENTS[1].knowledge_id

    def test_the_available_areas_are_sent(self) -> None:
        """A reviewer that is not told the areas cannot classify into them.

        They go in the message rather than the system prompt because they vary
        per project, and anything varying must sit after the cache breakpoint or
        it defeats the prefix match for every request.
        """

        adapter, client = _adapter(_Response({"findings": []}))

        adapter.review(_request())

        content = client.messages.last_call["messages"][0]["content"]
        for area in AREAS:
            assert area in content
        assert "cache_control" in client.messages.last_call["system"][0]

    def test_the_schema_is_enforced_by_the_provider(self) -> None:
        adapter, client = _adapter(_Response({"findings": []}))

        adapter.review(_request())

        sent = client.messages.last_call["output_config"]["format"]["schema"]
        assert sent is REVIEW_SCHEMA


class TestItCannotClassifyWhatItInvented:
    def test_a_quote_that_was_not_sent_is_refused(self) -> None:
        """The guarantee that makes a classification traceable.

        Without it a reviewer could assign an area to a statement the project
        does not hold, and readiness would count something nobody said.
        """

        adapter, _ = _adapter(
            _Response(
                {
                    "findings": [
                        {
                            "kind": "area_classification",
                            "statement_quote": "The system supports offline mode.",
                            "area_key": "scope_and_boundaries",
                        }
                    ]
                }
            )
        )

        with pytest.raises(UnverifiableReviewError):
            adapter.review(_request())

    def test_an_unknown_area_is_refused(self) -> None:
        """Areas are a fixed vocabulary, not a suggestion.

        An invented area would be silently dropped downstream — the assignment
        would fail to match a real area and the statement would simply stay
        unclassified, which is indistinguishable from the reviewer not trying.
        """

        adapter, _ = _adapter(
            _Response(
                {
                    "findings": [
                        {
                            "kind": "area_classification",
                            "statement_quote": STATEMENTS[0].text,
                            "area_key": "invented_area",
                        }
                    ]
                }
            )
        )

        with pytest.raises(Exception, match="unknown discovery area"):
            adapter.review(_request())


class TestProviderOutcomesAreTyped:
    def test_a_refusal_is_not_an_empty_review(self) -> None:
        """A refused request that returned no findings would read as "nothing to
        classify", which is the same thing a healthy review of a clean project
        says."""

        adapter, _ = _adapter(_Response({"findings": []}, stop_reason="refusal"))

        with pytest.raises(ProviderRefusedError):
            adapter.review(_request())

    def test_truncation_is_not_a_short_review(self) -> None:
        """Half a review looks exactly like a review that found half as much."""

        adapter, _ = _adapter(_Response({"findings": []}, stop_reason="max_tokens"))

        with pytest.raises(OutputTruncatedError):
            adapter.review(_request())

    def test_a_non_json_reply_is_typed(self) -> None:
        adapter, _ = _adapter(_Response("not json at all"))

        with pytest.raises(InvalidOutputError):
            adapter.review(_request())


class TestTheSelectorRefusesRatherThanDegrading:
    def test_bedrock_without_a_region_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The failure mode this whole phase exists to prevent.

        A reviewer that quietly fell back to the fixture would leave a
        deployment believing it was classifying with a model while two areas of
        ten populated. That is precisely the state EM-6b ends, and it took four
        real projects to notice — so it must not be reachable by a
        misconfiguration.
        """

        from kae_memory.worker import execution

        monkeypatch.setenv("KAE_REVIEW", "bedrock")
        monkeypatch.setattr(execution, "resolve_region", lambda: "")

        with pytest.raises(RuntimeError, match="region"):
            execution.default_reviewer()

    def test_the_default_is_still_the_fixture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unchanged deliberately.

        The demonstrable path must not require a provider, a credential or a
        bill — a clone of this repository reviews offline.
        """

        from kae_memory.agents.review_adapter import DeterministicReviewAdapter
        from kae_memory.worker import execution

        monkeypatch.delenv("KAE_REVIEW", raising=False)

        assert isinstance(execution.default_reviewer(), DeterministicReviewAdapter)

    def test_off_still_disables_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kae_memory.worker import execution

        monkeypatch.setenv("KAE_REVIEW", "off")

        assert execution.default_reviewer() is None
