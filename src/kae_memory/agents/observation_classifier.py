"""Reading a submitted observation without a model (T24.1, T24.2).

Two stages, kept apart because they fail differently.

**Stage 1 is deterministic.** Dates, milestone and target ids, status words,
action verbs, URLs, versions. It finds *fields* and decides nothing. Being
deterministic, it is testable to the character, and it works when no model is
reachable.

**Stage 2 assigns a class to a span.** The adapter here is rule-based rather
than semantic, and says so: `semantic_classification` is false for it, the same
way search reports a hash-derived embedder rather than implying it ranks by
meaning. A rule-based classifier that presented itself as a semantic one would
be believed exactly as far as its worst guess.

Both stages degrade rather than block. If classification cannot run, the
observation is still recorded — evidence capture must not depend on anything
being reachable.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from kae_memory.domain.observation import (
    ClassifiedSpan,
    ObservationClass,
    Span,
)

CLASSIFIER_NAME = "kae-observation-classifier"
CLASSIFIER_VERSION = "1.0"

_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")

_MILESTONE = re.compile(r"\bM(\d{1,3})\b")
_TARGET = re.compile(r"\bT(\d{1,3})(?:\.\d{1,2})?\b")
_DECISION = re.compile(r"\b(?:OQ|ADR|FR|NFR)-(\d{1,4})\b", re.I)
_PR = re.compile(r"(?:\bPR[ #-]?|#)(\d{1,6})\b", re.I)
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NAMED_DATE = re.compile(
    r"\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
    r"(?:\s+\d{4})?)\b",
    re.I,
)
_RELATIVE_DATE = re.compile(
    r"\b(today|tomorrow|yesterday|tonight|this week|next week|last week|"
    r"end of (?:the )?(?:day|week|month|quarter)|by (?:monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday))\b",
    re.I,
)
_VERSION = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?)\b")
_URL = re.compile(r"\bhttps?://\S+", re.I)
_ENVIRONMENT = re.compile(r"\b(production|staging|development|local|sandbox|prod|dev)\b", re.I)

_STATUS_WORDS = {
    "complete": "complete",
    "completed": "complete",
    "done": "complete",
    "finished": "complete",
    "shipped": "complete",
    "merged": "complete",
    "in progress": "in_progress",
    "started": "in_progress",
    "underway": "in_progress",
    "blocked": "blocked",
    "stuck": "blocked",
    "waiting": "blocked",
    "passed": "passed",
    "passing": "passed",
    "green": "passed",
    "failed": "failed",
    "failing": "failed",
    "broken": "failed",
    "red": "failed",
}

_ACTION_VERBS = (
    "add",
    "build",
    "check",
    "deploy",
    "fix",
    "implement",
    "migrate",
    "refactor",
    "release",
    "remove",
    "review",
    "run",
    "test",
    "update",
    "verify",
    "write",
)


def extract_fields(text: str) -> dict[str, Any]:
    """Return the structured values a span carries, without judging it (T24.1).

    Decides nothing. A date is reported as a date, not as a deadline: which of
    historical, effective, deadline, target, and check-in a bare date means is
    not recoverable from the date itself, and guessing is how a note about last
    week's release becomes next week's commitment.
    """

    found: dict[str, Any] = {}

    milestones = [f"M{match.group(1)}" for match in _MILESTONE.finditer(text)]
    targets = [match.group(0).upper() for match in _TARGET.finditer(text)]
    decisions = [match.group(0).upper() for match in _DECISION.finditer(text)]
    prs = [match.group(1) for match in _PR.finditer(text)]
    dates = (
        [match.group(1) for match in _ISO_DATE.finditer(text)]
        + [match.group(1) for match in _NAMED_DATE.finditer(text)]
        + [match.group(1).lower() for match in _RELATIVE_DATE.finditer(text)]
    )
    urls = _URL.findall(text)
    environments = sorted({match.group(1).lower() for match in _ENVIRONMENT.finditer(text)})
    versions = [
        match.group(1) for match in _VERSION.finditer(text) if not _ISO_DATE.search(match.group(0))
    ]

    lowered = text.lower()
    statuses = sorted(
        {normal for word, normal in _STATUS_WORDS.items() if re.search(rf"\b{word}\b", lowered)}
    )
    actions = sorted(
        {verb for verb in _ACTION_VERBS if re.search(rf"\b{verb}(?:s|ed|ing)?\b", lowered)}
    )

    for name, values in (
        ("milestones", milestones),
        ("targets", targets),
        ("decisions", decisions),
        ("pull_requests", prs),
        ("dates", dates),
        ("urls", urls),
        ("environments", environments),
        ("versions", versions),
        ("statuses", statuses),
        ("actions", actions),
    ):
        if values:
            # Order-preserving dedup: the first mention is the one a reviewer
            # will look for in the text.
            found[name] = list(dict.fromkeys(values))

    if "dates" in found:
        # Stated explicitly rather than implied by the presence of a date.
        # `unknown` is a real answer here and a far better one than a default.
        found["date_role"] = "unknown"
    return found


class ObservationClassifier(Protocol):
    """Assign classes to the spans of one observation."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def semantic(self) -> bool:
        """Whether classification is by meaning rather than by rule."""
        ...

    def classify(self, text: str) -> tuple[ClassifiedSpan, ...]: ...


