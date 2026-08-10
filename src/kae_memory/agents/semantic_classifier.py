"""Classifying an observation by meaning rather than by pattern (N43).

Resolves `OBSERVATION_CLASSIFICATION.md` §15 question 3. The deterministic
classifier reads wording it has a rule for and reports `unclassified` for
everything else, which is honest and is also most sentences: "we'll probably
want some way to search the old ones" is a requirement written the way people
actually write requirements, and no regular expression is going to find it.

**Deliberately narrow.** This decides a retention *tier*, not what a project
knows. Extraction produces candidate knowledge and is a separate path over the
same text — the first reading of the sparse-project failure confused the two,
and nothing here should encourage that again. A misclassification costs a
sentence being filed as evidence instead of as operational; a bad extraction
costs the project a requirement nobody agreed to.

Three properties hold it in place:

**Offsets are never model-derived.** The sentence split happens here, the model
sees numbered sentences, and it returns a class per number. A model asked for
character offsets will eventually return ones that do not line up, and a span
that does not line up points a reviewer at the wrong text — the one failure a
provenance system cannot tolerate.

**An unrecognised class is `unclassified`, not a guess.** A model naming a
class this version does not have is telling us it read something we cannot
route, and inventing the nearest match would file it confidently in the wrong
tier.

**It degrades rather than blocks.** Any provider failure falls back to the
deterministic classifier and says so. Classification is a convenience over
evidence that was already recorded; losing an observation because a model was
unreachable would invert what matters.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from kae_memory.domain.observation import ClassifiedSpan, ObservationClass, Span
from kae_memory.messages import message

from .observation_classifier import (
    DeterministicObservationClassifier,
    extract_fields,
)

SEMANTIC_CLASSIFIER_NAME = "kae-semantic-observation-classifier"
SEMANTIC_CLASSIFIER_VERSION = "1.0"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
"""Small on purpose. Assigning one of twenty-six labels to a sentence is not a
task that improves with a larger model, and this runs once per observation."""

DEFAULT_MAX_TOKENS = 2048

_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")

CLASSIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "spans": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "minimum": 0},
                    "classification": {
                        "type": "string",
                        "enum": [value.value for value in ObservationClass],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string", "maxLength": 300},
                },
                "required": ["index", "classification", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["spans"],
    "additionalProperties": False,
}

CLASSIFICATION_PROMPT_VERSION = "classification.v1"

CLASSIFICATION_PROMPT = """You assign a retention class to each numbered sentence \
of one observation about a software project.

You are not deciding what the project knows. You are deciding where a sentence \
is filed, so that a durable claim is not lost among status chatter and a \
passing remark is not promoted into a requirement.

Three tiers, and the tier is what the class means:

DURABLE — a claim about what the product is or must be. requirement, decision, \
open_question, assumption, constraint, scope, quality_attribute, domain_fact, \
acceptance_criterion, integration.

OPERATIONAL — a claim about where the work currently stands. task, \
milestone_status, check_in, deadline, blocker, test_result, defect, risk, \
progress_update, ownership_update.

EVIDENCE — kept, never promoted. session_note, personal_commentary, \
temporary_note, exploratory_statement, noise, unclassified.

Rules:

Classify what the sentence IS, not what it is about. "We should decide how \
search works" is an open_question, not a requirement — nobody decided anything.

Ordinary informal wording is normal. "I want somewhere to dump thoughts" is a \
requirement stated casually; it is not exploratory and it is not noise. \
Exploratory means the speaker is visibly still weighing it: "maybe we could", \
"I wonder whether".

Use unclassified when you genuinely cannot tell. It routes the sentence to a \
person, which is the correct outcome for something ambiguous. Do not reach for \
the nearest label to avoid saying so.

Confidence is how sure you are that the CLASS is right, not how important the \
sentence is. Below 0.5 sends it to a person, which is what you want when you \
are guessing.

