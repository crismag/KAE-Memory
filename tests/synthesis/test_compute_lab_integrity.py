"""The AWS Compute Lab fixture is internally consistent and holds the live shape.

No database needed. These freeze the fixture so a later phase cannot quietly
drop one of doc 17's named failure patterns, or make the corpus easier by
trimming the repetition that is the whole point of it.

The proportion checks matter more than they look. If the kind mix drifts, the
unclassified fraction drifts with it — because classification here is a
function of kind alone — and a gate that reads 85% would start reading
something else without anyone changing a gate.
"""

from __future__ import annotations

from kae_memory.application.review_service import unambiguous_area_for
from kae_memory.domain.models import KnowledgeKind
from tests.synthesis.compute_lab import (
    ADMIN_PROFILE_DECISION_TEXT,
    ADMIN_PROFILE_RULE_TEXT,
    ATTENTION_BOUND,
    AWS_PROFILE,
    CHUNK_LOCAL_QUESTION,
    CONFIRMATION_ABANDONED,
    DEAD_LETTER_QUEUE,
    DEFERRED_DECISION,
    HARNESS_NOISE,
    HEADLINE_COUNTS,
    IMPLEMENTATION_DETAIL,
    LIVE_ITEM_COUNT,
    LIVE_UNCLASSIFIED_COUNT,
    LIVE_UNKNOWN_COUNT,
    LIVE_VALIDATED_COUNT,
    MECHANICALLY_CLASSIFIABLE,
    OBSERVATIONS,
    OBSERVED_FACT,
    PROFILE_CONFLICT,
    REPEATED_IMPLEMENTATION,
    SAFE_DELETE_ANSWER_TEXT,
    SAFE_DELETE_QUESTION_TEXT,
    TRUNCATION_ARTIFACT,
    collapse_key,
    count_by_kind,
    observations_for,
)


def _would_classify(kind: KnowledgeKind) -> bool:
    """Whether today's offline review assigns this kind an area at all."""

    return unambiguous_area_for(kind.value) is not None


class TestHeadlineCounts:
    def test_extracted_counts_match_the_documented_corpus(self) -> None:
        assert count_by_kind() == dict(HEADLINE_COUNTS)

    def test_the_corpus_is_the_size_the_conversation_corpus_is(self) -> None:
        """`SYN-0` used 175 rows to carry its pathology. 803 rows would not
        make this one truer, only slower."""

        assert 150 <= len(OBSERVATIONS) <= 220

    def test_kind_proportions_track_the_live_project(self) -> None:
        """Within two points of the live 809, kind by kind."""

        live = {
            KnowledgeKind.REQUIREMENT.value: 242,
            KnowledgeKind.RULE.value: 197,
            KnowledgeKind.UNKNOWN.value: 103,
            KnowledgeKind.GOAL.value: 67,
            KnowledgeKind.ACTOR.value: 63,
            KnowledgeKind.ASSUMPTION.value: 55,
            KnowledgeKind.CONSTRAINT.value: 46,
            KnowledgeKind.DECISION.value: 36,
        }
        assert sum(live.values()) == LIVE_ITEM_COUNT
        fixture = count_by_kind()
        for kind, live_count in live.items():
            share = fixture[kind] / len(OBSERVATIONS)
            assert abs(share - live_count / LIVE_ITEM_COUNT) < 0.02, kind


class TestTheUnclassifiedShapeIsReproduced:
    def test_only_actors_and_assumptions_are_offline_classifiable(self) -> None:
        """Not an accident of the fixture: `SOFTWARE_TEMPLATE` says so, and
        `RUN-C1` ruled against rebalancing it to cover more ground."""

        classifiable = {kind for kind in KnowledgeKind if _would_classify(kind)}
        assert classifiable == {KnowledgeKind.ACTOR, KnowledgeKind.ASSUMPTION}

    def test_the_unclassified_fraction_matches_the_live_project(self) -> None:
        unclassified = sum(1 for item in OBSERVATIONS if not _would_classify(item.kind))
        assert (
            abs(unclassified / len(OBSERVATIONS) - LIVE_UNCLASSIFIED_COUNT / LIVE_ITEM_COUNT) < 0.02
        )

    def test_open_questions_are_a_comparable_share_of_the_backlog(self) -> None:
        """103 of 809 questions is doc 17's third headline number."""

        unknowns = HEADLINE_COUNTS[KnowledgeKind.UNKNOWN.value]
        assert abs(unknowns / len(OBSERVATIONS) - LIVE_UNKNOWN_COUNT / LIVE_ITEM_COUNT) < 0.02

    def test_almost_nothing_was_confirmed_before_the_person_stopped(self) -> None:
        """Six of 809 is a person opening a queue of hundreds and giving up.
        The fixture keeps that ratio rather than the count."""

        confirmed = [item for item in OBSERVATIONS if item.confirm]
        assert {item.content for item in observations_for(CONFIRMATION_ABANDONED)} == {
            item.content for item in confirmed
        }
        assert len(confirmed) / len(OBSERVATIONS) < LIVE_VALIDATED_COUNT / LIVE_ITEM_COUNT * 2


