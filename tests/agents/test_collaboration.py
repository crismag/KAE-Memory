"""The M6 collaboration proof.

One agent's confirmed output becomes another agent's input, with the handoff
carried entirely by the database. No test here opens a socket.
"""

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents import (
    ArchitectureAgent,
    DeterministicExtractionAdapter,
    ExtractionRequest,
    RequirementsAgent,
    UnverifiableOutputError,
)
from kae_memory.application import MemoryService
from kae_memory.domain.execution import AgentRole, RunStatus
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind, ProvenanceLinkType
from kae_memory.domain.workspace import SessionType

BRIEF = (
    "Ministry coordinators file reports every month, but the reporting cycle "
    "should be configurable. We do not know yet who approves a submitted report."
)


def _requirements_fixture(request: ExtractionRequest) -> dict[str, Any]:
    return {
        "items": [
            {
                "kind": "rule",
                "content": "The reporting cycle is configurable.",
                "confidence": "high",
                "source_quote": "the reporting cycle should be configurable",
            },
            {
                "kind": "unknown",
                "content": "Who approves a submitted report is undecided.",
                "confidence": "high",
                "source_quote": "We do not know yet who approves a submitted report",
            },
        ]
    }


def _architecture_fixture(request: ExtractionRequest) -> dict[str, Any]:
    quote = request.source_text.splitlines()[0]
    return {
        "items": [
            {
                "kind": "decision",
                "content": "Store the reporting cycle as project configuration.",
                "confidence": "medium",
                "source_quote": quote,
                "rationale": "Derived from the confirmed configurability rule.",
            }
        ]
    }


def test_architecture_agent_uses_requirements_confirmed_in_an_earlier_session(
    factory: sessionmaker[Session],
) -> None:
    """AT-006. The handoff crosses a session boundary through the database."""

    # --- Session one: extract and confirm -----------------------------------
    service_a = MemoryService(factory)
    project = service_a.create_project("Ministry reporting", key="ministry")
    discovery = service_a.open_session(project.id, SessionType.DISCOVERY)
    message = service_a.record_message(project.id, discovery.id, BRIEF).message

    requirements = RequirementsAgent(
        service_a, DeterministicExtractionAdapter(_requirements_fixture)
    )
    extracted = requirements.run_on_message(
        project.id, discovery.id, message.id, BRIEF, "requirements-1"
    )

    assert extracted.run.status is RunStatus.SUCCEEDED
    assert {item.kind for item in extracted.items} == {"rule", "unknown"}

    rule = next(item for item in extracted.items if item.kind == KnowledgeKind.RULE)
    service_a.confirm_knowledge(rule.id)
    service_a.close_session(discovery.id)

    # --- Session one's process ends -----------------------------------------
    del service_a, requirements, extracted

    # --- Session two: derive architecture from confirmed knowledge only -----
    service_b = MemoryService(factory)
    architecture_session = service_b.open_session(project.id, SessionType.ARCHITECTURE)
    architecture = ArchitectureAgent(
        service_b, DeterministicExtractionAdapter(_architecture_fixture)
    )
    derived = architecture.run_on_confirmed_knowledge(
        project.id, architecture_session.id, "architecture-1"
    )

    assert derived.run.status is RunStatus.SUCCEEDED
    assert derived.run.role is AgentRole.ARCHITECTURE
    assert len(derived.items) == 1

    decision = derived.items[0]
    assert decision.kind == KnowledgeKind.DECISION
    # The decision cites the confirmed requirement, not the raw conversation.
    assert decision.current_version.provenance.source == "The reporting cycle is configurable."

    # The consumption is recorded relationally, not inferred.
    links = service_b.provenance_for_item(rule.id)
    used_by = [link for link in links if link.link_type is ProvenanceLinkType.USED_BY]
    assert [link.agent_run_id for link in used_by] == [derived.run.id]


