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
from collections.abc import Sequence
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


NEAR_DUPLICATE_SIMILARITY = 0.85
"""How alike two statements must be before they are worth a human's attention.

High on purpose. A false positive costs someone a decision they did not need to
make; a false negative leaves a duplicate that readiness will count twice. The
first is cheap to dismiss, so the threshold errs toward silence.
"""

_NEGATIONS = frozenset({"cannot", "never", "no", "not"})
"""Polarity markers, held apart from content.

Two statements differing only by one of these are not near-duplicates — they
are a contradiction, and reporting them as the same thing would file a conflict
under housekeeping.
"""


def content_words(text: str) -> frozenset[str]:
    """Return the stemmed, meaning-bearing words of ``text``.

    Stopwords and negations are excluded. Negations are compared separately by
    :func:`is_negated` so that polarity is a distinct signal rather than one
    token's worth of overlap.
    """

    return frozenset(
        stem(word)
        for word in _WORD.findall(text.lower())
        if word not in _STOPWORDS and word not in _NEGATIONS
    )


def is_negated(text: str) -> bool:
    """Return whether ``text`` carries a negation marker."""

    lowered = f" {text.lower()} "
    return any(f" {token} " in lowered for token in _NEGATIONS)


def similarity(first: str, second: str) -> float:
    """Return how much meaning two statements share, from 0.0 to 1.0.

    Jaccard overlap of content stems. Deliberately blind to word order, because
    "only an approver may approve" and "may approve only an approver" say the
    same thing badly, and neither is a second fact.
    """

    left, right = content_words(first), content_words(second)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def is_near_duplicate(
    first: str, second: str, threshold: float = NEAR_DUPLICATE_SIMILARITY
) -> bool:
    """Return whether two statements say the same thing with the same polarity.

    Polarity is checked first. Without it, a rule and its exact negation score
    near-identical overlap and would be reported as duplicates of each other.
    """

    return is_negated(first) == is_negated(second) and similarity(first, second) >= threshold


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


#: How alike two statements must be to sit in one group on a review surface.
#:
#: **Lower than `NEAR_DUPLICATE_SIMILARITY` on purpose.** A duplicate is a claim
#: about sameness and deserves a high bar; a *group* is a claim about
#: adjacency — "read these together" — and the cost of being slightly wrong is
#: that somebody reads two related statements at once, which is what they were
#: going to do anyway.
#:
#: **Measured rather than chosen.** Jaccard over content stems is harsh on
#: paraphrase, because synonyms share no stems at all — "sent" and "go out" are
#: unrelated to it. Against real statements of the kind this product extracts:
#:
#:     0.83  "Only a supervisor may sign off completed work."
#:           "Completed work is signed off by a supervisor."
#:     0.78  "An invoice must be sent within three days of a job finishing."
#:           "Invoices are sent within three working days after a job finishes."
#:     0.50  "Invoices are sent within three days of a job finishing."
#:           "Invoices go out three days after a job finishes."
#:     0.43  "Invoices are not sent before a job finishes."
#:           "Invoices are not issued until the job has finished."
#:     0.27  "Invoices must be sent within three days and carry a client reference."
#:           "Every invoice carries a client reference for reconciliation."
#:     0.00  an invoicing rule and an approval rule
#:
#: **Recalibrated against real statements after deploying** (`D-16`). Those
#: figures came from statements written to illustrate the problem. Real
#: extracted ones are longer, hedged and full of qualifying clauses, so the same
#: meaning shares a smaller fraction of its words — on the first live project,
#: 32 statements and 496 pairs produced a **maximum similarity of 0.33** and the
#: threshold grouped nothing at all.
#:
#: **The threshold is unchanged, and that is the finding.** The obvious response
#: was to lower it until real statements grouped. Measured in full, the numbers
#: refuse:
#:
#:     0.300  one question asked twice
#:            "What is 'that repository' — which repository is being referred
#:             to, and what does it contain?"
#:            "What repository is being referred to, and where is it located or
#:             how would KAE access it?"
#:
#:     0.286  two unrelated statements
#:            "What is the project or system being worked on?"
#:            "The system must be able to read reference works."
#:
#: **Fourteen thousandths** separate a true pair from a false one. That is not a
#: threshold to tune; it is a measure that cannot tell them apart, and any value
#: chosen between them would be fitted to two examples and wrong on the third.
#:
#: Jaccard's weakness is length: it divides by the *union*, so the same meaning
#: expressed at different lengths scores low, and a short statement can never
#: score high against a long one. An overlap coefficient — dividing by the
#: smaller set — separates the same two pairs by 0.10 rather than 0.014, and
#: brings its own failure: the two-word actor "Qualified supervisor" scores
#: **1.00** against every rule that mentions it.
#:
#: So the real work is a measure that handles both, and it is `GROUP-MEASURE`
#: rather than something changed while unattended — it decides how a person
#: reads their own project.
#:
#: Until then this groups genuine near-duplicates and finds nothing on the live
#: project, which is a true answer rather than a useful one. The surface renders
#: nothing rather than something false.
#:
#: And the number that makes the polarity guard non-negotiable: **a rule and its
#: exact negation score `1.00`.** Similarity alone would group the two
#: statements a person most needs to see apart.
GROUPING_SIMILARITY = 0.42


