"""Closing the classification lifecycle (N4).

T24 shipped a write surface ahead of its read and review surface. Three
consequences, all of which this file exists to remove:

    classified spans and operational records were readable only through the
    briefing, which cannot be filtered or paged;

    the domain modelled `active`, `resolved`, `expired`, and `rejected` and no
    adapter could reach any of them, so every record stayed `proposed` for ever;

    `supersede_older_versions` had no caller, so the versioning guarantee the
    design records was true of the repository and not of the system.

The invariant that survives all of it: **settling is not verifying.** Accepting
a reported milestone completion records that a person took responsibility for
the claim. It does not make the claim true, and the record keeps saying who
reported it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.observation import (
    InvalidOperationalTransitionError,
    OperationalState,
    ensure_operational_transition,
)
from kae_memory.mcp import tools
from kae_memory.mcp.server import TOOL_DEFINITIONS, dispatch


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
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Ops", key="n4-ops").id)


def _submit(context: tools.ToolContext, project_id: str, text: str, key: str) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_submit_observation",
        {"project_id": project_id, "observation": text, "idempotency_key": key},
    )


def _first_record(context: tools.ToolContext, project_id: str) -> dict[str, Any]:
    page = dispatch(context, "kae_get_operational_state", {"project_id": project_id})
    assert page["results"], "the fixture must produce an operational record"
    return dict(page["results"][0])


class TestTheTransitionRules:
    def test_a_proposal_can_be_accepted_refused_or_lapse(self) -> None:
        for target in (
            OperationalState.ACTIVE,
            OperationalState.REJECTED,
            OperationalState.EXPIRED,
        ):
            ensure_operational_transition(OperationalState.PROPOSED, target)

    def test_a_proposal_cannot_jump_to_resolved(self) -> None:
        """Resolving what nobody accepted records an outcome for work never taken on."""

        with pytest.raises(InvalidOperationalTransitionError):
            ensure_operational_transition(OperationalState.PROPOSED, OperationalState.RESOLVED)

    def test_terminal_states_are_terminal(self) -> None:
        """ "Resolved for now" and "resolved" must not be the same word.

        A recurrence is a new record with its own evidence, not a reopening
        that erases the fact that this one closed.
        """

        for state in (
            OperationalState.RESOLVED,
            OperationalState.EXPIRED,
            OperationalState.REJECTED,
        ):
            with pytest.raises(InvalidOperationalTransitionError) as raised:
                ensure_operational_transition(state, OperationalState.ACTIVE)
            assert "terminal" in str(raised.value)


class TestTheReadsAreFilterableAndPageable:
    def test_operational_state_is_readable_without_the_briefing(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "M8 is complete.", "n4-read-1")

        page = dispatch(context, "kae_get_operational_state", {"project_id": project_id})

        assert page["total"] >= 1
        assert page["results"][0]["kind"] == "milestone_transition"

    def test_it_pages(self, context: tools.ToolContext, project_id: str) -> None:
        for index in range(4):
            _submit(context, project_id, f"M{index} is complete.", f"n4-page-{index}")

        page = dispatch(
            context, "kae_get_operational_state", {"project_id": project_id, "limit": 2}
        )

        assert page["total"] >= 4
        assert len(page["results"]) == 2
        assert page["cursor"] is not None

    def test_it_filters_by_subject(self, context: tools.ToolContext, project_id: str) -> None:
        _submit(context, project_id, "M8 is complete.", "n4-subj-1")
        _submit(context, project_id, "M9 is blocked.", "n4-subj-2")

        page = dispatch(
            context, "kae_get_operational_state", {"project_id": project_id, "subject": "M8"}
        )

        assert page["total"] == 1
        assert page["results"][0]["subject"] == "M8"

    def test_the_default_is_the_current_state_of_the_work(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        page = dispatch(context, "kae_get_operational_state", {"project_id": project_id})

        assert set(page["filters"]["states"]) == {"proposed", "active"}

    def test_classifications_are_readable_and_pageable(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "M8 is complete. To God be the glory!", "n4-cls-1")

        page = dispatch(context, "kae_get_classifications", {"project_id": project_id, "limit": 1})

        assert page["total"] >= 2
        assert len(page["results"]) == 1
        assert page["results"][0]["span"]["end"] > page["results"][0]["span"]["start"]

    def test_classifications_filter_by_tier(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "M8 is complete. To God be the glory!", "n4-cls-2")

        page = dispatch(
            context, "kae_get_classifications", {"project_id": project_id, "tiers": ["evidence"]}
        )

        assert page["results"]
        assert all(row["retention_tier"] == "evidence" for row in page["results"])

    def test_the_read_still_says_it_is_not_semantic(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        page = dispatch(context, "kae_get_classifications", {"project_id": project_id})

        assert page["semantic_classification"] is False


class TestSettling:
    def test_a_proposed_record_can_be_accepted(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "M8 is complete.", "n4-settle-1")
        record = _first_record(context, project_id)

        settled = dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": record["operational_update_id"],
                "state": "active",
                "actor": "cris",
            },
        )

        assert settled["state"] == "active"

    def test_settling_is_not_verifying(self, context: tools.ToolContext, project_id: str) -> None:
        """The invariant the whole file protects.

        A person accepting a reported completion has taken responsibility for
        the claim. The claim is still a report, and the record must keep saying
        so — otherwise "someone agreed" becomes indistinguishable from "the
        tests passed".
        """

        _submit(context, project_id, "The suite passed on T1.", "n4-settle-2")
        record = next(
            row
            for row in dispatch(context, "kae_get_operational_state", {"project_id": project_id})[
                "results"
            ]
            if row["kind"] == "test_result"
        )

        settled = dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": record["operational_update_id"],
                "state": "active",
                "actor": "cris",
            },
        )

        assert settled["verification"] == "reported"
        assert settled["authority"] == "agent_reported"
        assert settled["knowledge_changed"] is False

    def test_an_impermissible_transition_is_refused(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, "M8 is complete.", "n4-settle-3")
        record = _first_record(context, project_id)

        refused = dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": record["operational_update_id"],
                "state": "resolved",
                "actor": "cris",
            },
        )

        assert refused["error"] == "invalid_state_transition"

    def test_an_actor_is_required(self, context: tools.ToolContext, project_id: str) -> None:
        """The same rule confirmation rests on: a decision names who made it."""

        _submit(context, project_id, "M8 is complete.", "n4-settle-4")
        record = _first_record(context, project_id)

        refused = dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": record["operational_update_id"],
                "state": "active",
                "actor": "  ",
            },
        )

        assert refused["error"] == "invalid_argument"

    def test_the_settlement_history_accumulates(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """A record keeping only its latest decision cannot say who changed their mind."""

        _submit(context, project_id, "M8 is complete.", "n4-settle-5")
        record = _first_record(context, project_id)
        identifier = record["operational_update_id"]

        dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": identifier,
                "state": "active",
                "actor": "cris",
                "note": "accepted from the report",
            },
        )
        dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": identifier,
                "state": "resolved",
                "actor": "cris",
            },
        )

        page = dispatch(
            context,
            "kae_get_operational_state",
            {"project_id": project_id, "states": ["resolved"]},
        )
        settlements = page["results"][0]["settlements"]
        assert [s["to"] for s in settlements] == ["active", "resolved"]
        assert settlements[0]["actor"] == "cris"

    def test_a_settled_record_leaves_the_briefing(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Resolved records stay readable; they stop describing the project."""

        _submit(context, project_id, "M8 is complete.", "n4-settle-6")
        identifier = _first_record(context, project_id)["operational_update_id"]
        for state in ("active", "resolved"):
            dispatch(
                context,
                "kae_settle_operational_record",
                {
                    "project_id": project_id,
                    "operational_update_id": identifier,
                    "state": state,
                    "actor": "cris",
                },
            )

        briefing = dispatch(context, "kae_get_project_briefing", {"project_id": project_id})

        assert briefing["tiers"]["operational_state"] == []

    def test_another_projects_record_is_not_reachable(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """An id alone must not cross a project boundary."""

        _submit(context, project_id, "M8 is complete.", "n4-settle-7")
        identifier = _first_record(context, project_id)["operational_update_id"]
        other = str(context.memory.create_project("Other", key="n4-other").id)

        refused = dispatch(
            context,
            "kae_settle_operational_record",
            {
                "project_id": other,
                "operational_update_id": identifier,
                "state": "active",
                "actor": "cris",
            },
        )

        assert refused["error"] == "knowledge_not_found"


class TestSupersessionHasACaller:
    def test_an_upgraded_classifier_retires_the_previous_result_set(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The guarantee T24 documented and did not wire.

        Rows are marked, never deleted: a reviewer's decision was made against
        what they saw, and a history view has to show which version produced it.
        """

        from kae_memory.agents.observation_classifier import DeterministicObservationClassifier
        from kae_memory.domain.identifiers import MessageId
        from kae_memory.persistence.classification_repository import ClassificationRepository

        readiness = ReadinessService(factory)
        readiness.install_template()
        memory = MemoryService(factory)
        first = ClassificationService(factory)
        context = tools.ToolContext(
            memory=memory,
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
            classification=first,
        )
        project = context.memory.create_project("Upgrade", key="n4-upgrade")
        submitted = _submit(context, str(project.id), "M8 is complete.", "n4-upgrade-1")
        message_id = MessageId(submitted["message_id"])

        class Upgraded(DeterministicObservationClassifier):
            @property
            def version(self) -> str:
                return "2.0"

        ClassificationService(factory, Upgraded()).classify(
            ProjectId(str(project.id)), message_id, "M8 is complete."
        )

        with factory() as session:
            rows = ClassificationRepository(session).for_message(message_id)
            old = [row for row in rows if row.classifier_version == "1.0"]
            new = [row for row in rows if row.classifier_version == "2.0"]

        assert old, "the previous result set must survive"
        assert all(row.superseded_by_version == "2.0" for row in old)
        assert new and all(row.superseded_by_version is None for row in new)

    def test_rerunning_the_same_version_supersedes_nothing(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        from kae_memory.domain.identifiers import MessageId
        from kae_memory.persistence.classification_repository import ClassificationRepository

        submitted = _submit(context, project_id, "M8 is complete.", "n4-same-1")
        assert context.classification is not None
        context.classification.classify(
            ProjectId(project_id), MessageId(submitted["message_id"]), "M8 is complete."
        )

        with context.memory._session_factory() as session:
            rows = ClassificationRepository(session).for_message(MessageId(submitted["message_id"]))

        assert rows
        assert all(row.superseded_by_version is None for row in rows)


class TestRegistration:
    def test_the_tools_are_declared(self) -> None:
        declared = {definition["name"] for definition in TOOL_DEFINITIONS}

        assert {
            "kae_get_operational_state",
            "kae_get_classifications",
            "kae_settle_operational_record",
        } <= declared

    def test_settling_declares_only_permitted_targets(self) -> None:
        """`proposed` is where a record starts, not somewhere it can be put back."""

        definition = next(
            d for d in TOOL_DEFINITIONS if d["name"] == "kae_settle_operational_record"
        )

        assert set(definition["inputSchema"]["properties"]["state"]["enum"]) == {
            "active",
            "resolved",
            "expired",
            "rejected",
        }

    def test_the_capability_gap_is_reported_when_unwired(
        self, factory: sessionmaker[Session]
    ) -> None:
        readiness = ReadinessService(factory)
        readiness.install_template()
        bare = tools.ToolContext(
            memory=MemoryService(factory),
            blueprint=BlueprintService(factory),
            readiness=readiness,
            review=ReviewService(factory),
        )
        project = bare.memory.create_project("Bare", key="n4-bare")

        payload = dispatch(
            context=bare,
            name="kae_get_operational_state",
            arguments={"project_id": str(project.id)},
        )

        assert payload["error"] == "capability_unavailable"
