"""Fixture-backed review, and the offline stand-in that keeps it demonstrable.

Mirrors :mod:`~kae_memory.agents.deterministic`: recorded payloads pass through
the same resolution path a live response would, so a payload that production
would reject is rejected here too.

The offline reviewer is **not review intelligence**. It finds contradictions by
negation-matching and classifies areas by knowledge kind — surface rules a
language model would not need. It exists so that cloning the repository is
enough to walk the chain, and any demonstration leaning on it should say which
adapter ran.
"""

import re
from collections.abc import Callable, Sequence

from kae_memory.domain.execution import AgentRole
from kae_memory.domain.models import KnowledgeKind

from .extraction import Confidence
from .prompts import prompt_for
from .review import (
    SCHEMA_VERSION,
    ReviewFinding,
    ReviewRequest,
    ReviewResult,
    resolve,
)

Fixture = Callable[[ReviewRequest], object]

_KIND_TO_AREA: dict[str, str] = {
    KnowledgeKind.GOAL.value: "problem_and_value",
    KnowledgeKind.ACTOR.value: "users_and_stakeholders",
    KnowledgeKind.REQUIREMENT.value: "functional_requirements",
    KnowledgeKind.CONSTRAINT.value: "constraints_and_assumptions",
    KnowledgeKind.ASSUMPTION.value: "constraints_and_assumptions",
    KnowledgeKind.RULE.value: "acceptance_criteria",
    KnowledgeKind.DECISION.value: "scope_and_boundaries",
}
"""Which area a kind most often serves.

A default, not a truth. Kinds cannot resolve areas on their own — "functional
requirements" and "quality attributes" are both ``requirement`` — which is
precisely why these are proposals a human confirms rather than assignments.
``unknown`` is absent: an open question belongs to no area until it is answered.
"""

_NEGATIONS = ("cannot", "must not", "never", "may not", "not")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    {"a", "an", "and", "be", "by", "for", "in", "is", "it", "of", "on", "or", "the", "to"}
)


def offline_review_fixture(request: ReviewRequest) -> object:
    """Propose an area per statement, and flag negation-opposed near-twins."""

    findings: list[dict[str, object]] = []

    for statement in request.statements:
        area = _KIND_TO_AREA.get(statement.kind)
        if area and (not request.area_keys or area in request.area_keys):
            findings.append(
                {
                    "kind": "area_classification",
                    "statement_quote": statement.text,
                    "area_key": area,
                    "confidence": Confidence.LOW.value,
                    "rationale": (
                        f"offline fixture mapped kind {statement.kind!r} to its most "
                        "common area; not a judgement about content"
                    ),
                }
            )

    for index, first in enumerate(request.statements):
        for second in request.statements[index + 1 :]:
            if _opposed(first.text, second.text):
                findings.append(
                    {
                        "kind": "contradiction",
                        "statement_quote": first.text,
                        "counterpart_quote": second.text,
                        "confidence": Confidence.LOW.value,
                        "rationale": (
                            "offline fixture: near-identical wording differing by a negation"
                        ),
                    }
                )
    return {"findings": findings}


def _opposed(first: str, second: str) -> bool:
    """Return whether two statements say the same thing with opposite polarity."""

    first_words = _content_words(first)
    second_words = _content_words(second)
    if not first_words or not second_words:
        return False
    if _negated(first) == _negated(second):
        return False
    shared = first_words & second_words
    union = first_words | second_words
    return len(shared) / len(union) >= 0.6


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        word for word in _WORD.findall(text.lower()) if word not in _STOP and word not in _NEGATIONS
    )


def _negated(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(f" {token} " in lowered for token in _NEGATIONS)


class DeterministicReviewAdapter:
    """Return recorded review payloads, resolved exactly as a live one would be."""

    model = "deterministic-review-fixture"

    def __init__(self, fixtures: Sequence[Fixture] | Fixture | None = None) -> None:
        if fixtures is None:
            self._fixtures: list[Fixture] = [offline_review_fixture]
        elif callable(fixtures):
            self._fixtures = [fixtures]
        else:
            self._fixtures = list(fixtures)
        self._calls = 0

    @property
    def call_count(self) -> int:
        return self._calls

    def review(self, request: ReviewRequest) -> ReviewResult:
        """Resolve the next fixture payload into findings."""

        fixture = self._fixtures[min(self._calls, len(self._fixtures) - 1)]
        self._calls += 1
        payload = fixture(request)
        version, _ = prompt_for(AgentRole.REVIEW)
        findings: tuple[ReviewFinding, ...] = resolve(payload, request)
        return ReviewResult(
            findings=findings,
            prompt_version=version,
            schema_version=SCHEMA_VERSION,
            model=self.model,
        )


__all__ = ["DeterministicReviewAdapter", "offline_review_fixture"]
