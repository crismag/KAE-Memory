"""Lexical retrieval, and the relevance cutoff on the vector path.

The defect these cover: a query for ``approval`` returned every statement in the
project, ordered by a hash. Nearest-neighbour with only a ``LIMIT`` cannot
exclude anything, so the corpus came back whole however the query was worded.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import DeterministicEmbeddingAdapter
from kae_memory.application import MemoryService, RetrievalService, WriteKnowledgeRequest
from kae_memory.application.retrieval_service import SearchMode
from kae_memory.domain.chunks import strip_metadata_prefix
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.lexical import match, stem, terms
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project

MOMENT = datetime(2026, 8, 2, tzinfo=UTC)

APPROVAL_CORPUS = [
    ("requirement", "A report cannot be published before it is approved."),
    ("requirement", "Only an authorised approver may approve a report."),
    ("rule", "A submitter cannot approve their own report."),
    ("rule", "Editing an approved report invalidates the prior approval."),
    (
        "goal",
        "Every published report has an identifiable approver, approval time, and approved version.",
    ),
    ("constraint", "Identity must come from the existing organisational directory."),
    (
        "assumption",
        "Roughly 25 ministries submit monthly, so throughput is not a design constraint.",
    ),
    ("actor", "Ministry leaders submit monthly reports."),
    ("actor", "Pastors and administrators read published reports."),
    ("requirement", "A draft report remains editable by its author until it is submitted."),
]
"""The Ministry Reporting statements the original search returned in full."""


def _seed(
    service: MemoryService, texts: list[tuple[str, str]], key: str
) -> tuple[Project, tuple[KnowledgeItem, ...]]:
    project = service.create_project("Ministry Reporting", key=key)
    run = service.start_run(project.id, AgentRole.REQUIREMENTS, "seed-lexical")
    items = service.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(kind=kind, content=content, source="seed")
            for kind, content in texts
        ],
    )
    for item in items:
        service.confirm_knowledge(item.id)
    return project, items


def _prepare(factory: sessionmaker[Session], key: str) -> tuple[Project, RetrievalService]:
    memory = MemoryService(factory)
    retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
    project, items = _seed(memory, APPROVAL_CORPUS, key)
    for item in items:
        retrieval.chunk_knowledge(item, project.name)
    retrieval.embed_pending(project.id)
    return project, retrieval


def _bodies(hits: tuple[Any, ...]) -> set[str]:
    return {strip_metadata_prefix(hit.text) for hit in hits}


class TestLexicalSearch:
    def test_a_term_query_returns_only_the_word_family(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The regression case: 'approval' must not return the whole project."""

        project, retrieval = _prepare(factory, "lex-family")

        hits = retrieval.find(project.id, "approval", limit=20)

        assert _bodies(hits) == {
            "A report cannot be published before it is approved.",
            "Only an authorised approver may approve a report.",
            "A submitter cannot approve their own report.",
            "Editing an approved report invalidates the prior approval.",
            "Every published report has an identifiable approver, approval time, "
            "and approved version.",
        }

    def test_unrelated_statements_are_excluded_not_merely_ranked_last(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Exclusion is the whole point. Ranking alone still returns the corpus."""

        project, retrieval = _prepare(factory, "lex-exclude")

        bodies = _bodies(retrieval.find(project.id, "approval", limit=20))

        assert "Identity must come from the existing organisational directory." not in bodies
        assert not any("25 ministries" in body for body in bodies)
        assert "Ministry leaders submit monthly reports." not in bodies

    def test_a_lexical_hit_reports_no_distance(self, factory: sessionmaker[Session]) -> None:
        """No vector was consulted, so there is no distance to report."""

        project, retrieval = _prepare(factory, "lex-nodistance")

        hits = retrieval.find(project.id, "approval")

        assert hits
        assert all(hit.distance is None for hit in hits)
        assert all(hit.mode is SearchMode.LEXICAL for hit in hits)
        assert all("approv" in hit.matched_terms for hit in hits)

    def test_coverage_ranks_statements_naming_more_of_the_query(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A statement naming every term beats one naming a single term."""

        project, retrieval = _prepare(factory, "lex-coverage")

        hits = retrieval.find(project.id, "approver identifiable", limit=20)

        assert hits[0].coverage == 1.0
        assert "identifiable approver" in strip_metadata_prefix(hits[0].text)
        coverages = [hit.coverage for hit in hits]
        assert all(coverage is not None for coverage in coverages)
        assert coverages == sorted(coverages, reverse=True)  # type: ignore[type-var]

    def test_the_metadata_prefix_cannot_match(self, factory: sessionmaker[Session]) -> None:
        """Every chunk contains 'Project:', so the prefix would match everything."""

        project, retrieval = _prepare(factory, "lex-prefix")

        assert retrieval.find(project.id, "project", limit=20) == ()

    def test_a_query_of_only_stopwords_matches_nothing(
        self, factory: sessionmaker[Session]
    ) -> None:
        """No signal is not the same as matching everything."""

        project, retrieval = _prepare(factory, "lex-stopwords")

        assert retrieval.find(project.id, "the and of", limit=20) == ()

    def test_one_incidental_word_does_not_carry_a_result(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A conceptual query is lexical search's honest failure case.

        Every statement here contains "report", so without a coverage floor this
        four-term query returns the corpus again — the original defect, reached
        by a different route.
        """

        project, retrieval = _prepare(factory, "lex-coverage-floor")

        hits = retrieval.find(project.id, "report authorization and publication control", limit=20)

        assert hits == ()

    def test_a_partial_match_survives_when_it_covers_enough(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The floor excludes incidental matches, not genuinely partial ones."""

        project, retrieval = _prepare(factory, "lex-partial")

        hits = retrieval.find(project.id, "approval workflow", limit=20)

        assert len(hits) == 5
        assert all(hit.coverage == 0.5 for hit in hits)

    def test_kind_filters_compose_with_term_matching(self, factory: sessionmaker[Session]) -> None:
        project, retrieval = _prepare(factory, "lex-kinds")

        hits = retrieval.find(project.id, "approval", kinds=[KnowledgeKind.RULE], limit=20)

        assert hits
        assert {hit.kind for hit in hits} == {KnowledgeKind.RULE}

    def test_lexical_search_is_scoped_to_one_project(self, factory: sessionmaker[Session]) -> None:
        mine, retrieval = _prepare(factory, "lex-scope-mine")
        theirs, _ = _prepare(factory, "lex-scope-theirs")

        hits = retrieval.find(mine.id, "approval", limit=20)

        assert hits
        assert all(hit.knowledge_id for hit in hits)
        theirs_hits = retrieval.find(theirs.id, "approval", limit=20)
        assert {hit.knowledge_id for hit in hits}.isdisjoint(
            {hit.knowledge_id for hit in theirs_hits}
        )

    def test_knowledge_is_findable_before_it_is_embedded(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Words are readable the moment a chunk is stored.

        Unlike the vector path, lexical retrieval has no reason to wait for an
        embedding — which means a pending or failed re-embed costs nothing here.
        """

        memory = MemoryService(factory)
        retrieval = RetrievalService(factory, DeterministicEmbeddingAdapter())
        project, items = _seed(
            memory, [("rule", "A submitter cannot approve their own report.")], "lex-unembedded"
        )
        retrieval.chunk_knowledge(items[0], project.name)

        assert retrieval.search(project.id, "approval") == ()
        assert retrieval.find(project.id, "approval")


class TestRelevanceThreshold:
    def test_an_unrelated_vector_query_returns_nothing(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Hash-derived vectors sit near orthogonal, so nothing is close enough.

        This is the corrected behaviour. Before the cutoff existed, this same
        query returned every embedded chunk in the project.
        """

        project, retrieval = _prepare(factory, "vec-threshold")

        assert retrieval.search(project.id, "approval", limit=20) == ()

    def test_removing_the_cutoff_restores_the_old_listing(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Documents what the cutoff is actually filtering."""

        project, retrieval = _prepare(factory, "vec-nocutoff")

        hits = retrieval.search(project.id, "approval", limit=20, max_distance=None)

        assert len(hits) == len(APPROVAL_CORPUS)

    def test_an_exact_match_still_survives_the_cutoff(self, factory: sessionmaker[Session]) -> None:
        """The threshold must not break retrieval that genuinely is close."""

        project, retrieval = _prepare(factory, "vec-exact")
        stored = retrieval.search(project.id, "approval", limit=20, max_distance=None)

        hits = retrieval.search(project.id, stored[0].text, limit=5)

        assert hits
        assert hits[0].chunk_id == stored[0].chunk_id


class TestStemming:
    def test_the_approval_word_family_shares_one_stem(self) -> None:
        assert {stem(word) for word in ("approval", "approve", "approved", "approver")} == {
            "approv"
        }
        assert stem("approving") == "approv"

    def test_short_words_are_left_alone(self) -> None:
        """Over-stemming widens recall silently, which is worse than missing one."""

        assert stem("final") == "final"
        assert stem("data") == "data"

    def test_latinate_suffixes_are_not_stripped(self) -> None:
        """'publication' must not collapse into 'public'."""

        assert stem("publication") == "publication"

    def test_stopwords_are_dropped_before_stemming(self) -> None:
        assert terms("the approval of a report") == ("approv", "report")

    def test_coverage_is_the_share_of_query_terms_present(self) -> None:
        assert match(("approv", "report"), "An approved report.").score == 1.0
        assert match(("approv", "report"), "A report.").score == 0.5
        assert match(("approv", "report"), "Nothing relevant.").matched is False