def group_related(
    statements: Sequence[tuple[str, str]], threshold: float = GROUPING_SIMILARITY
) -> tuple[tuple[str, ...], ...]:
    """Cluster statements that say adjacent things, by id.

    `PPA-15`: *"'I don't know how to organise my project' becomes 'KAE generated
    70 things I don't know how to organise'."* Seventy flat statements is the
    original problem restated in the product's own words, and grouping is what
    turns it into a dozen readings.

    **Grouping is not merging.** Every statement stays whole, stays visible, and
    stays separately confirmable — so this decides nothing on the project's
    behalf, which is why it can ship while `EM-3`'s ruling on unattended merging
    stays open.

    Single-link clustering: A groups with C when both are close to B, even if A
    and C are not close to each other. That is the right shape for *"read these
    together"* and the wrong shape for *"these are the same"* — which is the
    other reason this is not a duplicate check.

    Polarity is respected through `is_near_duplicate`'s own rule at the pair
    level: a rule and its exact negation share almost every content word, and
    putting them in one group would suggest agreement where there is a conflict.

    Returns groups of two or more, largest first, each in input order. A
    statement in no group is absent rather than a group of one — a caller
    rendering "groups" should not have to filter out singletons to find the ones
    that mean something.
    """

    parent: dict[str, str] = {identifier: identifier for identifier, _ in statements}

    def root(identifier: str) -> str:
        while parent[identifier] != identifier:
            parent[identifier] = parent[parent[identifier]]
            identifier = parent[identifier]
        return identifier

    for index, (left_id, left_text) in enumerate(statements):
        for right_id, right_text in statements[index + 1 :]:
            if is_negated(left_text) != is_negated(right_text):
                # Opposite polarity. Nearly every content word is shared, and
                # grouping them would read as agreement about a conflict.
                continue
            if similarity(left_text, right_text) >= threshold:
                parent[root(right_id)] = root(left_id)

    clustered: dict[str, list[str]] = {}
    for identifier, _ in statements:
        clustered.setdefault(root(identifier), []).append(identifier)

    groups = [tuple(members) for members in clustered.values() if len(members) > 1]
    groups.sort(key=len, reverse=True)
    return tuple(groups)


__all__ = [
    "GROUPING_SIMILARITY",
    "NEAR_DUPLICATE_SIMILARITY",
    "LexicalMatch",
    "content_words",
    "group_related",
    "is_near_duplicate",
    "is_negated",
    "match",
    "similarity",
    "stem",
    "terms",
]