class TestNamedPathologiesArePresent:
    def test_repeated_implementation_evidence_dominates_the_corpus(self) -> None:
        """Doc 17 outcome 4. Repetition is the repository pathology; if a
        rewrite of this fixture removes it, there is nothing left to merge."""

        repeated = observations_for(REPEATED_IMPLEMENTATION)
        assert len(repeated) > len(OBSERVATIONS) / 4

    def test_each_merge_cluster_has_enough_members_to_be_a_merge(self) -> None:
        for case in (AWS_PROFILE, DEAD_LETTER_QUEUE):
            members = observations_for(case)
            assert len(members) >= 8, case
            assert len({item.kind for item in members}) >= 3, case

    def test_implementation_detail_is_present_and_is_not_project_knowledge(self) -> None:
        """Doc 17: *Is it merely implementation detail?* A flag default is
        true, evidenced, and still not something a project model should hold."""

        detail = observations_for(IMPLEMENTATION_DETAIL)
        assert len(detail) >= 15
        assert any("--" in item.content for item in detail)
        assert any("/" in item.content for item in detail)

    def test_chunk_local_questions_are_answered_elsewhere_in_the_corpus(self) -> None:
        """Doc 17 outcome 8, and its own words: *Repository ingestion must not
        create hundreds of persistent questions simply because individual
        chunks lack global context.*"""

        questions = observations_for(CHUNK_LOCAL_QUESTION)
        assert len(questions) >= 8
        assert all(item.kind is KnowledgeKind.UNKNOWN for item in questions)

        texts = {item.content for item in OBSERVATIONS}
        assert SAFE_DELETE_QUESTION_TEXT in texts
        assert SAFE_DELETE_ANSWER_TEXT in texts

    def test_the_profile_question_is_answered_by_the_profile_decision(self) -> None:
        answers = observations_for(AWS_PROFILE)
        assert any(item.kind is KnowledgeKind.DECISION for item in answers)
        assert any(item.kind is KnowledgeKind.ASSUMPTION for item in answers)

    def test_material_that_should_be_classified_without_a_human_is_present(self) -> None:
        """Doc 17 outcome 3 / `EPI-3`. These say what area they belong to in
        the statement itself; they are unclassified only because their *kind*
        maps to more than one area."""

        mechanical = observations_for(MECHANICALLY_CLASSIFIABLE)
        assert len(mechanical) >= 25
        assert not any(_would_classify(item.kind) for item in mechanical)

    def test_incidental_harness_material_is_present(self) -> None:
        """Doc 17 outcome 5. These describe the agent harness that produced the
        repository's documents, not AWS Compute Lab."""

        noise = observations_for(HARNESS_NOISE)
        assert len(noise) >= 25
        assert len({item.kind for item in noise}) >= 5

    def test_truncation_artifacts_became_durable_unknowns(self) -> None:
        residue = observations_for(TRUNCATION_ARTIFACT)
        assert residue
        assert all(item.kind is KnowledgeKind.UNKNOWN for item in residue)

    def test_observed_repository_facts_are_present(self) -> None:
        """Doc 17's `docker-compose declares PostgreSQL`: the file is the
        evidence, and asking a person to confirm it is the defect."""

        observed = observations_for(OBSERVED_FACT)
        assert len(observed) >= 6
        assert any("compute_lab_mvp/" in item.content for item in observed)

    def test_one_genuine_contradiction_exists(self) -> None:
        """Doc 17 outcome 9. Two repository statements that cannot both hold:
        the CLIs are split by privilege, and the admin CLI is told to run under
        the unprivileged profile."""

        conflict = observations_for(PROFILE_CONFLICT)
        texts = {item.content for item in conflict}
        assert ADMIN_PROFILE_RULE_TEXT in texts
        assert ADMIN_PROFILE_DECISION_TEXT in texts

    def test_a_few_matters_genuinely_need_the_project_owner(self) -> None:
        """Doc 17 outcomes 10-11. If nothing here needed a person, a gate that
        bounds attention would pass by producing nothing."""

        deferred = observations_for(DEFERRED_DECISION)
        assert 1 <= len(deferred) <= ATTENTION_BOUND


class TestFixtureHygiene:
    def test_every_observation_has_a_source(self) -> None:
        assert all(item.source.strip() for item in OBSERVATIONS)

    def test_sources_name_the_repository_not_a_conversation(self) -> None:
        """Repository-derived evidence and conversation-derived evidence do not
        carry the same authority (doc 17, *Source authority is contextual*).
        The fixture must not blur that at the provenance line."""

        assert all(item.source.startswith("repository:aws-compute-lab:") for item in OBSERVATIONS)

    def test_identical_collapse_keys_are_unique(self) -> None:
        """Near-duplicates must survive `write_knowledge` as separate rows.
        Identical ones collapse there, which would erase the pathology."""

        keys = [collapse_key(item) for item in OBSERVATIONS]
        assert len(keys) == len(set(keys))

    def test_attention_bound_is_a_handful_not_a_target_count(self) -> None:
        assert 1 <= ATTENTION_BOUND <= 8
        assert len(OBSERVATIONS) > ATTENTION_BOUND * 20
