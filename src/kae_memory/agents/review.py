"""The review boundary — findings about recorded knowledge, not new knowledge.

Separate from :mod:`~kae_memory.agents.extraction` because the two produce
different things. Extraction turns text into candidate statements. Review reads
statements that already exist and reports how they relate: which pair conflicts,
which discovery area a statement serves, which claim the record does not
support. A review finding is *about* knowledge and is never itself knowledge —
folding it into ``ExtractedItem`` would put findings in the extraction
vocabulary and, through it, into the readiness denominator.

The grounding rule carries over unchanged and is enforced the same way. Every
finding must quote a statement that actually exists in the reviewed set; a quote
matching nothing is :class:`UnverifiableReviewError`, not a rounding error. The
model never sees or returns identifiers — it quotes, and the quote is resolved
here — so a finding cannot reference a statement the reviewer never read.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from kae_memory.domain.identifiers import KnowledgeItemId

from .extraction import Confidence, ExtractionError

SCHEMA_VERSION = "review.v1"
"""The review payload contract. A change here is a new version, never an edit."""


class ReviewError(ExtractionError):
    """Base class for review failures.

    Inherits the extraction hierarchy so a caller mapping provider outcomes to
    run failure codes handles both without knowing which port ran.
    """

    error_code = "review_failed"
    retryable = False


class InvalidReviewOutputError(ReviewError):
    """The payload was malformed or named something outside the vocabulary."""

    error_code = "invalid_review_output"
    retryable = False


class UnverifiableReviewError(ReviewError):
    """A finding quoted a statement that is not in the reviewed set.

    Not retryable: the reviewer was given the statements, so a quote that
    matches none of them is a fabrication rather than a transient slip.
    """

    error_code = "unverifiable_review"
    retryable = False


class ReviewFindingKind(StrEnum):
    """What a reviewer may report.

    Deliberately small. Each value maps to something the domain can already
    record, so a finding never lands somewhere no one will look.
    """

    CONTRADICTION = "contradiction"
    AREA_CLASSIFICATION = "area_classification"
    UNSUPPORTED_CLAIM = "unsupported_claim"


@dataclass(frozen=True, slots=True)
class ReviewedStatement:
    """One statement offered to the reviewer, with the identity it keeps."""

    knowledge_id: KnowledgeItemId
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """One resolved finding: quotes already matched back to statements."""

    kind: ReviewFindingKind
    subject_id: KnowledgeItemId
    confidence: Confidence
    rationale: str
    counterpart_id: KnowledgeItemId | None = None
    area_key: str | None = None

    def __post_init__(self) -> None:
        if self.kind is ReviewFindingKind.CONTRADICTION and self.counterpart_id is None:
            raise InvalidReviewOutputError("a contradiction must name both statements")
        if self.kind is ReviewFindingKind.CONTRADICTION and self.counterpart_id == self.subject_id:
            raise InvalidReviewOutputError("a statement cannot contradict itself")
        if self.kind is ReviewFindingKind.AREA_CLASSIFICATION and not self.area_key:
            raise InvalidReviewOutputError("an area classification must name an area")


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """What the reviewer is asked to read."""

    statements: Sequence[ReviewedStatement]
    area_keys: Sequence[str] = ()
    max_findings: int = 40


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """What the reviewer returned, plus what produced it."""

    findings: tuple[ReviewFinding, ...]
    prompt_version: str
    schema_version: str
    model: str
    usage: dict[str, Any] | None = None


class ReviewPort(Protocol):
    """The review provider boundary."""

    def review(self, request: ReviewRequest) -> ReviewResult: ...


def resolve(payload: Any, request: ReviewRequest) -> tuple[ReviewFinding, ...]:
    """Turn a raw payload into findings, resolving every quote to a statement.

    Quote matching is exact after whitespace collapsing, the same normalisation
    extraction uses, so a reviewer that re-wraps a line is not punished for it
    while one that paraphrases still fails.
    """

    if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
        raise InvalidReviewOutputError("payload must be an object with a 'findings' list")

    by_text = {_normalise(s.text): s for s in request.statements}
    valid_areas = set(request.area_keys)
    findings: list[ReviewFinding] = []

    for raw in payload["findings"][: request.max_findings]:
        if not isinstance(raw, dict):
            raise InvalidReviewOutputError("each finding must be an object")
        try:
            kind = ReviewFindingKind(raw.get("kind", ""))
        except ValueError as error:
            raise InvalidReviewOutputError(
                f"unknown review finding kind: {raw.get('kind')!r}"
            ) from error

        subject = _match(raw.get("statement_quote"), by_text)
        counterpart = (
            _match(raw.get("counterpart_quote"), by_text) if raw.get("counterpart_quote") else None
        )
        area_key = raw.get("area_key") or None
        if area_key and valid_areas and area_key not in valid_areas:
            raise InvalidReviewOutputError(f"unknown discovery area: {area_key!r}")

        findings.append(
            ReviewFinding(
                kind=kind,
                subject_id=subject.knowledge_id,
                counterpart_id=counterpart.knowledge_id if counterpart else None,
                area_key=area_key,
                confidence=Confidence(raw.get("confidence", Confidence.MEDIUM.value)),
                rationale=str(raw.get("rationale") or "").strip(),
            )
        )
    return tuple(findings)


def _match(quote: Any, by_text: dict[str, ReviewedStatement]) -> ReviewedStatement:
    if not isinstance(quote, str) or not quote.strip():
        raise InvalidReviewOutputError("every finding must quote the statement it concerns")
    statement = by_text.get(_normalise(quote))
    if statement is None:
        raise UnverifiableReviewError(
            f"quoted statement is not in the reviewed set: {quote[:80]!r}"
        )
    return statement


def _normalise(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "SCHEMA_VERSION",
    "InvalidReviewOutputError",
    "ReviewError",
    "ReviewFinding",
    "ReviewFindingKind",
    "ReviewPort",
    "ReviewRequest",
    "ReviewResult",
    "ReviewedStatement",
    "UnverifiableReviewError",
    "resolve",
]