_RULES: tuple[tuple[ObservationClass, float, tuple[str, ...]], ...] = (
    # Ordered: the first rule that matches a sentence wins, so the more
    # specific patterns are listed before the general ones. `milestone_status`
    # sits above `blocker` and `defect` for that reason — "M8 is blocked" names
    # a milestone and a status, and the generic `\bblocked\b` rule would
    # otherwise file it as an unattached blocker and lose the transition.
    (
        ObservationClass.PERSONAL_COMMENTARY,
        0.93,
        (
            r"\bto god be the glory\b",
            r"\bthank(?:s| you)\b",
            r"\bpraise\b",
            r"\b(?:i|we)(?:'m| am| feel)\s+(?:happy|glad|tired|excited|proud)\b",
            r"\bgood (?:morning|evening|night)\b",
        ),
    ),
    (
        ObservationClass.MILESTONE_STATUS,
        0.92,
        (
            r"\bM\d{1,3}\b.*\b(?:complete|completed|done|in progress|started|blocked)\b",
            r"\b(?:milestone|phase)\b.*\b(?:complete|completed|done|in progress|started)\b",
        ),
    ),
    (
        ObservationClass.TEST_RESULT,
        0.92,
        (
            r"\btests?\b.*\b(?:pass|passed|passing|fail|failed|failing|green|red)\b",
            r"\b(?:pass|passed|failed|failing)\b.*\btests?\b",
            r"\bsuite\b.*\b(?:pass|fail)",
            r"\bsuccess on\b.*\btest\b",
        ),
    ),
    (
        ObservationClass.DEFECT,
        0.91,
        (r"\bbug\b", r"\bdefect\b", r"\bregression\b", r"\bcrash(?:es|ed|ing)?\b"),
    ),
    (
        ObservationClass.BLOCKER,
        0.91,
        (r"\bblocked\b", r"\bblocker\b", r"\bcannot proceed\b", r"\bwaiting on\b"),
    ),
    (
        ObservationClass.DEADLINE,
        0.88,
        (r"\bdue\b", r"\bdeadline\b", r"\bby (?:friday|monday|end of)\b"),
    ),
    (
        ObservationClass.CHECK_IN,
        0.86,
        (r"\bcheck ?in\b", r"\bfollow up\b", r"\bremind\b", r"\bstand ?up\b"),
    ),
    (
        ObservationClass.OPEN_QUESTION,
        0.90,
        (r"\?\s*$", r"\bnot (?:yet )?decided\b", r"\bundecided\b", r"\bwe need to decide\b"),
    ),
    (
        ObservationClass.DECISION,
        0.90,
        (
            r"\bwe (?:have )?decided\b",
            r"\bdecision\b",
            r"\bwe will use\b",
            r"\bagreed (?:to|that|on)\b",
            r"\bADR-\d+\b",
        ),
    ),
    (
        ObservationClass.CONSTRAINT,
        0.88,
        (r"\bmust not\b", r"\bcannot\b", r"\bis limited to\b", r"\bno more than\b"),
    ),
    (
        ObservationClass.ACCEPTANCE_CRITERION,
        0.87,
        (r"\bacceptance criteri", r"\bgiven\b.*\bwhen\b.*\bthen\b"),
    ),
    (
        ObservationClass.QUALITY_ATTRIBUTE,
        0.86,
        (
            r"\b(?:latency|throughput|availability|uptime|performance)\b",
            r"\bwithin \d+\s*(?:ms|seconds?|minutes?)\b",
        ),
    ),
    (
        ObservationClass.INTEGRATION,
        0.86,
        (r"\bintegrat(?:e|es|ion)\b", r"\bwebhook\b", r"\bAPI\b.*\b(?:call|endpoint)\b"),
    ),
    (
        ObservationClass.ASSUMPTION,
        0.86,
        (r"\bassum(?:e|es|ing|ption)\b", r"\bpresumably\b", r"\bwe expect\b"),
    ),
    (
        ObservationClass.SCOPE,
        0.86,
        (r"\bout of scope\b", r"\bin scope\b", r"\bnot part of\b", r"\bexcluded from\b"),
    ),
    (
        ObservationClass.REQUIREMENT,
        0.88,
        (r"\bmust\b", r"\bshall\b", r"\bis required to\b", r"\bhas to be\b", r"\bshould\b"),
    ),
    (
        ObservationClass.RISK,
        0.85,
        (r"\brisk\b", r"\bmight fail\b", r"\bcould break\b", r"\bconcern(?:ed|s)? that\b"),
    ),
    (
        ObservationClass.OWNERSHIP_UPDATE,
        0.85,
        (r"\b(?:owns|owner|assigned to|taking over)\b",),
    ),
    (
        ObservationClass.TASK,
        0.82,
        (r"\b(?:i|we)(?:'ll| will)\b", r"\bneed to\b", r"\bnext step\b", r"\btodo\b"),
    ),
    (
        ObservationClass.PROGRESS_UPDATE,
        0.80,
        (r"\bmade progress\b", r"\bstill working\b", r"\bcontinu(?:e|ing)\b"),
    ),
    (
        ObservationClass.SESSION_NOTE,
        0.78,
        (r"\bbefore sleeping\b", r"\bwrapping up\b", r"\bfor now\b", r"\bnote to self\b"),
    ),
)


