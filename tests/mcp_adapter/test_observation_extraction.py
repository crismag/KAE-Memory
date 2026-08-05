"""An observation reaches extraction (N42).

The manual test that produced this target failed with every subsystem behaving
correctly: a sentence was stored verbatim, classified honestly as unclassified,
and assembled to nothing — because `kae_submit_observation` enqueued no
extraction. Extraction was reachable from documents and from clarification
answers and from nowhere else.

This is the edge. What it does *not* do is make the interpretation good: the run
uses `requirements.v1`, which is tuned for requirement-bearing text and will
read a sparse product sentence thinly. That is correct behaviour for that prompt
and is what N46's discovery role exists to change.

So the assertions here are about the **path and its honesty**, not about what a
model says:

    the observation stays verbatim;
    a run is queued and identified;
    a retry reuses it;
    the policy can turn it off, and says so distinguishably;
    nothing is confirmed.
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
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.identifiers import ProjectId
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
    )


@pytest.fixture
def project_id(context: tools.ToolContext) -> str:
    return str(context.memory.create_project("Sparse Inbox", key="n42-inbox").id)


def _submit(
    context: tools.ToolContext, project_id: str, key: str = "n42-1", **extra: Any
) -> dict[str, Any]:
    return dispatch(
        context,
        "kae_submit_observation",
        {
            "project_id": project_id,
            "observation": SENTENCE,
            "idempotency_key": key,
            **extra,
        },
    )


class TestTheEdgeExists:
    def test_a_submitted_observation_queues_extraction(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """The single change the failed manual test was missing."""

        payload = _submit(context, project_id)

        assert payload["extraction"]["queued"] is True
        assert payload["extraction"]["run_id"]

    def test_the_run_exists_and_is_pending(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Queued work is not done work, and the response must not blur that."""

        payload = _submit(context, project_id)

        runs = context.memory.runs_for_project(ProjectId(project_id))
        assert [run.role for run in runs] == [AgentRole.DISCOVERY]
        assert {run.status for run in runs} == {RunStatus.PENDING}
        assert payload["extraction"]["status"] == RunStatus.PENDING.value

    def test_the_run_names_the_observation_it_will_read(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Provenance starts here: a candidate must trace to stored text."""

        payload = _submit(context, project_id)

        run = context.memory.runs_for_project(ProjectId(project_id))[0]
        assert run.input_context is not None
        assert run.input_context["message_id"] == payload["message_id"]
        assert run.input_context["source"] == "observation"


class TestEvidenceIsUntouched:
    def test_the_observation_is_stored_verbatim(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Extraction derives beside the evidence, never over it."""

        payload = _submit(context, project_id)

        messages = context.memory.messages_for_session(payload["session_id"])
        assert any(message.content.startswith(SENTENCE) for message in messages)

    def test_queuing_extraction_creates_no_knowledge(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Queued is not read, and read would not be confirmed either."""

        _submit(context, project_id)

        assert context.memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()

    def test_readiness_does_not_move(self, context: tools.ToolContext, project_id: str) -> None:
        before = context.readiness.knowledge_revision(ProjectId(project_id))

        _submit(context, project_id)

        assert context.readiness.knowledge_revision(ProjectId(project_id)) == before


class TestIdempotence:
    def test_a_retry_reuses_the_run(self, context: tools.ToolContext, project_id: str) -> None:
        """A second model call for the same sentence is money for nothing, and
        a second set of candidates is a review queue nobody asked for."""

        first = _submit(context, project_id)
        second = _submit(context, project_id)

        assert second["extraction"]["run_id"] == first["extraction"]["run_id"]
        assert len(context.memory.runs_for_project(ProjectId(project_id))) == 1

    def test_a_different_observation_gets_its_own_run(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        _submit(context, project_id, key="n42-a")
        _submit(context, project_id, key="n42-b")

        assert len(context.memory.runs_for_project(ProjectId(project_id))) == 2


class TestThePolicyDecides:
    def test_the_default_extracts(self, context: tools.ToolContext, project_id: str) -> None:
        """The useful case is not the one a caller must know to ask for."""

        payload = _submit(context, project_id)

        assert payload["extraction"]["generation_policy"] == {
            "discovery_extraction": "on_submission"
        }

    def test_disabled_skips_and_says_why(self, context: tools.ToolContext, project_id: str) -> None:
        """A policy choice must not be indistinguishable from a broken server."""

        payload = _submit(
            context,
            project_id,
            generation_policy={"discovery_extraction": "disabled"},
        )

        assert payload["extraction"]["queued"] is False
        assert "disabled" in payload["extraction"]["reason"]
        assert not context.memory.runs_for_project(ProjectId(project_id))

    def test_the_observation_is_still_recorded_when_extraction_is_off(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Opting out of interpretation is not opting out of evidence."""

        payload = _submit(
            context,
            project_id,
            generation_policy={"discovery_extraction": "disabled"},
        )

        assert payload["message_id"]
        messages = context.memory.messages_for_session(payload["session_id"])
        assert any(message.content.startswith(SENTENCE) for message in messages)

    def test_an_unsupported_policy_is_refused(
        self, context: tools.ToolContext, project_id: str
    ) -> None:
        """Ignoring it would let a caller believe they configured something."""

        payload = _submit(
            context, project_id, generation_policy={"assumption_authority": "delegate"}
        )

        assert payload["error"] == "invalid_argument"

    def test_the_schema_offers_the_policy(self) -> None:
        definition = next(d for d in TOOL_DEFINITIONS if d["name"] == "kae_submit_observation")
        policy = definition["inputSchema"]["properties"]["generation_policy"]

        assert set(policy["properties"]["discovery_extraction"]["enum"]) == {
            "on_submission",
            "disabled",
        }
        assert policy["additionalProperties"] is False
