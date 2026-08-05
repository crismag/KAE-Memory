"""Classifying a submitted observation and routing what it found (T24).

The observation is evidence. Everything classification produces sits *beside*
it, and the tests below exist because each derived record is an opportunity to
claim more than the text supports.

Four claims are defended here, in rough order of what they would cost:

    a milestone is never completed because a sentence said so
    classification is not confirmation, at any confidence
    a low-confidence guess stays unclassified rather than routing
    the submission survives a classifier that fails

The worked example is real, submitted on 2026-08-03:

    "KAE-Memory achieved data insertion success on T1 test at this point.
     Few more tests before sleeping. To God be the glory!"

One operational record, two pieces of evidence, nothing durable, nothing
confirmed. A classifier that returned one class for that whole submission would
either file a prayer as a test result or discard the test result.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.agents.observation_classifier import (
    DeterministicObservationClassifier,
    extract_fields,
)
from kae_memory.application import MemoryService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.identifiers import MessageId, ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.observation import (
    TIER_OF,
    ClassifiedSpan,
    ObservationClass,
    RetentionTier,
    Route,
    Span,
    route_for,
)
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch

MIXED = (
    "KAE-Memory achieved data insertion success on T1 test at this point. "
    "Few more tests before sleeping. To God be the glory!"
)


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        classification=ClassificationService(factory),
        embedder_name="deterministic",
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Ministry Reporting", key="t24-ministry").id)


def _classification(context: tools.ToolContext) -> ClassificationService:
    """The service the fixture wired, narrowed for the type checker."""

    assert context.classification is not None
    return context.classification


def _submit(
    context: tools.ToolContext, project_id: str, text: str, key: str, **extra: Any
) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_submit_observation",
        {"project_id": project_id, "observation": text, "idempotency_key": key, **extra},
    )


class TestTheTaxonomyIsWellFormed:
    def test_every_class_has_a_tier(self) -> None:
        """Checked at import; asserted here so the guard itself is covered."""

        assert set(TIER_OF) == set(ObservationClass)

    def test_the_taxonomy_is_not_knowledge_kind(self) -> None:
        """Merging them would put commentary in the readiness denominator."""

        from kae_memory.domain.models import KnowledgeKind

        overlap = {c.value for c in ObservationClass} & {k.value for k in KnowledgeKind}
        assert "personal_commentary" not in overlap
        assert "session_note" not in overlap

    def test_commentary_is_evidence_not_durable(self) -> None:
        assert TIER_OF[ObservationClass.PERSONAL_COMMENTARY] is RetentionTier.EVIDENCE
        assert TIER_OF[ObservationClass.REQUIREMENT] is RetentionTier.DURABLE
        assert TIER_OF[ObservationClass.MILESTONE_STATUS] is RetentionTier.OPERATIONAL


class TestConfidenceGatesRoutingNotTruth:
    def test_a_confident_requirement_is_still_only_a_candidate(self) -> None:
        assert route_for(ObservationClass.REQUIREMENT, 0.99) is Route.KNOWLEDGE_CANDIDATE, (
            "a candidate, never a confirmation"
        )

    def test_durable_always_needs_review_however_confident(self) -> None:
        """A classifier sure it is a requirement has said nothing about truth."""

        span = ClassifiedSpan(ObservationClass.REQUIREMENT, 1.0, Span(0, 5), "text")

        assert span.review_required is True

    def test_a_middling_confidence_routes_to_review(self) -> None:
        assert route_for(ObservationClass.TEST_RESULT, 0.70) is Route.NEEDS_REVIEW

    def test_below_the_floor_nothing_is_routed(self) -> None:
        """Unclassified is a worse-looking outcome and a better one."""

        assert route_for(ObservationClass.MILESTONE_STATUS, 0.10) is Route.NEEDS_REVIEW
        assert route_for(ObservationClass.UNCLASSIFIED, 1.0) is Route.NEEDS_REVIEW

    def test_evidence_never_becomes_a_candidate(self) -> None:
        assert route_for(ObservationClass.PERSONAL_COMMENTARY, 0.99) is Route.EVIDENCE_ONLY


class TestDeterministicExtraction:
    """T24.1 — finds fields, decides nothing."""

    def test_it_finds_identifiers(self) -> None:
        fields = extract_fields("M8 and T1 are done, see PR #412 and ADR-0021.")

        assert fields["milestones"] == ["M8"]
        assert fields["targets"] == ["T1"]
        assert fields["decisions"] == ["ADR-0021"]
        assert "412" in fields["pull_requests"]

    def test_it_finds_dates_without_deciding_what_they_mean(self) -> None:
        """A bare date does not say whether it is a deadline or a memory."""

        fields = extract_fields("Shipped on 2026-08-03, next review by Friday.")

        assert "2026-08-03" in fields["dates"]
        assert fields["date_role"] == "unknown"

    def test_it_normalises_status_words(self) -> None:
        assert extract_fields("The suite is green.")["statuses"] == ["passed"]
        assert extract_fields("M8 is finished.")["statuses"] == ["complete"]

    def test_it_is_silent_when_there_is_nothing_to_find(self) -> None:
        assert extract_fields("Hello there.") == {}


class TestMixedObservations:
    """One submission, several spans, several routes. The normal case."""

    def test_the_worked_example_splits_three_ways(self) -> None:
        spans = DeterministicObservationClassifier().classify(MIXED)

        classes = [span.classification for span in spans]
        assert ObservationClass.TEST_RESULT in classes
        assert ObservationClass.PERSONAL_COMMENTARY in classes
        assert len(spans) == 3

    def test_every_span_is_a_real_range_of_the_text(self) -> None:
        """A reviewer must see precisely which words produced which candidate."""

        for span in DeterministicObservationClassifier().classify(MIXED):
            quoted = span.span.of(MIXED)
            assert quoted
            assert quoted in MIXED

    def test_nothing_durable_comes_out_of_it(self) -> None:
        spans = DeterministicObservationClassifier().classify(MIXED)

        assert not [span for span in spans if span.tier is RetentionTier.DURABLE]

    def test_an_unrecognised_sentence_stays_unclassified(self) -> None:
        spans = DeterministicObservationClassifier().classify("Zqx frobnicated the widget.")

        assert spans[0].classification is ObservationClass.UNCLASSIFIED
        assert spans[0].confidence == 0.0
        assert spans[0].route is Route.NEEDS_REVIEW


class TestTheClassifierIsHonestAboutItself:
    def test_it_does_not_claim_to_be_semantic(self) -> None:
        """Wording it does not recognise is invisible to it."""

        assert DeterministicObservationClassifier().semantic is False

    def test_the_response_says_so(self, context: tools.ToolContext, project_id: str) -> None:
        payload = _submit(context, project_id, MIXED, "t24-honest-1")

        assert payload["classification"]["semantic_classification"] is False


class TestSubmissionSurvivesClassification:
    def test_the_observation_is_recorded_verbatim(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Derive beside it, never over it."""

        payload = _submit(context, project_id, MIXED, "t24-verbatim-1")

        messages = context.memory.messages_for_session(payload["session_id"])
        assert any(message.content.startswith(MIXED[:40]) for message in messages)

    def test_the_hint_is_no_longer_smuggled_into_the_text(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """T24.5: it used to be appended as a line nobody read again."""

        payload = _submit(
            context,
            project_id,
            "The report must be approved.",
            "t24-hint-1",
            classification_hint="requirement",
        )

        messages = context.memory.messages_for_session(payload["session_id"])
        assert not any("Classification hint" in message.content for message in messages)

    def test_a_failing_classifier_does_not_lose_the_observation(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Evidence capture must not depend on a classifier being reachable."""

        class Broken:
            name = "broken"
            version = "0"
            semantic = False

            def classify(self, text: str) -> tuple[ClassifiedSpan, ...]:
                raise RuntimeError("classifier unavailable")

        readiness = ReadinessService(factory)
        readiness.install_template()
        context = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
            classification=ClassificationService(factory, Broken()),
        )
        project = context.memory.create_project("Broken", key="t24-broken")

        payload = _submit(context, str(project.id), MIXED, "t24-broken-1")

        assert payload["message_id"]
        assert payload["classification"]["classified"] is False
        assert payload["classification"]["reason"] == "RuntimeError"

    def test_an_unconfigured_classifier_is_reported_not_faked(
        self, factory: sessionmaker[Session]
    ) -> None:
        readiness = ReadinessService(factory)
        readiness.install_template()
        context = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
        )
        project = context.memory.create_project("Bare", key="t24-bare")

        payload = _submit(context, str(project.id), MIXED, "t24-bare-1")

        assert payload["classification"]["available"] is False
        assert payload["message_id"]


class TestClassificationNeverConfirms:
    def test_no_knowledge_is_created(self, context: tools.ToolContext, project_id: str) -> None:
        """The claim FR-005 exists to protect."""

        _submit(context, project_id, "The report must be approved.", "t24-nk-1")

        assert context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()

    def test_the_response_says_knowledge_did_not_change(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _submit(context, project_id, "The report must be approved.", "t24-nk-2")

        assert payload["classification"]["knowledge_changed"] is False

    def test_a_durable_span_is_a_candidate_needing_review(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _submit(context, project_id, "The report must be approved.", "t24-nk-3")

        durable = [
            span
            for span in payload["classification"]["spans"]
            if span["retention_tier"] == "durable"
        ]
        assert durable
        assert all(span["review_required"] for span in durable)


class TestMilestonesAreNotCompletedBySentences:
    def test_a_reported_completion_is_a_proposed_transition(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """`CURRENT_PROJECT_STATE.md` once recorded "M8 is complete" while no
        production path created chunks at all. A person wrote that in good
        faith; a classifier accepting it would have made it machine-readable.
        """

        _submit(context, project_id, "M8 is complete.", "t24-m8-1")

        records = _classification(context).operational_state(ProjectId(project_id))
        assert records
        transition = next(r for r in records if r.kind == "milestone_transition")
        assert transition.reported_status == "complete"
        assert transition.state == "proposed"
        assert transition.authority in {"agent_reported", "user_reported"}

    def test_a_test_result_is_reported_not_verified(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Only an approved runner produces a verified result."""

        _submit(context, project_id, "The suite passed on T1.", "t24-test-1")

        records = _classification(context).operational_state(ProjectId(project_id))
        result = next(r for r in records if r.kind == "test_result")
        assert result.verification == "reported"

    def test_a_regression_is_told_from_a_progression(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Not every change is a conflict, and one of these two is."""

        _submit(context, project_id, "M8 is complete.", "t24-m8-a")
        _submit(context, project_id, "M8 is blocked.", "t24-m8-b")

        records = _classification(context).operational_state(ProjectId(project_id))
        transitions = [r for r in records if r.kind == "milestone_transition"]
        assert any(r.transition_type == "regression" for r in transitions)


class TestIdempotence:
    def test_reclassifying_creates_no_duplicates(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        first = _submit(context, project_id, MIXED, "t24-idem-1")
        message_id = first["message_id"]

        again = _classification(context).classify(
            ProjectId(project_id), MessageId(message_id), MIXED
        )

        assert again.replayed is True
        assert again.operational_ids == ()

    def test_resubmitting_the_same_observation_replays(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        first = _submit(context, project_id, MIXED, "t24-idem-2")
        second = _submit(context, project_id, MIXED, "t24-idem-2")

        assert second["idempotent_replay"] is True
        assert second["message_id"] == first["message_id"]


class TestTheHintIsComparedNotObeyed:
    """T24.5 — the parameter now means something, and it is not authority."""

    def test_an_agreeing_hint_is_reported_as_agreeing(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _submit(
            context,
            project_id,
            "The report must be approved.",
            "t24-hint-agree",
            classification_hint="requirement",
        )

        assert payload["classification"]["hint"]["agreed"] is True

    def test_a_hint_cannot_promote_a_greeting(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A hint that could override would make the taxonomy a suggestion."""

        payload = _submit(
            context,
            project_id,
            "To God be the glory!",
            "t24-hint-override",
            classification_hint="requirement",
        )

        spans = payload["classification"]["spans"]
        assert all(span["classification"] != "requirement" for span in spans)
        assert payload["classification"]["hint"]["agreed"] is False

    def test_no_hint_means_no_hint_report(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _submit(context, project_id, MIXED, "t24-hint-absent")

        assert "hint" not in payload["classification"]


class TestBriefingTierFilters:
    """T24.4 — which tiers are eligible, not how much of one is rendered."""

    def test_commentary_is_excluded_by_default(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Preserved as evidence, and not presented as a claim about the project."""

        _submit(context, project_id, "To God be the glory!", "t24-tier-1")

        briefing = dispatch(context, "kae_get_project_briefing", {"project_id": project_id})

        assert "evidence" not in briefing["tiers"]["included"]
        assert "evidence" in briefing["tiers"]["excluded"]
        assert "evidence" not in briefing["tiers"]

    def test_an_excluded_tier_is_named_rather_than_silently_absent(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        briefing = dispatch(context, "kae_get_project_briefing", {"project_id": project_id})

        assert briefing["tiers"]["excluded"] == ["evidence"]

    def test_evidence_can_be_asked_for_and_arrives_labelled(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "To God be the glory!", "t24-tier-2")

        briefing = dispatch(
            context,
            "kae_get_project_briefing",
            {"project_id": project_id, "tiers": ["durable", "evidence"]},
        )

        assert briefing["tiers"]["evidence"]
        assert briefing["tiers"]["evidence"][0]["classification"] == "personal_commentary"

    def test_operational_state_appears_with_its_authority(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "M8 is complete.", "t24-tier-3")

        briefing = dispatch(context, "kae_get_project_briefing", {"project_id": project_id})

        state = briefing["tiers"]["operational_state"]
        assert state
        assert state[0]["authority"]
        assert "sentence said so" in briefing["tiers"]["operational_note"]

    def test_an_unknown_tier_is_refused(self, context: tools.ToolContext, project_id: str) -> None:
        briefing = dispatch(
            context,
            "kae_get_project_briefing",
            {"project_id": project_id, "tiers": ["everything"]},
        )

        assert briefing["error"] == "invalid_argument"

    def test_tiers_and_detail_stay_orthogonal(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A tier says which kinds are eligible; detail says how much is shown."""

        _submit(context, project_id, "M8 is complete.", "t24-tier-4")

        economy = dispatch(
            context,
            "kae_get_project_briefing",
            {"project_id": project_id, "profile": "economy"},
        )

        assert economy["tiers"]["included"] == ["durable", "operational"]


class TestReadinessIsUnaffected:
    def test_a_classified_observation_does_not_move_readiness(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Routing a fragment into knowledge_items would inflate coverage."""

        before = context.readiness.calculate(ProjectId(project_id)).percentage

        _submit(context, project_id, "The report must be approved before publishing.", "t24-r-1")

        after = context.readiness.calculate(ProjectId(project_id)).percentage
        assert after == before

    def test_no_proposed_knowledge_appears_either(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "The report must be approved.", "t24-r-2")

        items = context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)
        assert not [item for item in items if item.lifecycle is LifecycleState.PROPOSED]
