"""The review port's grounding rule.

Every finding must quote a statement in the reviewed set, so a reviewer cannot
comment on a statement it never read. This mirrors what ``verify_quotes`` does
for extraction, and it is the reason a review finding can be trusted enough to
act on.

Review *orchestration* — which engine runs, what it may write, how it recovers —
is a worker concern and is covered in ``tests/worker/test_unified_review.py``.
"""

from __future__ import annotations

import pytest

from kae_memory.agents.review import (
    InvalidReviewOutputError,
    ReviewedStatement,
    ReviewFindingKind,
    ReviewRequest,
    UnverifiableReviewError,
    resolve,
)
from kae_memory.agents.review_adapter import offline_review_fixture
from kae_memory.domain.identifiers import KnowledgeItemId


class TestGrounding:
    def _request(self) -> ReviewRequest:
        return ReviewRequest(
            statements=(
                ReviewedStatement(
                    knowledge_id=KnowledgeItemId("11111111-1111-1111-1111-111111111111"),
                    kind="rule",
                    text="A submitter cannot approve their own report.",
                ),
            ),
            area_keys=("acceptance_criteria",),
        )

    def test_a_quote_outside_the_reviewed_set_is_rejected(self) -> None:
        """The load-bearing guarantee, mirroring extraction's verify_quotes."""

        with pytest.raises(UnverifiableReviewError):
            resolve(
                {"findings": [{"kind": "unsupported_claim", "statement_quote": "Invented."}]},
                self._request(),
            )

    def test_rewrapped_whitespace_still_matches(self) -> None:
        """Re-wrapping a line is not paraphrasing, and must not fail."""

        findings = resolve(
            {
                "findings": [
                    {
                        "kind": "unsupported_claim",
                        "statement_quote": "A submitter cannot\n  approve their own report.",
                    }
                ]
            },
            self._request(),
        )

        assert findings[0].kind is ReviewFindingKind.UNSUPPORTED_CLAIM

    def test_a_finding_must_quote_something(self) -> None:
        with pytest.raises(InvalidReviewOutputError):
            resolve({"findings": [{"kind": "unsupported_claim"}]}, self._request())

    def test_an_unknown_area_is_rejected(self) -> None:
        """A reviewer may not invent a discovery area to file a statement under."""

        with pytest.raises(InvalidReviewOutputError):
            resolve(
                {
                    "findings": [
                        {
                            "kind": "area_classification",
                            "statement_quote": "A submitter cannot approve their own report.",
                            "area_key": "made_up_area",
                        }
                    ]
                },
                self._request(),
            )

    def test_a_statement_cannot_contradict_itself(self) -> None:
        text = "A submitter cannot approve their own report."
        with pytest.raises(InvalidReviewOutputError):
            resolve(
                {
                    "findings": [
                        {
                            "kind": "contradiction",
                            "statement_quote": text,
                            "counterpart_quote": text,
                        }
                    ]
                },
                self._request(),
            )

    def test_the_offline_fixture_is_honest_about_itself(self) -> None:
        """A demo leaning on rules must not read as model judgement."""

        request = ReviewRequest(
            statements=(
                ReviewedStatement(
                    knowledge_id=KnowledgeItemId("22222222-2222-2222-2222-222222222222"),
                    kind="actor",
                    text="Ministry leaders submit monthly reports.",
                ),
            ),
            area_keys=("users_and_stakeholders",),
        )

        payload = offline_review_fixture(request)

        assert isinstance(payload, dict)
        rationales = " ".join(str(f.get("rationale", "")) for f in payload["findings"])
        assert "offline fixture" in rationales
