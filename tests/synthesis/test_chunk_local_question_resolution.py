"""`EPI-4`: the resolution rule, graded against `D-137`'s labels.

`D-138`. `D-137` wrote the ground truth first and deliberately wrote no rule,
because a rule and its own grading key written together always agree. So this
file grades rather than demonstrates: every assertion below is read off
`QUESTIONS_THE_CORPUS_ANSWERS` and its three companions, and the one labelled
question the rule does **not** resolve is pinned as a miss rather than removed
from the labels.

No database: `plan_reconciliation` is a pure function over snapshots, which is
where the rule lives and where it can be graded on all 180 rows at once.
"""

from __future__ import annotations

from kae_memory.domain.identifiers import KnowledgeItemId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.reconciliation import (
    EvidenceSnapshot,
    PairRelation,
    asserts_candidate,
    classify_pair,
    enumerated_candidates,
    is_candidate_resolution,
    plan_reconciliation,
    question_subject,
)
from kae_memory.domain.relationships import KnowledgeRelation
from kae_memory.domain.synthesis import EvidenceRole
from tests.synthesis import corpus as golden
from tests.synthesis.compute_lab import (
    CHUNK_LOCAL_QUESTION,
    OBSERVATIONS,
    QUESTIONS_ANSWERED_BY_A_CONTRADICTION,
    QUESTIONS_THE_CORPUS_ANSWERS,
    QUESTIONS_THE_CORPUS_NEVER_ANSWERS,
    UNGRADABLE_QUESTIONS,
)

CONSERVATIVE_BEHAVIOR_QUESTION = (
    "What constitutes 'conservative' receive/delete behavior — at-least-once delivery, "
    "explicit delete only after processing, or visibility timeout management?"
)
"""The one labelled-answered question this rule does not resolve. `D-138`."""

SYNTHESIZER_HOME_QUESTION = "Where should domain synthesizers live — Memory or CIE?"
"""The golden corpus's open architectural question — and the rule's false positive.

It enumerates two candidates and both are bare proper nouns, so `Memory` is
asserted whole by any sentence naming Memory. Subject overlap is what removes it,
and this corpus is the only place that could have shown it: the rule was read off
the other one.
"""


def _snapshots(observations: tuple[object, ...]) -> tuple[EvidenceSnapshot, ...]:
    return tuple(
        EvidenceSnapshot(
            KnowledgeItemId(f"item-{index:04d}"),
            item.kind.value,  # type: ignore[attr-defined]
            item.content,  # type: ignore[attr-defined]
            LifecycleState.PROPOSED,
        )
        for index, item in enumerate(observations)
    )


def _resolved_questions(observations: tuple[object, ...]) -> set[str]:
    snapshots = _snapshots(observations)
    by_id = {snapshot.id: snapshot for snapshot in snapshots}
    graph = plan_reconciliation(snapshots)
    return {
        by_id[edge.target_id].content
        for edge in graph.edges
        if edge.reason == "candidate_resolution"
    }


def _resolvers(observations: tuple[object, ...], question: str) -> set[str]:
    snapshots = _snapshots(observations)
    by_id = {snapshot.id: snapshot for snapshot in snapshots}
    graph = plan_reconciliation(snapshots)
    return {
        by_id[edge.source_id].content
        for edge in graph.edges
        if edge.reason == "candidate_resolution" and by_id[edge.target_id].content == question
    }


class TestGradedAgainstTheLabels:
    def test_two_of_the_three_answered_questions_resolve(self) -> None:
        resolved = _resolved_questions(OBSERVATIONS)
        answered = set(QUESTIONS_THE_CORPUS_ANSWERS)
        assert resolved <= answered
        assert resolved == answered - {CONSERVATIVE_BEHAVIOR_QUESTION}

    def test_every_resolver_is_a_statement_the_labels_name(self) -> None:
        for question in _resolved_questions(OBSERVATIONS):
            assert _resolvers(OBSERVATIONS, question) <= set(QUESTIONS_THE_CORPUS_ANSWERS[question])

    def test_no_question_the_corpus_never_answers_resolves(self) -> None:
        resolved = _resolved_questions(OBSERVATIONS)
        assert resolved & set(QUESTIONS_THE_CORPUS_NEVER_ANSWERS) == set()

    def test_the_profile_conflict_is_not_resolved_to_either_side(self) -> None:
        resolved = _resolved_questions(OBSERVATIONS)
        assert resolved & set(QUESTIONS_ANSWERED_BY_A_CONTRADICTION) == set()

    def test_the_ungradable_question_abstains(self) -> None:
        assert _resolved_questions(OBSERVATIONS) & set(UNGRADABLE_QUESTIONS) == set()