class DeterministicObservationClassifier:
    """Rule-based classification, honest about being rule-based (T24.2).

    Splits an observation into sentences and classifies each. One submission
    producing several differently-routed spans is the normal case, not an edge
    case: "tests passed, a few more before sleeping, to God be the glory" is
    one operational record and two pieces of evidence, and treating it as a
    single class would either file a prayer as a test result or discard the
    test result.

    A sentence matching no rule is `unclassified` at zero confidence, which
    routes it to a person rather than to a guess.
    """

    @property
    def name(self) -> str:
        return CLASSIFIER_NAME

    @property
    def version(self) -> str:
        return CLASSIFIER_VERSION

    @property
    def semantic(self) -> bool:
        """False, and it matters.

        Wording it does not recognise is invisible to it. A caller told this
        was semantic would read an `unclassified` span as "there was nothing
        there", rather than "this classifier does not know that phrasing".
        """

        return False

    def classify(self, text: str) -> tuple[ClassifiedSpan, ...]:
        spans: list[ClassifiedSpan] = []
        for match in _SENTENCE.finditer(text):
            raw = match.group(0)
            stripped = raw.strip()
            if not stripped:
                continue
            start = match.start() + (len(raw) - len(raw.lstrip()))
            span = Span(start, start + len(stripped))
            classification, confidence, rationale = _classify_sentence(stripped)
            spans.append(
                ClassifiedSpan(
                    classification=classification,
                    confidence=confidence,
                    span=span,
                    # Whitespace-normalised only. Anything more would be a
                    # rewrite, and the original is the record.
                    normalized_text=" ".join(stripped.split()),
                    fields=extract_fields(stripped),
                    rationale=rationale,
                )
            )
        return tuple(spans)


def _classify_sentence(sentence: str) -> tuple[ObservationClass, float, str]:
    """Return the first matching rule's class, confidence, and why."""

    for classification, confidence, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, sentence, re.I):
                return classification, confidence, f"matched {pattern!r}"
    return ObservationClass.UNCLASSIFIED, 0.0, "no rule matched"