Return one entry per sentence index you were given. Do not merge, split, \
reword, or skip sentences."""


class SemanticClassificationError(RuntimeError):
    """The provider could not classify. The caller falls back rather than failing."""


class BedrockObservationClassifier:
    """Classification by meaning, backed by Claude on Amazon Bedrock.

    Falls back to the deterministic classifier on any provider failure, and the
    fallback is **visible**: `last_degraded` says whether the most recent call
    used it. A classifier that silently degraded would report
    `semantic_classification: true` on rule-based output, which is the exact
    confusion `semantic` was introduced to prevent.
    """

    def __init__(
        self,
        region: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
        fallback: DeterministicObservationClassifier | None = None,
    ) -> None:
        self._region = region
        self.model = model
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._client = client
        self._fallback = fallback or DeterministicObservationClassifier()
        self._degraded = False

    @property
    def name(self) -> str:
        return SEMANTIC_CLASSIFIER_NAME

    @property
    def version(self) -> str:
        return SEMANTIC_CLASSIFIER_VERSION

    @property
    def semantic(self) -> bool:
        """Whether the **most recent** call classified by meaning.

        This returned a hard-coded `True`, which made the class docstring above
        false in exactly the way it warns against: a provider timeout fell back
        to regexes and the span was still persisted, and reported over HTTP, as
        semantically classified (AUD-007).

        `last_degraded` existed to carry the difference and had no production
        reader — the whole estate consulted `semantic`, which could not vary.
        So the honest fix is here rather than at every call site: the property
        callers already ask now answers the question they were asking.
        """

        return not self._degraded

    @property
    def last_degraded(self) -> bool:
        """Whether the most recent call fell back to rules.

        Exposed rather than logged. A caller deciding how much to trust an
        `unclassified` span needs to know whether it means "the model read this
        and could not tell" or "no model ran".
        """

        return self._degraded

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from anthropic import AnthropicBedrockMantle
            except ImportError as error:  # pragma: no cover - depends on extras
                raise SemanticClassificationError(
                    message("environment.bedrock_extra_missing")
                ) from error
            self._client = AnthropicBedrockMantle(aws_region=self._region)
        return self._client

    def classify(self, text: str) -> tuple[ClassifiedSpan, ...]:
        """Classify each sentence, falling back to rules if the provider fails."""

        sentences = split_sentences(text)
        if not sentences:
            self._degraded = False
            return ()

        try:
            assigned = self._ask(sentences)
        except Exception:
            # Any provider failure. The observation is already recorded; losing
            # its classification is a smaller loss than raising here would be,
            # and `last_degraded` keeps the difference readable.
            self._degraded = True
            return self._fallback.classify(text)

        self._degraded = False
        spans: list[ClassifiedSpan] = []
        for index, (sentence, span) in enumerate(sentences):
            classification, confidence, rationale = assigned.get(
                index,
                # A sentence the model skipped. Unclassified routes it to a
                # person, which is the right outcome for text nothing read.
                (ObservationClass.UNCLASSIFIED, 0.0, "the model returned no class"),
            )
            spans.append(
                ClassifiedSpan(
                    classification=classification,
                    confidence=confidence,
                    span=span,
                    # Whitespace-normalised only, as with the deterministic
                    # adapter. The model never rewrites the record.
                    normalized_text=" ".join(sentence.split()),
                    # Deterministic even here: dates, ids and status words are
                    # exactly what a rule reads correctly every time, and a
                    # model has no advantage over a regular expression at it.
                    fields=extract_fields(sentence),
                    rationale=rationale,
                )
            )
        return tuple(spans)

    def _ask(
        self, sentences: Sequence[tuple[str, Span]]
    ) -> dict[int, tuple[ObservationClass, float, str]]:
        """Return the model's class per sentence index."""

        client = self._ensure_client()
        numbered = "\n".join(
            f"{index}. {sentence}" for index, (sentence, _) in enumerate(sentences)
        )

        response = client.with_options(timeout=self._timeout).messages.create(
            model=self.model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": CLASSIFICATION_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": CLASSIFICATION_SCHEMA}},
            messages=[{"role": "user", "content": numbered}],
        )

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason in {"refusal", "max_tokens"}:
            raise SemanticClassificationError(f"the provider stopped: {stop_reason}")

        block = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
        if block is None:
            raise SemanticClassificationError("the response contained no text block")
        return parse_assignments(json.loads(block), len(sentences))


def split_sentences(text: str) -> tuple[tuple[str, Span], ...]:
    """Split into sentences and their exact offsets into ``text``.

    Here rather than in the model, and identical to the deterministic
    classifier's split so that the two adapters point at the same spans. A span
    that does not line up with the stored text sends a reviewer to the wrong
    sentence, which is worse than any misclassification.
    """

    found: list[tuple[str, Span]] = []
    for match in _SENTENCE.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        start = match.start() + (len(raw) - len(raw.lstrip()))
        found.append((stripped, Span(start, start + len(stripped))))
    return tuple(found)


def parse_assignments(
    payload: Any, sentence_count: int
) -> dict[int, tuple[ObservationClass, float, str]]:
    """Read the model's answer, refusing what cannot be trusted.

    Three things are rejected rather than repaired: an index that names no
    sentence, a class this version does not have, and a confidence outside
    [0, 1]. Each would otherwise become a span pointing somewhere real with a
    meaning nothing here decided.
    """

    assignments: dict[int, tuple[ObservationClass, float, str]] = {}
    for entry in (payload or {}).get("spans", ()):
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= index < sentence_count:
            continue
        try:
            classification = ObservationClass(str(entry.get("classification", "")))
        except ValueError:
            # A class this version does not have. The model read something we
            # cannot route, and the nearest match would file it confidently in
            # the wrong tier.
            assignments[index] = (
                ObservationClass.UNCLASSIFIED,
                0.0,
                f"the model named an unknown class {entry.get('classification')!r}",
            )
            continue
        try:
            confidence = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if not 0.0 <= confidence <= 1.0:
            confidence = 0.0
        assignments[index] = (
            classification,
            confidence,
            str(entry.get("rationale", "") or "classified by meaning"),
        )
    return assignments
