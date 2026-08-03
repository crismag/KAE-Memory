"""The retrieval evaluation set — real queries against real project knowledge.

Ground truth is written against knowledge that exists in the development corpus,
not invented fixtures, because a paraphrase test on synthetic text proves the
embedder can match text you wrote to text you wrote.

Judgements are manual and deliberately loose. With this many queries a
mathematically perfect ground truth would be false precision; what matters is
whether a reader would accept the answer, and every entry records what would
make it unacceptable as well as what would make it right.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class QueryKind(StrEnum):
    """Why a query is in the set.

    The categories test different things. Exact terminology is what lexical
    search is for; paraphrase is the whole reason to buy an embedding model;
    weak queries test whether the system knows when it does not know.
    """

    EXACT = "exact_terminology"
    PARAPHRASE = "paraphrase"
    SYNTHESIS = "cross_document"
    ISOLATION = "project_isolation"
    WEAK = "weak_or_unrelated"


class Expectation(StrEnum):
    """Which retrieval mode should win a query, if either should."""

    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    EITHER = "either"
    NEITHER = "neither"


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One query, and what an acceptable answer looks like."""

    query: str
    kind: QueryKind
    expects: Expectation
    project: str | None = None
    relevant: tuple[str, ...] = field(default_factory=tuple)
    """Substrings identifying acceptable statements. Any one is a hit."""
    unacceptable: tuple[str, ...] = field(default_factory=tuple)
    """Substrings that must not rank first. A wrong confident answer."""
    why: str = ""


MINISTRY = "Ministry Reporting"
KAE = "KAE-Memory"

CASES: tuple[EvalCase, ...] = (
    # -- exact terminology: lexical territory ------------------------------
    EvalCase(
        query="approver",
        kind=QueryKind.EXACT,
        expects=Expectation.LEXICAL,
        project=MINISTRY,
        relevant=("authorised approver", "identifiable approver"),
        why="A rare exact term. Lexical must stay competitive here.",
    ),
    EvalCase(
        query="organisational directory",
        kind=QueryKind.EXACT,
        expects=Expectation.EITHER,
        project=MINISTRY,
        relevant=("organisational directory",),
        why="A distinctive phrase appearing in exactly one statement.",
    ),
    EvalCase(
        query="human-in-the-loop",
        kind=QueryKind.EXACT,
        expects=Expectation.EITHER,
        project=KAE,
        relevant=("human-in-the-loop",),
        why="Hyphenated term; tests tokenisation as much as retrieval.",
    ),
    EvalCase(
        query="blueprint",
        kind=QueryKind.EXACT,
        expects=Expectation.EITHER,
        project=KAE,
        relevant=("blueprint",),
        why="Single distinctive noun.",
    ),
    # -- paraphrase: the reason to buy an embedding model -------------------
    EvalCase(
        query="Who is allowed to sign off a document before it goes out?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=MINISTRY,
        relevant=("authorised approver", "cannot be published before"),
        unacceptable=("Roughly 25 ministries",),
        why="No shared wording with the target. Lexical cannot answer this.",
    ),
    EvalCase(
        query="Can somebody rubber-stamp their own submission?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=MINISTRY,
        relevant=("submitter cannot approve their own",),
        why="Colloquial phrasing of a recorded rule.",
    ),
    EvalCase(
        query="What happens to sign-off if the document is changed afterwards?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=MINISTRY,
        relevant=("invalidates the prior approval",),
        why="Tests whether the consequence relation is captured.",
    ),
    EvalCase(
        query="How do we stop losing context between AI sessions?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=KAE,
        relevant=("long-term engineering collaborators", "across sessions"),
        why="The product's central claim, asked in the user's words.",
    ),
    EvalCase(
        query="Is anything ever deleted when it turns out to be wrong?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=KAE,
        relevant=("preserve history", "corrections preserve history"),
        why="Negative phrasing of a stated guarantee.",
    ),
    EvalCase(
        query="Can the machine decide something is true on its own?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=KAE,
        relevant=("human-in-the-loop", "requires human confirmation", "Human owners retain"),
        why="Authority model, asked without any of its vocabulary.",
    ),
    EvalCase(
        query="Who would actually use this product?",
        kind=QueryKind.PARAPHRASE,
        expects=Expectation.SEMANTIC,
        project=KAE,
        relevant=("Intended users are", "MVP targets"),
        why="Actor recall from a natural question.",
    ),
    # -- cross-document synthesis ------------------------------------------
    EvalCase(
        query="What is still undecided about the reporting workflow?",
        kind=QueryKind.SYNTHESIS,
        expects=Expectation.SEMANTIC,
        project=MINISTRY,
        relevant=("Which role holds approval authority", "How is a published report corrected"),
        why="Two open questions should both be reachable.",
    ),
    EvalCase(
        query="What limits the scope of the first release?",
        kind=QueryKind.SYNTHESIS,
        expects=Expectation.SEMANTIC,
        project=KAE,
        relevant=("not part of the first release", "bounded task"),
        why="Several constraints contribute; one should not dominate.",
    ),
    EvalCase(
        query="What does a user get at the end?",
        kind=QueryKind.SYNTHESIS,
        expects=Expectation.SEMANTIC,
        project=KAE,
        relevant=("leaves with validated requirements", "blueprint is what the user takes away"),
        why="Answer is supported by more than one statement.",
    ),
    # -- project isolation --------------------------------------------------
    EvalCase(
        query="reports",
        kind=QueryKind.ISOLATION,
        expects=Expectation.EITHER,
        project=MINISTRY,
        relevant=("report",),
        unacceptable=("durable shared-memory foundation",),
        why="'reports' appears in more than one project. Scoping must hold.",
    ),
    EvalCase(
        query="requirements",
        kind=QueryKind.ISOLATION,
        expects=Expectation.EITHER,
        project=KAE,
        relevant=("validated requirements", "requirements validation"),
        unacceptable=("Ministry leaders",),
        why="Same term, different projects.",
    ),
    # -- weak, ambiguous, unrelated ----------------------------------------
    EvalCase(
        query="Kubernetes ingress controller",
        kind=QueryKind.WEAK,
        expects=Expectation.NEITHER,
        project=MINISTRY,
        why="Absent from the corpus. Must not return a confident answer.",
    ),
    EvalCase(
        query="quarterly revenue forecast",
        kind=QueryKind.WEAK,
        expects=Expectation.NEITHER,
        project=KAE,
        why="Plausible business language, no project relevance.",
    ),
    EvalCase(
        query="the",
        kind=QueryKind.WEAK,
        expects=Expectation.NEITHER,
        project=MINISTRY,
        why="Pure stopword. Must not match everything.",
    ),
    EvalCase(
        query="thanks, that's helpful",
        kind=QueryKind.WEAK,
        expects=Expectation.NEITHER,
        project=KAE,
        why="Conversational filler with no informational content.",
    ),
)


def by_kind(kind: QueryKind) -> tuple[EvalCase, ...]:
    """Return the cases in one category."""

    return tuple(case for case in CASES if case.kind is kind)


__all__ = ["CASES", "EvalCase", "Expectation", "QueryKind", "by_kind"]