class TestTheNegativesAbstainByConstruction:
    """Not by scoring below something — the rule never looks at them.

    This is what makes the labels informative. A threshold tuned on this fixture
    would read as safe because every negative is refused one step earlier.
    """

    def test_no_unanswerable_question_enumerates_candidates(self) -> None:
        unresolvable = (
            set(QUESTIONS_THE_CORPUS_NEVER_ANSWERS)
            | set(QUESTIONS_ANSWERED_BY_A_CONTRADICTION)
            | set(UNGRADABLE_QUESTIONS)
        )
        for question in unresolvable:
            assert enumerated_candidates(question) == ()

    def test_every_answered_question_does_enumerate_candidates(self) -> None:
        for question in QUESTIONS_THE_CORPUS_ANSWERS:
            assert enumerated_candidates(question)


class TestTopicOverlapIsNotResolution:
    def test_the_conservative_behaviour_miss_is_two_candidate_words_of_three(self) -> None:
        """`D-138`: the miss is reported, not closed with a partial threshold."""

        nearest = (
            "On a transient dependency failure, let the visibility timeout expire so the "
            "message is retried automatically."
        )
        candidate = "visibility timeout management"
        wanted = question_subject(candidate)
        assert len(wanted) == 3
        assert len(wanted & question_subject(nearest)) == 2
        assert not asserts_candidate(nearest, candidate)

    def test_a_dead_letter_statement_does_not_resolve_a_dead_letter_question(self) -> None:
        question = _snapshot_for(
            "What threshold of delivery attempts triggers the redrive policy move to the "
            "dead-letter queue?",
            KnowledgeKind.UNKNOWN,
        )
        statement = _snapshot_for(
            "A poison message must be routed to the DLQ after reaching the max receive count.",
            KnowledgeKind.RULE,
        )
        assert not is_candidate_resolution(statement, question)
        assert classify_pair(statement, question) is PairRelation.NONE


class TestTheSubjectConditionIsLoadBearing:
    def test_the_golden_corpus_open_question_is_not_resolved(self) -> None:
        assert SYNTHESIZER_HOME_QUESTION in {item.content for item in golden.OBSERVATIONS}
        assert _resolved_questions(golden.OBSERVATIONS) == set()

    def test_its_candidate_is_asserted_whole_by_statements_about_something_else(self) -> None:
        """Without the subject condition this is exactly the false positive."""

        off_topic = "Memory must not become a blob warehouse."
        assert asserts_candidate(off_topic, "Memory")
        assert not question_subject(SYNTHESIZER_HOME_QUESTION) & question_subject(off_topic)

    def test_a_modal_verb_is_not_subject_matter(self) -> None:
        assert "should" not in " ".join(question_subject(SYNTHESIZER_HOME_QUESTION))


class TestTheEdgeIsTheOneTheGraphAlreadyHas:
    def test_a_resolved_question_takes_the_existing_role_and_relation(self) -> None:
        snapshots = _snapshots(OBSERVATIONS)
        by_id = {snapshot.id: snapshot for snapshot in snapshots}
        graph = plan_reconciliation(snapshots)
        edges = [edge for edge in graph.edges if edge.reason == "candidate_resolution"]
        assert edges
        assert all(edge.type is KnowledgeRelation.SUPERSEDES for edge in edges)
        roles = dict(graph.roles)
        for edge in edges:
            assert roles[edge.target_id] is EvidenceRole.RESOLVED
            assert by_id[edge.target_id].kind == KnowledgeKind.UNKNOWN.value

    def test_a_question_answered_by_several_statements_is_resolved_once(self) -> None:
        snapshots = _snapshots(OBSERVATIONS)
        by_id = {snapshot.id: snapshot for snapshot in snapshots}
        graph = plan_reconciliation(snapshots)
        targets = [
            by_id[edge.target_id].content
            for edge in graph.edges
            if edge.reason == "candidate_resolution"
        ]
        assert len(targets) == len(set(targets))

    def test_a_chunk_local_question_is_still_an_extracted_row(self) -> None:
        """Resolution changes a role. It does not delete evidence."""

        snapshots = _snapshots(OBSERVATIONS)
        graph = plan_reconciliation(snapshots)
        assert len(snapshots) == len(OBSERVATIONS)
        assert set(graph.resolved_item_ids) <= {snapshot.id for snapshot in snapshots}
        tagged = [item for item in OBSERVATIONS if CHUNK_LOCAL_QUESTION in item.cases]
        assert len(tagged) == 9


def _snapshot_for(content: str, kind: KnowledgeKind) -> EvidenceSnapshot:
    return EvidenceSnapshot(KnowledgeItemId("probe"), kind.value, content, LifecycleState.PROPOSED)
