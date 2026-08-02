"""Fixture-backed review, and the offline stand-in that keeps it demonstrable.

Mirrors :mod:`~kae_memory.agents.deterministic`: recorded payloads pass through
the same resolution path a live response would, so a payload that production
would reject is rejected here too.

The offline reviewer is **not review intelligence**. It finds contradiction
candidates by negation-matching, and classifies only where a kind is accepted
by exactly one area — surface rules a language model would not need. It refuses
the ambiguous cases rather than guessing them (ADR-0015). It exists so that
cloning the repository is enough to walk the chain, and any demonstration
leaning on it should say which adapter ran.
"""

from collections.abc import Callable, Sequence

from kae_memory.application.review_service import unambiguous_area_for
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.lexical import content_words, is_negated, similarity

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

_OPPOSED_SIMILARITY = 0.6
"""How alike two statements must be before a polarity difference reads as conflict.

Lower than the near-duplicate bar: a contradiction is worth surfacing on weaker
evidence than a housekeeping duplicate, because missing one is expensive.
"""


def offline_review_fixture(request: ReviewRequest) -> object:
    """Propose an area per statement, and flag negation-opposed near-twins."""

    findings: list[dict[str, object]] = []

    for statement in request.statements:
        # Only where the kind leaves no choice. Picking between "functional
        # requirements" and "quality attributes" for a requirement is the
        # discrimination a model is for, and guessing it offline would
        # manufacture coverage a user then has to unpick (ADR-0015).
        area = unambiguous_area_for(statement.kind)
        if area and (not request.area_keys or area in request.area_keys):
            findings.append(
                {
                    "kind": "area_classification",
                    "statement_quote": statement.text,
                    "area_key": area,
                    "confidence": Confidence.LOW.value,
                    "rationale": (
                        f"offline fixture: kind {statement.kind!r} is accepted by "
                        "exactly one area, so no judgement was needed"
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

    if is_negated(first) == is_negated(second):
        return False
    if not content_words(first) or not content_words(second):
        return False
    return similarity(first, second) >= _OPPOSED_SIMILARITY


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
