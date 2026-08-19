"""The eight sparse-project scenarios, end to end (N41).

From the progressive-acquisition context. Each is a situation where a system
built around completeness would refuse, and where this one must produce
something honest instead. The principle under test throughout:

    Incomplete, uncertain, or minimal project knowledge is a normal project
    condition — not a KAE failure.

The eighth scenario is the one that keeps the other seven honest. A system that
never blocks is not principled, it is careless; there are five things that
genuinely must stop an operation, and the test asserts that a real block stays
**narrow** — it stops the operation that needs the missing thing and nothing
else.

Nothing here asserts a model's taste. No count of questions, no wording, no
particular assumption.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.deliverable_service import DeliverableService
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.application.setup_service import SetupService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.publication_targets import Provider
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch


@pytest.fixture
def context(factory: sessionmaker[Session]) -> tools.ToolContext:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        classification=ClassificationService(factory),
        clarification=ClarificationService(factory),
        assembly=AssemblyService(factory),
        assumptions=AssumptionService(factory),
        deliverables=DeliverableService(factory),
        preliminary=PreliminaryContextService(factory),
        setup=SetupService(factory),
    )


def _project(context: tools.ToolContext, name: str, key: str) -> str:
    return str(context.memory.create_project(name, key=key).id)


def _observe(context: tools.ToolContext, project_id: str, text: str, key: str) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_submit_observation",
        {
            "project_id": project_id,
            "observation": text,
            "idempotency_key": key,
            # These scenarios test what KAE does with the state it has, not what
            # a model produces from it. Extraction is N42's path and needs a
            # worker; asserting over its output would be asserting taste.
            "generation_policy": {"discovery_extraction": "disabled"},
        },
    )


def _compose(context: tools.ToolContext, project_id: str) -> dict[str, Any]:
    return dispatch(context, "kae_get_preliminary_context", {"project_id": project_id})


def _confirm(
    factory: sessionmaker[Session], project_id: str, text: str, key: str, confirm: bool = True
) -> str:
    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, key)
    written = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, text, "seed")]
    )
    ReadinessService(factory).assign_area(
        ProjectId(project_id), written[0].id, "constraints_and_assumptions"
    )
    if confirm:
        memory.confirm_knowledge(written[0].id)
    return str(written[0].id)


class TestOne_AOneSentenceIdea:
    """The manual test that started all of this."""

    def test_it_produces_context_rather_than_a_refusal(self, context: tools.ToolContext) -> None:
        project_id = _project(context, "Inbox", "n41-idea")
        _observe(
            context,
            project_id,
            "I want an inbox where I can dump thoughts and have them turned into useful things.",
            "n41-1",
        )

        payload = _compose(context, project_id)

        assert payload.get("error") is None
        assert payload["stated_verbatim"]
        assert payload["readiness_percentage"] == 0

    def test_nothing_is_presented_as_confirmed(self, context: tools.ToolContext) -> None:
        project_id = _project(context, "Inbox", "n41-idea-2")
        _observe(context, project_id, "I want an inbox for thoughts.", "n41-2")

        assert _compose(context, project_id)["known"] == []


class TestTwo_APartialQuestionnaire:
    """Some questions answered, most not. The common state after one session."""

    def test_answered_questions_leave_the_queue_and_the_rest_stay(
        self, context: tools.ToolContext
    ) -> None:
        project_id = _project(context, "Partial", "n41-partial")
        listed = dispatch(
            context, "kae_get_clarifications", {"project_id": project_id, "limit": 50}
        )
        answered = listed["questions"][0]["clarification_id"]

        dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": answered,
                "answer": "It is for one person keeping notes.",
            },
        )

        remaining = dispatch(
            context, "kae_get_clarifications", {"project_id": project_id, "limit": 50}
        )
        assert answered not in {q["clarification_id"] for q in remaining["questions"]}
        assert remaining["questions"]

    def test_a_partial_project_still_composes(self, context: tools.ToolContext) -> None:
        project_id = _project(context, "Partial", "n41-partial-2")
        listed = dispatch(context, "kae_get_clarifications", {"project_id": project_id, "limit": 1})
        dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": listed["questions"][0]["clarification_id"],
                "answer": "One person keeping notes.",
            },
        )

        payload = _compose(context, project_id)

        assert payload.get("error") is None
        assert payload["material_unknowns"] or payload["deferrable_unknowns"]


class TestThree_AnExistingProjectWithWeakDocumentation:
    """Statements exist, nobody confirmed them. The state after ingestion."""

    def test_unconfirmed_statements_are_included_and_labelled(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        project_id = _project(context, "Legacy", "n41-legacy")
        _confirm(factory, project_id, "The service exposes a REST API.", "n41-w", confirm=False)

        payload = _compose(context, project_id)

        assert payload["proposed"]
        assert payload["known"] == []
        assert all(s["inclusion_class"] != "confirmed" for s in payload["proposed"])

    def test_a_warning_says_what_it_rests_on(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        project_id = _project(context, "Legacy", "n41-legacy-2")
        _confirm(factory, project_id, "The service exposes a REST API.", "n41-w2", confirm=False)

        assert any(
            "not" in w or "candidates" in w for w in _compose(context, project_id)["warnings"]
        )


class TestFour_ContradictorySources:
    """Two confirmed statements that disagree. Generation continues and says so."""

    def test_generation_continues_and_the_disagreement_is_visible(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        project_id = _project(context, "Conflicted", "n41-conflict")
        _confirm(factory, project_id, "Notes are stored as markdown files.", "n41-c1")
        _confirm(factory, project_id, "Notes are stored in a database.", "n41-c2")

        payload = _compose(context, project_id)

        assert payload.get("error") is None
        assert len(payload["known"]) == 2

    def test_the_deliverable_records_the_contested_count(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        """Recorded rather than resolved. Resolution is a human ruling, and a
        package that quietly dropped one side would be picking a winner."""

        project_id = _project(context, "Conflicted", "n41-conflict-2")
        _confirm(factory, project_id, "Notes are markdown.", "n41-c3")

        recorded = dispatch(
            context,
            "kae_record_deliverable",
            {"project_id": project_id, "purpose": "discovery", "include_proposed": True},
        )

        assert "contested" in recorded["provisional_context"]


class TestFive_NoPublicationTarget:
    """Nothing is configured. Everything except publication still works."""

    def test_generation_is_unaffected(self, context: tools.ToolContext) -> None:
        project_id = _project(context, "Unconfigured", "n41-notarget")
        _observe(context, project_id, "I want a note-taking tool.", "n41-5")

        assert _compose(context, project_id).get("error") is None

    def test_a_deliverable_can_still_be_recorded(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        """Recording an output is not publishing it. A project with nowhere to
        publish still has outputs worth keeping."""

        project_id = _project(context, "Unconfigured", "n41-notarget-2")
        _confirm(factory, project_id, "Notes are markdown.", "n41-5b")

        recorded = dispatch(
            context, "kae_record_deliverable", {"project_id": project_id, "purpose": "discovery"}
        )

        assert recorded["deliverable_id"]

    def test_only_publication_is_reported_as_blocked(self, context: tools.ToolContext) -> None:
        project_id = _project(context, "Unconfigured", "n41-notarget-3")

        state = dispatch(context, "kae_get_setup_state", {"project_id": project_id})

        blocked = {gap["capability"] for gap in state["gaps"] if gap["blocking"]}
        assert blocked == {"publication"}


class TestSix_GenerateNowWithImportantQuestionsOpen:
    """The request the rejected readiness gate would have refused."""

    def test_it_generates(self, context: tools.ToolContext) -> None:
        project_id = _project(context, "Impatient", "n41-now")
        _observe(context, project_id, "I want a note-taking tool.", "n41-6")

        payload = _compose(context, project_id)

        assert payload.get("error") is None
        assert payload["has_content"] if "has_content" in payload else payload["stated_verbatim"]

    def test_the_open_questions_are_disclosed_rather_than_used_as_a_reason(
        self, context: tools.ToolContext
    ) -> None:
        """Disclosed, not enforced. That is the whole difference between a
        warning and a gate."""

        project_id = _project(context, "Impatient", "n41-now-2")

        payload = _compose(context, project_id)

        assert payload["material_unknowns"] or payload["deferrable_unknowns"]
        assert payload.get("error") is None

    def test_the_deliverable_records_what_was_open_at_the_time(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        project_id = _project(context, "Impatient", "n41-now-3")
        _confirm(factory, project_id, "Notes are markdown.", "n41-6c")

        recorded = dispatch(
            context, "kae_record_deliverable", {"project_id": project_id, "purpose": "discovery"}
        )

        assert recorded["provisional_context"]["question_pins"]

    def test_the_agent_is_told_what_was_unresolved_in_the_same_words_the_person_is(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        """`D-293`: the manifest reached the HTTP reader and not this one.

        `provisional_context` counts the uncertainty; the manifest quotes it —
        each gap's summary and the assembly's own warnings — and a record
        written before provisional context existed has nothing else.
        """

        project_id = _project(context, "Impatient", "n41-now-4")
        _confirm(factory, project_id, "Notes are markdown.", "n41-6d")

        recorded = dispatch(
            context, "kae_record_deliverable", {"project_id": project_id, "purpose": "discovery"}
        )
        manifest = recorded["manifest"]

        assert (
            manifest["confirmation_state"]["confirmed"]
            == (recorded["provisional_context"]["confirmed"])
        )
        assert isinstance(manifest["unresolved_critical_gaps"], list)
        assert isinstance(manifest["warnings"], list)


class TestSeven_ReproducingAHistoricalProvisionalDeliverable:
    """The claim, not only the bytes."""

    def test_the_old_record_keeps_saying_what_it_said(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        project_id = _project(context, "Historical", "n41-history")
        _confirm(factory, project_id, "Notes are markdown.", "n41-7", confirm=False)
        recorded = dispatch(
            context,
            "kae_record_deliverable",
            {"project_id": project_id, "purpose": "discovery", "include_proposed": True},
        )
        before = recorded["provisional_context"]

        _confirm(factory, project_id, "Notes are markdown, confirmed.", "n41-7b")

        listed = dispatch(context, "kae_list_deliverables", {"project_id": project_id})
        found = next(
            item
            for item in listed["results"]
            if item["deliverable_id"] == recorded["deliverable_id"]
        )
        assert found["provisional_context"] == before

    def test_it_renders_to_the_same_bytes(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        from kae_memory.application.render_service import RenderService, package_hash

        project_id = _project(context, "Historical", "n41-history-2")
        _confirm(factory, project_id, "Notes are markdown.", "n41-7c")
        recorded = dispatch(
            context, "kae_record_deliverable", {"project_id": project_id, "purpose": "discovery"}
        )

        render = RenderService(factory)
        first = render.render(ProjectId(project_id), recorded["deliverable_id"])
        second = render.render(ProjectId(project_id), recorded["deliverable_id"])

        assert package_hash(first.artifacts) == package_hash(second.artifacts)


class TestEight_ARealBlockStaysNarrow:
    """The scenario that keeps the other seven honest.

    A system that never blocks is not principled, it is careless. Five things
    genuinely must stop an operation, and when one does it must stop **that**
    operation rather than the project.
    """

    def test_an_unauthorised_target_blocks_publication(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        project_id = _project(context, "Blocked", "n41-block")
        setup = SetupService(factory)
        connection = setup.record_connection(ProjectId(project_id), Provider.GITHUB)
        setup.register_target(
            ProjectId(project_id),
            Provider.GITHUB,
            "studio",
            connection_id=str(connection.id),
            make_default=True,
        )

        targets = dispatch(context, "kae_list_publication_targets", {"project_id": project_id})

        assert targets["results"][0]["available"] is False

    def test_it_does_not_block_generation(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        """The narrowness. An unauthorised GitHub connection must not stop a
        project producing a document."""

        project_id = _project(context, "Blocked", "n41-block-2")
        setup = SetupService(factory)
        connection = setup.record_connection(ProjectId(project_id), Provider.GITHUB)
        setup.register_target(
            ProjectId(project_id),
            Provider.GITHUB,
            "studio",
            connection_id=str(connection.id),
            make_default=True,
        )
        _confirm(factory, project_id, "Notes are markdown.", "n41-8")

        assert _compose(context, project_id).get("error") is None
        assert dispatch(
            context, "kae_record_deliverable", {"project_id": project_id, "purpose": "discovery"}
        )["deliverable_id"]

    def test_the_block_says_what_would_lift_it(
        self, context: tools.ToolContext, factory: sessionmaker[Session]
    ) -> None:
        """A block with no remedy is indistinguishable from a fault."""

        project_id = _project(context, "Blocked", "n41-block-3")
        setup = SetupService(factory)
        connection = setup.record_connection(ProjectId(project_id), Provider.GITHUB)
        setup.register_target(
            ProjectId(project_id),
            Provider.GITHUB,
            "studio",
            connection_id=str(connection.id),
            make_default=True,
        )

        state = dispatch(context, "kae_get_setup_state", {"project_id": project_id})

        assert all(gap["next_action"].strip() for gap in state["gaps"])

    def test_no_block_is_about_how_much_is_known(self, context: tools.ToolContext) -> None:
        """The line every one of these eight scenarios exists to hold."""

        project_id = _project(context, "Blocked", "n41-block-4")

        state = dispatch(context, "kae_get_setup_state", {"project_id": project_id})

        assert all(
            "know" not in gap["reason"].lower() and "readiness" not in gap["reason"].lower()
            for gap in state["gaps"]
            if gap["blocking"]
        )
