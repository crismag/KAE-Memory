"""Review from a model on this machine, and the two things it must not do.

The step that kept readiness empty on every offline deployment: extraction,
embedding and observation classification all went local under `ADR-0006`, and
review did not — so an offline project was classified by a rule that fires for
two knowledge kinds of eight, and nine discovery areas of ten stayed `missing`.

The two assertions that matter most are negative ones. It must not resolve a
quote it was never given, because a finding is only attached to a statement by
its quote. And it must not swallow a provider failure — `ReviewStep` degrades
per batch and records which failure, and an adapter that fell back inside itself
while carrying `judges = True` would report `reviewed_by_model` about output no
model produced (`AUD-039`, `D-266`).
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from kae_memory.agents.extraction import (
    InvalidOutputError,
    OutputTruncatedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from kae_memory.agents.ollama_review import OllamaReviewAdapter
from kae_memory.agents.review import (
    InvalidReviewOutputError,
    ReviewedStatement,
    ReviewFindingKind,
    ReviewRequest,
    UnverifiableReviewError,
    judges,
)
from kae_memory.domain.identifiers import KnowledgeItemId

FIRST = "The receptionist books appointments for four therapists."
SECOND = "Every invoice must carry the client reference assigned at booking."

FIRST_ID = KnowledgeItemId("11111111-1111-4111-8111-111111111111")
SECOND_ID = KnowledgeItemId("22222222-2222-4222-8222-222222222222")


def request() -> ReviewRequest:
    return ReviewRequest(
        statements=(
            ReviewedStatement(knowledge_id=FIRST_ID, kind="actor", text=FIRST),
            ReviewedStatement(knowledge_id=SECOND_ID, kind="rule", text=SECOND),
        ),
        area_keys=("users_and_stakeholders", "functional_scope"),
    )


def answering(payload: Any, **body: Any) -> OllamaReviewAdapter:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:14b",
                "message": {
                    "content": json.dumps(payload) if not isinstance(payload, str) else payload
                },
                "prompt_eval_count": 900,
                "eval_count": 120,
                **body,
            },
        )

    return OllamaReviewAdapter(transport=httpx.MockTransport(handler))


def classification(quote: str, area: str = "users_and_stakeholders") -> dict[str, Any]:
    return {
        "kind": "area_classification",
        "statement_quote": quote,
        "area_key": area,
        "confidence": "high",
        "rationale": "the statement names who uses the system",
    }


class TestWhatItProduces:
    def test_a_classification_resolves_to_the_statement_it_quoted(self) -> None:
        adapter = answering({"findings": [classification(FIRST)]})

        result = adapter.review(request())

        assert len(result.findings) == 1
        finding = result.findings[0]
        assert finding.kind is ReviewFindingKind.AREA_CLASSIFICATION
        assert finding.subject_id == FIRST_ID
        assert finding.area_key == "users_and_stakeholders"
        assert result.model == "qwen2.5:14b"
        assert result.usage is not None
        assert result.usage["input_tokens"] == 900

    def test_it_asks_for_the_work_rather_than_sending_bare_lists(self) -> None:
        """`BedrockReviewAdapter`'s lesson, copied with it.

        Its first version sent a list of areas and a list of statements and got
        zero findings for three obviously classifiable statements. A system
        prompt describing a job is not the same as being asked to do it on this
        input, so the instruction is repeated in the message.
        """

        sent: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"message": {"content": '{"findings": []}'}})

        OllamaReviewAdapter(transport=httpx.MockTransport(handler)).review(request())

        messages = sent["messages"]
        assert [m["role"] for m in messages] == ["system", "user"]
        user = messages[1]["content"]
        assert "users_and_stakeholders" in user
        assert FIRST in user and SECOND in user
        assert "area_classification" in user
        # A schema, not `"json"`. Without it a 14B model wraps its JSON in prose.
        assert isinstance(sent["format"], dict)
        assert sent["stream"] is False

    def test_the_prompt_is_the_shared_one_and_not_a_second_definition(self) -> None:
        """`D-122`'s rule, applied to review (`D-266`).

        A second prompt written here would be a second definition of
        `ReviewFindingKind`, and the two would part company at the first change.
        """

        from kae_memory.agents.prompts import prompt_for
        from kae_memory.domain.execution import AgentRole

        sent: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            sent.update(json.loads(req.content))
            return httpx.Response(200, json={"message": {"content": '{"findings": []}'}})

        version, system_prompt = prompt_for(AgentRole.REVIEW)
        result = OllamaReviewAdapter(transport=httpx.MockTransport(handler)).review(request())

        assert sent["messages"][0]["content"] == system_prompt
        assert result.prompt_version == version


class TestItClaimsJudgement:
    def test_it_declares_that_it_judges(self) -> None:
        """The flag `AUD-039` made readiness read.

        `judges()` defaults to `False`, so an adapter that forgets this
        under-claims and a run backed by a model reports `reviewed_by_fixture`.
        A 14B model placing a statement among ten named areas is doing the
        discrimination the deterministic adapter refuses to guess at.
        """

        assert judges(OllamaReviewAdapter()) is True


class TestTheQuoteCheckIsNotRelaxed:
    def test_a_quote_matching_no_statement_is_unverifiable(self) -> None:
        adapter = answering({"findings": [classification("The receptionist handles all billing")]})

        with pytest.raises(UnverifiableReviewError):
            adapter.review(request())

    def test_an_area_outside_the_ones_offered_is_refused(self) -> None:
        adapter = answering({"findings": [classification(FIRST, area="invented_area")]})

        with pytest.raises(InvalidReviewOutputError):
            adapter.review(request())

    def test_rewrapped_whitespace_still_matches(self) -> None:
        """The same normalisation extraction uses: a re-wrapped line is not a
        paraphrase, and punishing it would discard correct findings."""

        adapter = answering({"findings": [classification(FIRST.replace(" ", "\n  "))]})

        assert adapter.review(request()).findings[0].subject_id == FIRST_ID


class TestWhenItCannotWork:
    """Every one of these reaches `ReviewStep`, which degrades the batch and
    records the error code. None of them is handled here (`D-266`)."""

    def test_a_missing_model_says_how_to_pull_it(self) -> None:
        adapter = OllamaReviewAdapter(
            transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"error": "no"}))
        )

        with pytest.raises(ProviderUnavailableError, match=re.escape("ollama pull qwen2.5:14b")):
            adapter.review(request())

    def test_ollama_not_running_names_the_setting_that_changes_it(self) -> None:
        def refuse(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        adapter = OllamaReviewAdapter(transport=httpx.MockTransport(refuse))

        with pytest.raises(ProviderUnavailableError, match="KAE_REVIEW"):
            adapter.review(request())

    def test_a_timeout_is_its_own_failure(self) -> None:
        def stall(_: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow")

        adapter = OllamaReviewAdapter(transport=httpx.MockTransport(stall))

        with pytest.raises(ProviderTimeoutError):
            adapter.review(request())

    def test_hitting_the_context_ceiling_is_truncation_not_bad_json(self) -> None:
        """The remedy is `KAE_REVIEW_BATCH`, not a repaired adapter."""

        adapter = answering({"findings": []}, done_reason="length")

        with pytest.raises(OutputTruncatedError):
            adapter.review(request())

    def test_prose_around_the_json_is_an_invalid_output(self) -> None:
        adapter = answering('Here are the findings: {"findings": []}')

        with pytest.raises(InvalidOutputError):
            adapter.review(request())

    def test_an_empty_response_is_refused(self) -> None:
        adapter = answering("   ")

        with pytest.raises(InvalidOutputError):
            adapter.review(request())