def test_architecture_agent_ignores_unconfirmed_candidates(
    factory: sessionmaker[Session],
) -> None:
    """A project with nothing confirmed yields no decisions, not speculation."""

    service = MemoryService(factory)
    project = service.create_project("Unconfirmed", key="unconfirmed")
    session = service.open_session(project.id, SessionType.DISCOVERY)
    message = service.record_message(project.id, session.id, BRIEF).message

    RequirementsAgent(
        service, DeterministicExtractionAdapter(_requirements_fixture)
    ).run_on_message(project.id, session.id, message.id, BRIEF, "requirements-1")
    # Nothing confirmed.

    extractor = DeterministicExtractionAdapter(_architecture_fixture)
    derived = ArchitectureAgent(service, extractor).run_on_confirmed_knowledge(
        project.id, session.id, "architecture-1"
    )

    assert derived.items == ()
    assert derived.run.status is RunStatus.SUCCEEDED
    assert derived.run.output_summary == {
        "items_written": 0,
        "reason": "no_confirmed_knowledge",
    }
    # The extractor was never called — there was nothing authoritative to derive from.
    assert extractor.call_count == 0


def test_fabricated_source_quote_fails_the_run_and_writes_nothing(
    factory: sessionmaker[Session],
) -> None:
    """Knowledge that misstates its own provenance must never be written."""

    def fabricating(request: ExtractionRequest) -> dict[str, Any]:
        return {
            "items": [
                {
                    "kind": "requirement",
                    "content": "Reports must be approved by the finance director.",
                    "confidence": "high",
                    "source_quote": "reports are approved by the finance director",
                }
            ]
        }

    service = MemoryService(factory)
    project = service.create_project("Fabrication", key="fabrication")
    session = service.open_session(project.id, SessionType.DISCOVERY)
    message = service.record_message(project.id, session.id, BRIEF).message
    agent = RequirementsAgent(service, DeterministicExtractionAdapter(fabricating))

    with pytest.raises(UnverifiableOutputError):
        agent.run_on_message(project.id, session.id, message.id, BRIEF, "requirements-1")

    assert service.retrieve_knowledge(project.id, lifecycle=None) == ()
    runs = service.runs_for_project(project.id)
    assert len(runs) == 1
    assert runs[0].status is RunStatus.FAILED
    assert runs[0].error_code == "unverifiable_output"


def test_run_records_prompt_and_schema_versions(factory: sessionmaker[Session]) -> None:
    """Every item traces to the exact prompt that produced it."""

    service = MemoryService(factory)
    project = service.create_project("Versions", key="versions")
    session = service.open_session(project.id, SessionType.DISCOVERY)
    message = service.record_message(project.id, session.id, BRIEF).message

    outcome = RequirementsAgent(
        service, DeterministicExtractionAdapter(_requirements_fixture)
    ).run_on_message(project.id, session.id, message.id, BRIEF, "requirements-1")

    summary = outcome.run.output_summary or {}
    assert summary["prompt_version"] == "requirements.v1"
    assert summary["schema_version"] == "extraction.v1"
    assert summary["items_written"] == 2


def test_extraction_is_idempotent_by_key(factory: sessionmaker[Session]) -> None:
    """Re-submitting the same extraction produces one run and one result set."""

    service = MemoryService(factory)
    project = service.create_project("Replay", key="replay")
    session = service.open_session(project.id, SessionType.DISCOVERY)
    message = service.record_message(project.id, session.id, BRIEF).message
    agent = RequirementsAgent(service, DeterministicExtractionAdapter([_requirements_fixture] * 2))

    first = agent.run_on_message(project.id, session.id, message.id, BRIEF, "requirements-1")
    second = agent.run_on_message(project.id, session.id, message.id, BRIEF, "requirements-1")

    assert first.run.id == second.run.id
    assert len(service.runs_for_project(project.id)) == 1
    assert len(service.retrieve_knowledge(project.id, lifecycle=LifecycleState.PROPOSED)) == 2
