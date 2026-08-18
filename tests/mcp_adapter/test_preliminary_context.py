"""Useful output from a project that has almost nothing (N44).

The manual test this closes: one sentence submitted, every subsystem behaving
correctly, and nothing useful produced. The candidates were in one place, the
assumptions in another, the questions in a third, and assembly showed only
confirmed knowledge — of which there was none. Nothing composed them.

What these assertions defend is **not** the quality of any interpretation. No
count of questions, no particular assumption, no wording. A test asserting "two
questions" would be asserting a model's taste and would fail on a better answer.

What is asserted is composition and epistemic integrity:

    something useful comes back from a project at 0% readiness;
    the original sentence survives verbatim;
    known, proposed, assumed and unknown stay four separate things;
    nothing is confirmed by being read;
    readiness does not move;
    what a person deferred is disclosed, not hidden.
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
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.assumptions import Consequence
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch

SENTENCE = "I want an inbox where I can dump thoughts and have them turned into useful things."


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
        preliminary=PreliminaryContextService(factory),
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    project_id = str(context.memory.create_project("Sparse Inbox", key="n44-inbox").id)
    dispatch(
        context,
        "kae_submit_observation",
        {
            "project_id": project_id,
            "observation": SENTENCE,
            "idempotency_key": "n44-1",
            # The extraction path is N42's and needs a worker to run. What N44
            # composes is whatever state exists, so this test does not wait on
            # a model — it asserts the composition, not the interpretation.
            "generation_policy": {"discovery_extraction": "disabled"},
        },
    )
    return project_id


CANDIDATE = "Captured thoughts are stored as markdown files."


def _propose(context: tools.ToolContext, project_id: str, text: str = CANDIDATE) -> str:
    """A candidate: written by a run, area-assigned, and left unconfirmed.

    Area-assigned because unassigned knowledge assembles to nothing, and a test
    over an empty assembly passes every assertion vacuously.
    """

    run = context.memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "n44-propose")
    written = context.memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, text, "seed")]
    )
    context.readiness.assign_area(
        ProjectId(project_id), written[0].id, "constraints_and_assumptions"
    )
    return str(written[0].id)


def _compose(context: tools.ToolContext, project_id: str, **extra: Any) -> dict[str, Any]:
    return dispatch(context, "kae_get_preliminary_context", {"project_id": project_id, **extra})


class TestItProducesSomethingFromAlmostNothing:
    def test_a_project_with_one_sentence_gets_a_context(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The manual test's failure, inverted. Zero confirmed statements is
        the ordinary state of a new project, not a reason to return nothing."""

        payload = _compose(context, project_id)

        assert payload["project_name"] == "Sparse Inbox"
        assert payload["stated_verbatim"]

    def test_zero_readiness_does_not_refuse(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The gate this system deliberately does not have. Low readiness
        produces a thinner context, never an error."""

        payload = _compose(context, project_id)

        assert payload.get("error") is None
        assert payload["readiness_percentage"] == 0

    def test_the_original_sentence_survives_verbatim(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Everything else in the document is derived from it, and a
        preliminary context is far likelier to be wrong in its interpretation
        than in its transcription. A reader who sees the sentence can catch
        that; one who does not, cannot."""

        payload = _compose(context, project_id)

        assert any(SENTENCE in stated["text"] for stated in payload["stated_verbatim"])

    def test_a_relayed_observation_is_not_presented_as_first_hand(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """An agent submitted this sentence on a person's behalf. Recording it
        as though a person typed it into KAE would overstate the evidence, and
        the actor is the only thing that keeps the two apart."""

        payload = _compose(context, project_id)

        relayed = next(s for s in payload["stated_verbatim"] if SENTENCE in s["text"])
        assert relayed["actor_type"] == "agent"

    def test_it_says_it_is_preliminary(self, context: tools.ToolContext, project_id: str) -> None:
        payload = _compose(context, project_id)

        assert payload["is_preliminary"] is True

    def test_it_names_what_it_rests_on(self, context: tools.ToolContext, project_id: str) -> None:
        """Generation may be incomplete; it may never be silent."""

        payload = _compose(context, project_id)

        assert payload["warnings"]
        assert any("confirmed" in warning for warning in payload["warnings"])

    def test_an_empty_project_still_answers(self, context: tools.ToolContext) -> None:
        """Nothing to say is a legitimate answer, and is not the same event as
        declining to speak because knowledge was judged insufficient."""

        empty = str(context.memory.create_project("Nothing Yet", key="n44-empty").id)

        payload = _compose(context, empty)

        assert payload.get("error") is None
        assert payload["stated_verbatim"] == []


class TestTheFourThingsNeverMerge:
    def test_known_and_proposed_are_separate_collections(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _compose(context, project_id)

        assert "known" in payload and "proposed" in payload
        assert payload["known"] == []

    def test_a_candidate_arrives_as_proposed_and_not_as_known(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The whole point. An unconfirmed statement is included — because a
        project with none confirmed is otherwise unserviceable — and it is
        included *as* unconfirmed."""

        _propose(context, project_id)

        payload = _compose(context, project_id)

        texts = {statement["text"] for statement in payload["proposed"]}
        assert CANDIDATE in texts
        assert all(statement["inclusion_class"] != "confirmed" for statement in payload["proposed"])
        assert payload["known"] == []

    def test_an_assumption_arrives_with_its_consequence(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """ "We assumed single-tenant" invites a nod. The same line with what it
        would cost to be wrong invites a decision, and no renderer may drop
        that half."""

        dispatch(
            context,
            "kae_record_assumption",
            {
                "project_id": project_id,
                "subject": "storage",
                "assumed_value": "markdown files on local disk",
                "reason": "a prototype needs no database",
                "origin": "inferred",
                "consequence": Consequence.REWORK.value,
            },
        )

        payload = _compose(context, project_id)

        assert len(payload["assumed"]) == 1
        entry = payload["assumed"][0]
        assert entry["consequence"] == Consequence.REWORK.value
        assert entry["reversible"] is True
        assert Consequence.REWORK.value in entry["disclosure"]

    def test_an_assumption_says_what_brings_it_back(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The same answer the HTTP reader gets, or the two paths describe
        different projects.

        A **non-default** trigger, so a hop that dropped the field and fell
        back to `on_request` fails here rather than passing (`D-290`).
        """

        dispatch(
            context,
            "kae_record_assumption",
            {
                "project_id": project_id,
                "subject": "storage",
                "assumed_value": "markdown files on local disk",
                "reason": "a prototype needs no database",
                "origin": "inferred",
                "revisit": "before_build",
            },
        )

        payload = _compose(context, project_id)

        assert payload["assumed"][0]["revisit"] == "before_build"

    def test_assumptions_are_not_in_known_or_proposed(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A guess that reaches the statement list is a guess that will be read
        as a requirement."""

        dispatch(
            context,
            "kae_record_assumption",
            {
                "project_id": project_id,
                "subject": "storage",
                "assumed_value": "markdown files on local disk",
                "reason": "a prototype needs no database",
                "origin": "inferred",
            },
        )

        payload = _compose(context, project_id)

        rendered = {s["text"] for s in payload["known"]} | {s["text"] for s in payload["proposed"]}
        assert "markdown files on local disk" not in rendered

    def test_unknowns_are_split_by_consequence(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Ten helpful questions must never make a project look blocked, and
        merging them with the material ones is how that happens."""

        payload = _compose(context, project_id)

        assert "material_unknowns" in payload
        assert "deferrable_unknowns" in payload
        assert payload["material_unknowns"] or payload["deferrable_unknowns"]

    def test_material_unknowns_do_not_block(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """They are disclosed and the context is produced anyway. Material
        means "spend a person's attention here first", never "stop"."""

        payload = _compose(context, project_id)

        assert payload["material_unknowns"]
        assert payload.get("error") is None


class TestReadingIsNotDeciding:
    def test_nothing_is_confirmed_by_composing(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _propose(context, project_id)

        _compose(context, project_id)

        remaining = context.memory.retrieve_knowledge(
            ProjectId(project_id), lifecycle=LifecycleState.PROPOSED
        )
        assert len(remaining) == 1

    def test_readiness_does_not_move(self, context: tools.ToolContext, project_id: str) -> None:
        """Readiness rises through confirmation a person performs. A read that
        moved it would be manufacturing progress."""

        before = context.readiness.knowledge_revision(ProjectId(project_id))

        _compose(context, project_id)

        assert context.readiness.knowledge_revision(ProjectId(project_id)) == before

    def test_the_response_says_knowledge_did_not_change(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _compose(context, project_id)

        assert payload["knowledge_changed"] is False

    def test_an_accepted_assumption_is_still_not_confirmed_knowledge(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Accepting says someone is willing to build on a guess. It stays in
        `assumed` and never becomes a statement (FR-005)."""

        recorded = dispatch(
            context,
            "kae_record_assumption",
            {
                "project_id": project_id,
                "subject": "storage",
                "assumed_value": "markdown files on local disk",
                "reason": "a prototype needs no database",
                "origin": "inferred",
            },
        )
        dispatch(
            context,
            "kae_accept_assumption",
            {
                "project_id": project_id,
                "assumption_id": recorded["assumption_id"],
                "actor": "cris",
            },
        )

        payload = _compose(context, project_id)

        assert payload["assumed"][0]["state"] == "accepted"
        assert payload["known"] == []


class TestWhatWasDeferredIsDisclosed:
    def test_a_deferred_question_appears_as_an_unknown(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Held back from the *asking* list so a person is not re-asked every
        call (N36). A context document is not asking, it is disclosing, and an
        unknown omitted from a disclosure reads as one that does not exist."""

        listed = dispatch(context, "kae_get_clarifications", {"project_id": project_id, "limit": 1})
        question_id = listed["questions"][0]["clarification_id"]
        dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": question_id,
                "answer": "I don't know yet.",
                "disposition": "unknown_by_user",
            },
        )

        payload = _compose(context, project_id)

        unknowns = payload["material_unknowns"] + payload["deferrable_unknowns"]
        found = next(u for u in unknowns if u["clarification_id"] == question_id)
        assert found["disposition"] == "unknown_by_user"

    def test_an_answered_question_stops_being_an_unknown(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        listed = dispatch(context, "kae_get_clarifications", {"project_id": project_id, "limit": 1})
        question_id = listed["questions"][0]["clarification_id"]
        dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": question_id,
                "answer": "Markdown files on disk.",
            },
        )

        payload = _compose(context, project_id)

        unknowns = payload["material_unknowns"] + payload["deferrable_unknowns"]
        assert question_id not in {u["clarification_id"] for u in unknowns}

    def test_what_a_person_said_while_deferring_is_kept_verbatim(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """ "I don't know yet, but not for a prototype" is a statement about the
        project even though it decided nothing."""

        listed = dispatch(context, "kae_get_clarifications", {"project_id": project_id, "limit": 1})
        dispatch(
            context,
            "kae_answer_clarification",
            {
                "project_id": project_id,
                "clarification_id": listed["questions"][0]["clarification_id"],
                "answer": "I don't know yet, but nothing heavyweight for a prototype.",
                "disposition": "unknown_by_user",
            },
        )

        payload = _compose(context, project_id)

        assert any("nothing heavyweight" in stated["text"] for stated in payload["stated_verbatim"])


class TestItCanBeBuiltOn:
    def test_it_carries_the_pins_it_read(self, context: tools.ToolContext, project_id: str) -> None:
        """A deliverable recorded from preliminary context must be reproducible
        in fact rather than in appearance: identifiers alone go stale the moment
        a statement is corrected (N20.1)."""

        _propose(context, project_id)

        payload = _compose(context, project_id)

        assert payload["statement_pins"]
        assert all(pin["version"] >= 1 and pin["knowledge_id"] for pin in payload["statement_pins"])

    def test_it_carries_a_content_hash_and_package_id(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        payload = _compose(context, project_id)

        assert payload["content_hash"]
        assert payload["package_id"]

    def test_an_unknown_purpose_is_refused(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Guessing which areas a caller meant would silently compose the wrong
        document, and a wrong document is harder to notice than an error."""

        payload = _compose(context, project_id, purpose="vibes")

        assert payload["error"] == "invalid_argument"


class TestTheContractIsDiscoverable:
    def test_the_tool_is_declared(self) -> None:
        assert "kae_get_preliminary_context" in {d["name"] for d in TOOL_DEFINITIONS}

    def test_the_description_says_it_never_refuses(self) -> None:
        """An agent reads this before deciding whether a sparse project is
        worth asking about, and the wrong reading is "not yet"."""

        declaration = next(
            d for d in TOOL_DEFINITIONS if d["name"] == "kae_get_preliminary_context"
        )

        assert "Never refuses" in declaration["description"]

    def test_the_description_says_nothing_is_confirmed(self) -> None:
        declaration = next(
            d for d in TOOL_DEFINITIONS if d["name"] == "kae_get_preliminary_context"
        )

        assert "confirmed" in declaration["description"]
