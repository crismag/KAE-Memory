"""Lexical matching — retrieval that does not depend on an embedding model.

Vector search answers "what is this about". It cannot answer "which statements
contain this word", and on a hash-derived test embedder it cannot answer either.
A query for ``approval`` should reach *A submitter cannot approve their own
report* without a model being involved at all, because the word family is right
there in the text.

The stemmer here is deliberately small. It is not linguistics: it exists so that
``approval``, ``approve``, ``approved``, ``approver``, and ``approving`` collapse
to one key. Suffix stripping is capped by :data:`_MIN_STEM` so short words are
left alone, and the aggressive Latinate suffixes that a full Porter stemmer
would strip are omitted — over-stemming silently widens recall, which is harder
to notice than missing a rare inflection.
"""

import re
from dataclasses import dataclass

MIN_COVERAGE = 0.5
"""The share of a query's terms a text must contain to count as a result.

The lexical counterpart to :data:`~kae_memory.domain.chunks.MAX_DISTANCE`, and
it exists for the same reason. Without it, "report authorization and publication
control" returns every statement containing the word "report" — which in a
reporting project is all of them — because one common term out of four is enough
to rank. Matching a single incidental word is not answering the query.

Single-term queries are unaffected: their only match scores 1.0.
"""

_MIN_STEM = 4
"""Never strip a suffix that would leave a stub shorter than this.

``final`` keeps its ``al`` because ``fin`` is not the same concept. ``approval``
loses its ``al`` because ``approv`` still is.
"""

_SUFFIXES = (
    "ingly",
    "edly",
    "ing",
    "ment",
    "ness",
    "es",
    "ed",
    "er",
    "or",
    "al",
    "ly",
    "s",
)
"""Ordered longest-first so ``approves`` strips ``es`` rather than ``s``.

Notably absent: ``ation`` and friends. Stripping those turns ``publication``
into ``public``, which would quietly merge two unrelated ideas.
"""

_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "must",
        "not",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "there",
        "they",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "with",
    }
)
"""Words that match everything and therefore rank nothing."""

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class LexicalMatch:
    """How well one text answered a query, and which terms carried it."""

    score: float
    matched_terms: tuple[str, ...]

    @property
    def matched(self) -> bool:
        return bool(self.matched_terms)


def stem(word: str) -> str:
    """Reduce ``word`` to the key its inflections share.

    One pass, not repeated to a fixed point: ``approvals`` is rare enough that
    chasing it is not worth the extra over-stemming risk everywhere else.
    """

    lowered = word.lower()
    for suffix in _SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= _MIN_STEM:
            return lowered[: -len(suffix)]
    # A bare trailing ``e`` is what separates ``approve`` from ``approv``.
    if len(lowered) > _MIN_STEM and lowered.endswith("e"):
        return lowered[:-1]
    return lowered


def terms(query: str) -> tuple[str, ...]:
    """Return the distinct, ordered stems a query is actually asking about.

    Stopwords are dropped before stemming. If a query is *only* stopwords the
    result is empty, and a caller must treat that as "no lexical signal" rather
    than as "matches everything".
    """

    seen: list[str] = []
    for word in _WORD.findall(query.lower()):
        if word in _STOPWORDS:
            continue
        key = stem(word)
        if key and key not in seen:
            seen.append(key)
    return tuple(seen)


def match(query_terms: tuple[str, ...], text: str) -> LexicalMatch:
    """Score ``text`` against already-stemmed ``query_terms``.

    The score is term coverage: the share of distinct query stems the text
    contains. Coverage rather than frequency, because a statement that mentions
    every term once is a better answer than one that repeats a single term.
    """

    if not query_terms:
        return LexicalMatch(score=0.0, matched_terms=())

    present = {stem(word) for word in _WORD.findall(text.lower())}
    hit = tuple(term for term in query_terms if term in present)
    return LexicalMatch(score=len(hit) / len(query_terms), matched_terms=hit)


__all__ = ["LexicalMatch", "match", "stem", "terms"]
