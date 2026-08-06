"""The whole journey, from one sentence to a pinned deliverable (Milestone A).

This is the manual test that failed, run as code. A person said:

    "I want an inbox where I can dump thoughts and have them turned into
    useful things."

then, when KAE asked its most important question:

    "I don't know yet. Recommend something reasonable for a prototype, but
    don't make it a permanent project decision."

Every subsystem behaved correctly and the product failed anyway, because no
path connected them. Six targets closed the gaps — N42 the extraction edge, N46
the discovery prompt, N45 the assumption adapters, N36 the disposition, N44 the
composition, N20.2 the provisional pins — and this walks the whole thing to
make sure the connections hold together rather than individually.

**Asserted through KAE's own state, and only through it.** Nothing here reads
the conversation that produced the project. A candidate that traces to a stored
message through a recorded run cannot have come from anywhere else.

**Nothing about the model's taste.** No count of questions, no particular
assumption, no wording. The requirement is semantic usefulness plus epistemic
integrity; a test asserting "exactly two questions" would fail on a better
answer and would be measuring nothing worth measuring.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.assembly_service import AssemblyService
from kae_memory.application.assumption_service import AssumptionService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.clarification_service import ClarificationService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.deliverable_service import DeliverableService
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch

SENTENCE = "I want an inbox where I can dump thoughts and have them turned into useful things."
DONT_KNOW = (
    "I don't know yet. Recommend something reasonable for a prototype, "
    "but don't make it a permanent project decision."
)


def _discovery_run(context: tools.ToolContext, project_id: str) -> Any:
    """The run the submitted observation queued.

    Answering a clarification queues its own extraction, so "the first run" is
    not a stable way to name this one.
    """

    return next(
        run
        for run in context.memory.runs_for_project(ProjectId(project_id))
        if run.role is AgentRole.DISCOVERY
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
        classification=ClassificationService(factory),
        clarification=ClarificationService(factory),
        assembly=AssemblyService(factory),
        assumptions=AssumptionService(factory),
        deliverables=DeliverableService(factory),
        preliminary=PreliminaryContextService(factory),
    )


@pytest.fixture
def journey(context: tools.ToolContext) -> dict[str, Any]:
    """Walk the whole path once, and hand every step to the assertions.

    One fixture rather than one per test: the point of this file is that the
    steps connect, and a test that re-ran only its own step would prove each
    link in isolation — which is what the six targets already do.
    """

    project_id = str(context.memory.create_project("Sparse Inbox", key="journey-inbox").id)

    submitted = dispatch(
        context,
        "kae_submit_observation",
        {
            "project_id": project_id,
            "observation": SENTENCE,
            "idempotency_key": "journey-1",
        },
    )

    listed = dispatch(context, "kae_get_clarifications", {"project_id": project_id, "limit": 1})
    question = listed["questions"][0]

    # The recommendation the person asked for, recorded where it can be found
    # again rather than said once in a conversation.
    assumption = dispatch(
        context,
        "kae_record_assumption",
        {
            "project_id": project_id,
            "subject": question["question"][:60],
            "assumed_value": "markdown files on local disk for the prototype",
            "reason": "a prototype needs no database, and this is reversible",
            "origin": "kae_recommended_accepted",
            "consequence": "rework",
        },
    )

    answered = dispatch(
        context,
        "kae_answer_clarification",
        {
            "project_id": project_id,
            "clarification_id": question["clarification_id"],
            "answer": DONT_KNOW,
            "disposition": "delegated",
            "assumption_id": assumption["assumption_id"],
        },
    )

    preliminary = dispatch(context, "kae_get_preliminary_context", {"project_id": project_id})

    deliverable = dispatch(
        context,
        "kae_record_deliverable",
        {
            "project_id": project_id,
            "purpose": "discovery",
            "include_proposed": True,
            "recorded_by": "cris",
        },
    )

    return {
        "project_id": project_id,
        "submitted": submitted,
        "question": question,
        "assumption": assumption,
        "answered": answered,
        "preliminary": preliminary,
        "deliverable": deliverable,
    }


class TestTheSentenceSurvives:
    def test_it_is_stored_verbatim(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """The record, not a paraphrase of it. Everything downstream is an
        interpretation, and only this can be checked against what was meant."""

        messages = context.memory.messages_for_session(journey["submitted"]["session_id"])

        assert any(SENTENCE in message.content for message in messages)

    def test_it_reaches_extraction(self, journey: dict[str, Any]) -> None:
        """The edge N42 added. Before it, a conversational sentence was stored
        honestly and interpreted by nothing."""

        assert journey["submitted"]["extraction"]["queued"] is True
        assert journey["submitted"]["extraction"]["run_id"]

    def test_the_run_names_the_message_it_will_read(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """Provenance starts here. A candidate that traces to a stored message
        through a recorded run cannot have come from the conversation around
        KAE — which is what makes any of this proof rather than theatre."""

        # Selected by role, not by position. Answering the clarification
        # enqueues a second run, and an index would silently start asserting
        # about whichever happened to be first.
        discovery = _discovery_run(context, journey["project_id"])

        assert discovery.input_context is not None
        assert discovery.input_context["message_id"] == journey["submitted"]["message_id"]

    def test_it_reaches_extraction_by_the_discovery_role(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """N46's role, not the requirements one. A prompt tuned for
        requirement-bearing text reads a sparse product sentence thinly, which
        is correct behaviour for that prompt and the reason it is not this
        one."""

        assert _discovery_run(context, journey["project_id"]).role.value == "discovery"


class TestNotKnowingIsAnAnswer:
    def test_the_recommendation_is_recorded_where_it_can_be_found(
        self, journey: dict[str, Any]
    ) -> None:
        """ "Recommend something reasonable" produces a choice. A choice nobody
        recorded is one nobody can revisit, which is the opposite of "don't
        make it permanent"."""

        assert journey["assumption"]["assumption_id"]
        assert journey["assumption"]["state"] == "proposed"

    def test_the_answer_is_recorded_without_deciding_anything(
        self, journey: dict[str, Any]
    ) -> None:
        """The N36 distinction, at the point it was needed. Recording this as
        an answer would put a decision nobody made into the project."""

        assert journey["answered"]["answer_id"]
        assert journey["answered"]["question_settled"] is False
        assert journey["answered"]["assumption_id"] == journey["assumption"]["assumption_id"]

    def test_the_question_is_not_asked_again(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """A person who says "I don't know yet" and is asked the same thing on
        the next call learns to stop reading the list."""

        again = dispatch(
            context, "kae_get_clarifications", {"project_id": journey["project_id"], "limit": 50}
        )

        assert journey["question"]["clarification_id"] not in {
            item["clarification_id"] for item in again["questions"]
        }

    def test_it_is_still_counted_as_owed(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """Held back is not resolved, and the difference is the whole target."""

        again = dispatch(context, "kae_get_clarifications", {"project_id": journey["project_id"]})

        assert again["deferred"] >= 1


class TestSomethingUsefulComesOut:
    def test_a_context_is_produced_at_zero_readiness(self, journey: dict[str, Any]) -> None:
        """The failure this milestone exists to invert. Nothing confirmed is
        the ordinary state of a project described yesterday."""

        assert journey["preliminary"].get("error") is None
        assert journey["preliminary"]["readiness_percentage"] == 0

    def test_it_carries_what_was_said(self, journey: dict[str, Any]) -> None:
        stated = " ".join(entry["text"] for entry in journey["preliminary"]["stated_verbatim"])

        assert SENTENCE in stated
        assert "I don't know yet" in stated

    def test_it_carries_the_assumption_with_its_consequence(self, journey: dict[str, Any]) -> None:
        assumed = journey["preliminary"]["assumed"]

        assert len(assumed) == 1
        assert "rework" in assumed[0]["disclosure"]

    def test_the_deferred_question_is_disclosed_rather_than_hidden(
        self, journey: dict[str, Any]
    ) -> None:
        """It is held back from the asking list, not from the record. An
        unknown omitted from a disclosure reads as one that does not exist."""

        unknowns = (
            journey["preliminary"]["material_unknowns"]
            + journey["preliminary"]["deferrable_unknowns"]
        )
        found = next(
            u for u in unknowns if u["clarification_id"] == journey["question"]["clarification_id"]
        )

        assert found["disposition"] == "delegated"

    def test_nothing_is_presented_as_confirmed(self, journey: dict[str, Any]) -> None:
        """The line that must hold at every step. Nobody confirmed anything, so
        nothing may appear as confirmed."""

        assert journey["preliminary"]["known"] == []
        assert journey["preliminary"]["is_preliminary"] is True

    def test_it_says_what_it_rests_on(self, journey: dict[str, Any]) -> None:
        assert journey["preliminary"]["warnings"]


class TestReadinessRoseThroughNothing:
    def test_no_knowledge_was_confirmed(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """FR-005, across the whole journey rather than at one seam. A person
        confirms what becomes project knowledge, and nobody did."""

        confirmed = context.memory.retrieve_knowledge(
            ProjectId(journey["project_id"]), lifecycle=LifecycleState.VALIDATED
        )

        assert confirmed == ()

    def test_the_assumption_did_not_become_a_statement(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """The promotion the model forbids. An assumption reaching the
        knowledge table would be a guess a reader takes for a requirement."""

        everything = context.memory.retrieve_knowledge(
            ProjectId(journey["project_id"]), lifecycle=None
        )

        assert not any(
            "markdown files on local disk" in item.current_version.content for item in everything
        )

    def test_readiness_stayed_where_it_was(self, journey: dict[str, Any]) -> None:
        assert journey["preliminary"]["readiness_percentage"] == 0


class TestTheOutputCanBeBuiltOn:
    def test_a_deliverable_was_recorded(self, journey: dict[str, Any]) -> None:
        """A sparse project produces a real, durable output. Withholding one
        until the project looked ready is the gate this system does not have."""

        assert journey["deliverable"]["deliverable_id"]

    def test_it_pins_what_it_rendered(self, journey: dict[str, Any]) -> None:
        """Bytes. Identifiers alone go stale the moment a statement is
        corrected (N20.1)."""

        assert journey["deliverable"]["render_inputs"] is not None

    def test_it_pins_the_uncertainty_it_rested_on(self, journey: dict[str, Any]) -> None:
        """The claim (N20.2). This package rested on a delegated question and
        an unaccepted assumption, and the identical bytes will read as settled
        once those are settled."""

        provisional = journey["deliverable"]["provisional_context"]

        assert provisional is not None
        assert journey["deliverable"]["rested_on_uncertainty"] is True
        assert provisional["question_pins"]

    def test_the_assumption_is_pinned_unaccepted(self, journey: dict[str, Any]) -> None:
        pins = {
            pin["assumption_id"]: pin["state"]
            for pin in journey["deliverable"]["provisional_context"]["assumption_pins"]
        }

        assert pins[journey["assumption"]["assumption_id"]] == "proposed"

    def test_settling_it_later_does_not_rewrite_the_record(
        self, context: tools.ToolContext, journey: dict[str, Any]
    ) -> None:
        """Historical reproduction never consults current knowledge. An
        improved package is a new deliverable; the old one keeps saying what it
        said, which is the only reason it is worth keeping."""

        dispatch(
            context,
            "kae_accept_assumption",
            {
                "project_id": journey["project_id"],
                "assumption_id": journey["assumption"]["assumption_id"],
                "actor": "cris",
            },
        )

        listed = dispatch(context, "kae_list_deliverables", {"project_id": journey["project_id"]})
        recorded = next(
            item
            for item in listed["results"]
            if item["deliverable_id"] == journey["deliverable"]["deliverable_id"]
        )
        pins = {
            pin["assumption_id"]: pin["state"]
            for pin in recorded["provisional_context"]["assumption_pins"]
        }

        assert pins[journey["assumption"]["assumption_id"]] == "proposed"
