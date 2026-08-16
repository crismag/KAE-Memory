"""Qualitative gates the AWS Compute Lab corpus must satisfy once ingestion reconciles.

`17-KAE-MEMORY-EPISTEMIC-INGESTION-MODEL.md` ends with twelve numbered
outcomes it calls the *regression expectation* for this project. Each testable
one is an assertion below. They are not target counts — doc 17 says
*"Exact counts are not acceptance criteria"* — and the numbers that do appear
are bounds and ratios rather than goals.

They fail on today's product, and they fail for the reason doc 17 gives: no
ingestion adapter converges on a reconciliation contract, so consuming a
repository writes 180 candidates and stops. ``xfail(strict=True)`` is what
makes that a specification rather than a complaint — removing a mark without
satisfying its gate is a regression, and satisfying a gate without removing the
mark fails the run.

**What already exists and still does not run here.** `GoalSynthesisService`
can synthesize a goal model (`SYN-3b`) and `ReconciliationService` can relate
evidence (`SYN-2`). Neither is invoked below, deliberately: repository
ingestion reaches the review queue without passing through either, which is
exactly the rule `EPI-6` states. These gates read what a *repository ingest*
leaves behind, not what a hand-run synthesizer could produce from it.

Outcome 1 — *ingest/consume AWS Compute Lab* — has no assertion of its own; it
is what `compute_lab_load.py` does, and `test_compute_lab_baseline.py`
characterises. Outcome 12 — advanced inspection of pipeline health — is a
Studio surface (`EPI-7`); its Memory half, that raw evidence stays retrievable,
is `TestEvidenceAndProvenanceSurvive` below.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, SynthesisService
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeItem, KnowledgeKind, Project
from kae_memory.domain.readiness import AreaState
from kae_memory.domain.synthesis import EvidenceRole
from tests.synthesis.compute_lab import (
    ADMIN_PROFILE_DECISION_TEXT,
    ADMIN_PROFILE_RULE_TEXT,
    ATTENTION_BOUND,
    CHUNK_LOCAL_QUESTION,
    DEAD_LETTER_QUEUE,
    DEFERRED_LAYER_TEXT,
    EXPECTED_AREAS,
    HARNESS_NOISE,
    IDEMPOTENT_CONSUMER,
    IMPLEMENTATION_DETAIL,
    MECHANICALLY_CLASSIFIABLE,
    OBSERVATIONS,
    PROJECT_IDENTITY_TEXT,
    REPEATED_IMPLEMENTATION,
    SAFE_DELETE_QUESTION_TEXT,
    TRUNCATION_ARTIFACT,
    observations_for,
)
from tests.synthesis.compute_lab_load import LoadedRepositoryCorpus, load_compute_lab_corpus

pytestmark = pytest.mark.synthesis_gate

_CLASSIFICATION_IS_THE_USERS = (
    "strict=True xfail: `EPI-3` is not built. `classify_offline` assigns the two "
    "kinds exactly one area accepts and leaves the other six to a person, so "
    "unclassified is still a user queue rather than KAE's processing backlog. "
    "Since `D-110` this class grades placements as well as counting them."
)

_NO_REPOSITORY_SYNTHESIS = (
    "strict=True xfail: `EPI-1` and `EPI-6` are not built. Repository ingestion "
    "writes candidates straight to review and nothing derives a model from them, "
    "so the active model is still all 180 extracted rows."
)

_UNKNOWNS_NOT_RECONCILED = (
    "strict=True xfail: `EPI-4` is not built. An extractor's unanswered question "
    "still becomes a durable project unknown even when another chunk answers it."
)

_ATTENTION_IS_THE_QUEUE = (
    "strict=True xfail: `EPI-6` is not built. There is no attention layer for a "
    "repository ingest, so the proposed rows are the queue by default."
)

_READINESS_COUNTS_CONFIRMATIONS = (
    "strict=True xfail: `EPI-5` is not built. Readiness is still a function of "
    "confirmed rows in classified areas, so a fully consumed repository reports "
    "its areas as missing."
)


@dataclass(frozen=True, slots=True)
class Ingested:
    """One AWS Compute Lab ingest, and the services that read it back."""

    readiness: ReadinessService
    synthesis: SynthesisService
    project: Project
    corpus: LoadedRepositoryCorpus

    def model(self, domain: str | None = None) -> tuple[str, ...]:
        """The synthesized project model, as the product would read it."""

        return tuple(obj.statement for obj in self.synthesis.list_objects(self.project.id, domain))

    def roles_for(self, case: str) -> tuple[EvidenceRole, ...]:
        """The epistemic role of every row tagged with a named regression case."""

        wanted = {item.content for item in observations_for(case)}
        return tuple(
            self.synthesis.evidence_role(item.id)
            for item in self.corpus.items
            if item.current_version.content in wanted
        )


@pytest.fixture
def ingested(factory: sessionmaker[Session]) -> Ingested:
    memory = MemoryService(factory)
    readiness = ReadinessService(factory)
    project = memory.create_project("AWS Compute Lab", key="compute-lab-gates")
    corpus = load_compute_lab_corpus(memory, readiness, project.id)
    return Ingested(readiness, SynthesisService(factory), project, corpus)


def _shown_as_work(ingested: Ingested) -> tuple[KnowledgeItem, ...]:
    """What Studio Reviews puts in front of a person after this ingest.

    Doc 17's screenshot in one function: everything still awaiting review, plus
    everything a classifier declined to place.

    Rows KAE has since given an epistemic role are excluded, and that exclusion
    is the whole route to satisfying the gate. Doc 17 keeps the confirmation
    field for migration — *"existing records may retain a confirmation field
    temporarily"* — so a row staying ``proposed`` is not the defect. A row
    staying ``proposed``, unplaced, unreconciled, and counted as somebody's
    work is.
    """

    unclassified = {str(item.id) for item in ingested.corpus.unclassified}
    return tuple(
        item
        for item in ingested.corpus.items
        if ingested.synthesis.evidence_role(item.id) is EvidenceRole.ACTIVE
        and (item.lifecycle is LifecycleState.PROPOSED or str(item.id) in unclassified)
    )


class TestEvidenceAndProvenanceSurvive:
    """Outcome 2, and the Memory half of outcome 12. Already required today.

    Every gate below permits a much smaller active model. None of them permits
    losing a row — compaction is not deletion (`ADR-0007`), and doc 17 is
    explicit that evidence stays referenceable so conclusions remain
    explainable.
    """

    def test_every_extracted_row_remains_retrievable(self, ingested: Ingested) -> None:
        assert len(ingested.corpus.items) == len(OBSERVATIONS)
        assert len(ingested.corpus.items) == len(ingested.corpus.observations)

    def test_every_row_still_names_the_repository_it_came_from(self, ingested: Ingested) -> None:
        assert all(item.current_version.provenance.source.strip() for item in ingested.corpus.items)


@pytest.mark.xfail(strict=True, reason=_CLASSIFICATION_IS_THE_USERS)
class TestUnclassifiedIsKaesBacklogNotTheUsers:
    """Outcome 3. `EPI-3`.

    Doc 17: *"The user should not become KAE-Memory's taxonomy clerk."* Its
    remedies are all internal — retry with broader context, cluster, attach as
    supporting evidence, classify as incidental — and escalation only where the
    ambiguity itself is material.
    """

    def test_the_majority_of_observations_are_classified_without_a_human(
        self, ingested: Ingested
    ) -> None:
        corpus = ingested.corpus
        classified = len(corpus.items) - len(corpus.unclassified)

        assert classified / len(corpus.items) >= 0.7

    def test_statements_that_name_their_own_area_are_placed(self, ingested: Ingested) -> None:
        """These are unclassified only because their *kind* maps to several
        areas. Nothing about the statement itself is ambiguous."""

        mechanical = {item.content for item in observations_for(MECHANICALLY_CLASSIFIABLE)}
        stranded = {
            item.current_version.content
            for item in ingested.corpus.unclassified
            if item.current_version.content in mechanical
        }

        assert not stranded

    def test_classification_reaches_more_than_two_discovery_areas(self, ingested: Ingested) -> None:
        assert len({link.area_key for link in ingested.corpus.area_links}) > 2

    def test_placed_statements_land_in_the_area_they_belong_in(self, ingested: Ingested) -> None:
        """`D-110`. The three gates above count placements; this one grades
        them.

        Without it, `EPI-3b` is satisfiable by a classifier that places enough
        rows anywhere — and `EPI-5b` does not cover that. `EPI-5b` stopped
        auto-placement inflating readiness; it says nothing about a quality
        attribute filed under functional requirements, which is still coverage
        somebody has to unpick.

        `EXPECTED_AREAS` is written from the statements alone and deliberately
        holds only the rows that *have* an answer — the ones the template
        forbids and the ones the sentence leaves open are excluded by name, so
        this cannot fail for a reason the classifier could not have fixed.
        """

        by_content = {item.id: item.current_version.content for item in ingested.corpus.items}
        placed = {
            by_content[link.knowledge_item_id]: link.area_key
            for link in ingested.corpus.area_links
            if link.knowledge_item_id in by_content
        }

        missing = [content for content in EXPECTED_AREAS if content not in placed]
        wrong = {
            content: (placed[content], expected)
            for content, expected in EXPECTED_AREAS.items()
            if content in placed and placed[content] != expected
        }

        # Both halves, because either alone is passable by doing nothing: a
        # classifier that places none of these scores no wrong answers, and one
        # that places all of them anywhere scores full coverage.
        assert not missing, f"never placed: {missing}"
        assert not wrong, f"placed in the wrong area: {wrong}"


@pytest.mark.xfail(strict=True, reason=_NO_REPOSITORY_SYNTHESIS)
class TestRepeatedEvidenceMergesIntoConcepts:
    """Outcome 4.

    Doc 17's illustrative arc is *"803 extracted observations -> clusters /
    supporting evidence -> tens of coherent project concepts"*. This corpus
    restates one dead-letter rule fifteen times across five kinds because five
    markdown files each said it. A person should meet it once.
    """

    def test_the_model_is_much_smaller_than_the_evidence(self, ingested: Ingested) -> None:
        model = ingested.model()

        assert model, "the project model is empty; nothing synthesized the ingest"
        assert len(model) < len(ingested.corpus.items) / 4

    def test_a_merge_cluster_does_not_arrive_as_one_object_per_row(
        self, ingested: Ingested
    ) -> None:
        cluster = {item.content for item in observations_for(DEAD_LETTER_QUEUE)}
        members = {
            item.id for item in ingested.corpus.items if item.current_version.content in cluster
        }
        covering = {
            obj.id
            for obj in ingested.synthesis.list_objects(ingested.project.id)
            for binding in ingested.synthesis.list_bindings(ingested.project.id, obj.id)
            if binding.knowledge_item_id in members
        }

        assert covering, "no synthesized object claims the dead-letter evidence"
        assert len(covering) < len(members) / 2

    def test_repeated_evidence_stops_being_active_in_its_own_right(
        self, ingested: Ingested
    ) -> None:
        """Doc 17: many observations may support one synthesized object. The
        supporting ones keep existing; they stop being independent concepts."""

        roles = ingested.roles_for(REPEATED_IMPLEMENTATION)

        assert roles
        assert sum(1 for role in roles if role is not EvidenceRole.ACTIVE) / len(roles) >= 0.8

    def test_every_promoted_concept_keeps_its_evidence(self, ingested: Ingested) -> None:
        objects = ingested.synthesis.list_objects(ingested.project.id)

        assert objects
        for obj in objects:
            bindings = ingested.synthesis.list_bindings(ingested.project.id, obj.id)
            assert bindings, f"{obj.statement!r} entered the model with no evidence"


@pytest.mark.xfail(strict=True, reason=_NO_REPOSITORY_SYNTHESIS)
class TestIncidentalMaterialIsSuppressed:
    """Outcome 5.

    Doc 17's *Noise / Non-project / Incidental* class: material that does not
    warrant promotion into the active project model, kept as *"searchable
    evidence where useful without polluting active reasoning or review"*.

    Nearly a fifth of this corpus is about the agent harness that wrote the
    repository's documents — grade floors, frozen requirement contexts,
    six-stage governed runtimes. None of it is about AWS Compute Lab.
    """

    def test_harness_material_is_not_in_the_active_model(self, ingested: Ingested) -> None:
        noise = {item.content for item in observations_for(HARNESS_NOISE)}
        model = set(ingested.model())

        assert model, "the project model is empty; nothing synthesized the ingest"
        assert model.isdisjoint(noise)

    def test_harness_material_is_marked_rather_than_silently_kept_active(
        self, ingested: Ingested
    ) -> None:
        """Marked, not deleted: doc 17 keeps it searchable for provenance."""

        roles = ingested.roles_for(HARNESS_NOISE)

        assert roles
        assert all(role is EvidenceRole.NOISE for role in roles)

    def test_truncation_residue_is_not_a_project_unknown(self, ingested: Ingested) -> None:
        """*The document ends mid-section* is a fact about the extractor's
        input, not something the project does not know."""

        roles = ingested.roles_for(TRUNCATION_ARTIFACT)

        assert roles
        assert all(role is not EvidenceRole.ACTIVE for role in roles)

    def test_flag_defaults_and_file_paths_do_not_become_project_knowledge(
        self, ingested: Ingested
    ) -> None:
        """Doc 17 asks it as a question KAE must answer internally: *Is it
        merely implementation detail?* ``--wait must be between 0 and 20`` is
        true, evidenced, and not something a project model should hold."""

        detail = {item.content for item in observations_for(IMPLEMENTATION_DETAIL)}
        model = set(ingested.model())

        assert model, "the project model is empty; nothing synthesized the ingest"
        assert model.isdisjoint(detail)


@pytest.mark.xfail(strict=True, reason=_NO_REPOSITORY_SYNTHESIS)
class TestACoherentProjectDescriptionIsDerived:
    """Outcomes 6 and 7.

    Doc 17's success sentence is *"KAE consumed AWS Compute Lab and learned the
    project."* A model covering one domain has not learned a project, and a
    model that needed 180 confirmations was not derived.
    """

    def test_the_model_spans_the_domains_the_repository_evidenced(self, ingested: Ingested) -> None:
        domains = {obj.domain for obj in ingested.synthesis.list_objects(ingested.project.id)}

        assert len(domains) >= 4
        assert KnowledgeKind.REQUIREMENT.value in domains
        assert KnowledgeKind.ACTOR.value in domains

    def test_the_model_says_what_the_project_is(self, ingested: Ingested) -> None:
        """The repository states its own purpose in one sentence. A derived
        description that does not carry it has described something else."""

        goals = ingested.model(KnowledgeKind.GOAL.value)
        subject = {word for word in PROJECT_IDENTITY_TEXT.casefold().split() if len(word) > 4}

        assert goals
        assert any(len(subject & set(goal.casefold().split())) >= 2 for goal in goals)

    def test_the_model_was_derived_without_record_by_record_confirmation(
        self, ingested: Ingested
    ) -> None:
        """Outcome 7 in one line. Two rows were confirmed by a person, and the
        model must not have needed more."""

        validated = [
            item for item in ingested.corpus.items if item.lifecycle is LifecycleState.VALIDATED
        ]

        assert ingested.model()
        assert len(validated) <= 2


@pytest.mark.xfail(strict=True, reason=_UNKNOWNS_NOT_RECONCILED)
class TestChunkLocalQuestionsDoNotBecomeProjectUnknowns:
    """Outcome 8. `EPI-4`.

    Doc 17: *"An extractor's inability to answer something at extraction time
    does not establish a durable project unknown"*, and the first question it
    tells KAE to ask is *"Is the answer already present elsewhere in Memory?"*
    For every question tagged here, it is.
    """

    def test_questions_answered_elsewhere_in_the_corpus_are_resolved(
        self, ingested: Ingested
    ) -> None:
        roles = ingested.roles_for(CHUNK_LOCAL_QUESTION)

        assert roles
        assert all(role is EvidenceRole.RESOLVED for role in roles)

    def test_the_safe_delete_question_is_closed_by_the_poll_loop_rule(
        self, ingested: Ingested
    ) -> None:
        """One named pair, so a failure says which reconciliation is missing
        rather than that some proportion moved."""

        question = next(
            item
            for item in ingested.corpus.items
            if item.current_version.content == SAFE_DELETE_QUESTION_TEXT
        )

        assert ingested.synthesis.evidence_role(question.id) is EvidenceRole.RESOLVED

    def test_duplicate_questions_do_not_persist_separately(self, ingested: Ingested) -> None:
        """Doc 17: *Is this semantically duplicate of an existing unknown?*
        Three chunks asked what safe receive and delete behaviour means."""

        cluster = {item.content for item in observations_for(IDEMPOTENT_CONSUMER)}
        active = [
            item
            for item in ingested.corpus.items
            if item.kind == KnowledgeKind.UNKNOWN.value
            and item.current_version.content in cluster
            and ingested.synthesis.evidence_role(item.id) is EvidenceRole.ACTIVE
        ]

        assert len(active) <= 1


@pytest.mark.xfail(strict=True, reason=_ATTENTION_IS_THE_QUEUE)
class TestOnlyMaterialMattersReachAPerson:
    """Outcomes 9, 10 and 11.

    Doc 17's contrast, quoted whole because it is the acceptance criterion:

    > KAE analyzed the existing project and updated its understanding.
    > Hundreds of observations were reconciled into the current project model.
    > 3 matters need your judgment.

    against

    > 803 candidates await review. 692 items need classification. 103 questions
    > must be answered.
    """

    def test_the_review_queue_is_not_the_attention_queue(self, ingested: Ingested) -> None:
        assert len(_shown_as_work(ingested)) <= ATTENTION_BOUND

    def test_attention_is_a_handful_and_is_not_empty(self, ingested: Ingested) -> None:
        """Bounded above and below. A pipeline that surfaced nothing would
        satisfy a bound alone while hiding the deferred decision that really
        does need the owner."""

        attention = ingested.synthesis.list_attention(ingested.project.id)

        assert 1 <= len(attention) <= ATTENTION_BOUND

    def test_the_genuine_contradiction_is_identified(self, ingested: Ingested) -> None:
        """Outcome 9. The CLIs are split by privilege level, and a rule tells
        the admin commands to run under the unprivileged profile. Both are
        repository statements, neither is noise, and they cannot both hold."""

        conflicting = {
            item.current_version.content
            for item in ingested.corpus.items
            if ingested.synthesis.evidence_role(item.id) is EvidenceRole.CONFLICTING
        }

        assert ADMIN_PROFILE_RULE_TEXT in conflicting
        assert ADMIN_PROFILE_DECISION_TEXT in conflicting

    def test_the_deferred_decision_reaches_the_owner(self, ingested: Ingested) -> None:
        """Outcome 9's second half: a consequential missing decision. The
        author deferred which abstraction layer the MVP targets and said it
        blocks scoping. No amount of repository evidence answers that."""

        attention = ingested.synthesis.list_attention(ingested.project.id)
        subject = {word for word in DEFERRED_LAYER_TEXT.casefold().split() if len(word) > 5}

        assert any(
            subject & set(f"{item.title} {item.explanation}".casefold().split())
            for item in attention
        )

    def test_every_attention_item_explains_why_a_person_is_needed(self, ingested: Ingested) -> None:
        """Outcome 11: *make every surfaced attention item actionable and
        explain why a person is needed*."""

        attention = ingested.synthesis.list_attention(ingested.project.id)

        assert attention
        for item in attention:
            assert item.explanation.strip()
            assert item.actions, f"{item.title!r} says what is wrong but not what to do"


@pytest.mark.xfail(strict=True, reason=_READINESS_COUNTS_CONFIRMATIONS)
class TestReadinessDescribesEvidenceNotConfirmations:
    """Outcome 7's other half. `EPI-5`.

    Doc 17: *"A repository-backed area may have strong current-implementation
    knowledge without a user having clicked Confirm on any extracted record."*
    `ADR-0003` still rules that area state is discrete, so this asserts states
    rather than a percentage.
    """

    def test_no_mandatory_area_reports_missing_after_a_full_ingest(
        self, ingested: Ingested
    ) -> None:
        snapshot = ingested.readiness.calculate(ingested.project.id)
        missing = [
            area.key
            for area in snapshot.areas
            if area.mandatory and area.state is AreaState.MISSING
        ]

        assert not missing

    def test_functional_requirements_are_covered_by_fifty_four_requirements(
        self, ingested: Ingested
    ) -> None:
        """54 repository requirements and an area that reports nothing is the
        absurd outcome doc 17 names by hand."""

        snapshot = ingested.readiness.calculate(ingested.project.id)
        area = next(area for area in snapshot.areas if area.key == "functional_requirements")

        assert area.state is not AreaState.MISSING
