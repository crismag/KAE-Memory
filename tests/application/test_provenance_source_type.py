"""What kind of source a statement came from, recorded where it is decided.

`D-105` found `knowledge_provenance_links.source_type` `NULL` on all 4,136 live
rows: in the schema since revision 0002, carried by the domain model and the
repository, and written by nothing. `ADR-0008` makes what an area may reach
depend on it, so an empty column is a ladder whose every rung reads `missing`.

These tests hold the two halves of `D-106`. The rule is applied once, in
`source_type_for_run`, because only the acquisition path can tell a repository
file from a pasted specification — by the time a run reads the text the two are
identical. And the guard is on the write, not on the read: a database written
before this rule holds `NULL`, and refusing to *read* one would turn an unfed
column into a failure to open a knowledge item.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import IngestionService, MemoryService, WriteKnowledgeRequest
from kae_memory.application.memory_service import source_type_for_run
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole, AgentRun, RunStatus
from kae_memory.domain.identifiers import (
    AgentRunId,
    KnowledgeItemId,
    MessageId,
    ProjectId,
    ProvenanceLinkId,
)
from kae_memory.domain.models import (
    KnowledgeSourceType,
    ProvenanceLink,
    ProvenanceLinkType,
)
from kae_memory.domain.workspace import SessionType
from kae_memory.persistence.workspace_repositories import ProvenanceLinkRepository

PRODUCING = {
    ProvenanceLinkType.PRODUCED_BY,
    ProvenanceLinkType.DERIVED_FROM_MESSAGE,
}


def _run(role: AgentRole, context: dict[str, object]) -> AgentRun:
    """An unpersisted run, for the rule that reads only role and context."""

    return AgentRun(
        id=AgentRunId("11111111-1111-1111-1111-111111111111"),
        project_id=ProjectId("22222222-2222-2222-2222-222222222222"),
        role=role,
        idempotency_key="rule-1",
        status=RunStatus.PENDING,
        input_context=context,
    )


class TestTheRuleIsDeterminedOnceFromTheRun:
    """`source_type_for_run` — four branches, one per member of `D-106`."""

    def test_architecture_derives_from_what_the_project_already_holds(self) -> None:
        """It reaches nothing outside KAE, so it cannot ground an area."""

        assert source_type_for_run(_run(AgentRole.ARCHITECTURE, {})) is (
            KnowledgeSourceType.KAE_INFERENCE
        )

    def test_a_declared_source_type_is_believed(self) -> None:
        """Only the acquisition path knows the text came from a repository."""

        run = _run(AgentRole.REQUIREMENTS, {"source_type": "repository", "document": "api.py"})

        assert source_type_for_run(run) is KnowledgeSourceType.REPOSITORY

    def test_a_run_carrying_a_document_was_given_one(self) -> None:
        run = _run(AgentRole.REQUIREMENTS, {"document": "spec.md"})

        assert source_type_for_run(run) is KnowledgeSourceType.IMPORTED_DOCUMENT

    def test_anything_else_read_a_message_in_a_session(self) -> None:
        run = _run(AgentRole.REQUIREMENTS, {"message_id": "abc"})

        assert source_type_for_run(run) is KnowledgeSourceType.USER_STATEMENT


class TestEveryWritePathRecordsIt:
    """The end the column exists for: a written statement names its source."""

    def test_knowledge_written_from_a_conversation_is_a_user_statement(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = memory.create_project("Ministry reporting", key="prov-conversation")
        session = memory.open_session(project.id, SessionType.DISCOVERY)
        message = memory.record_message(
            project.id, session.id, "Only an authorised approver may approve a report."
        ).message
        run = memory.start_run(
            project.id, AgentRole.REQUIREMENTS, idempotency_key="req-1", session_id=session.id
        )

        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="rule",
                    content="Only an authorised approver may approve a report.",
                    source="discovery interview",
                    from_message_id=message.id,
                )
            ],
        )

        links = memory.provenance_for_item(written[0].id)
        producing = [link for link in links if link.link_type in PRODUCING]
        assert len(producing) == 2, "the run link and the message link"
        assert all(link.source_type is KnowledgeSourceType.USER_STATEMENT for link in producing)

    def test_knowledge_an_architecture_run_derived_is_inference(
        self, factory: sessionmaker[Session]
    ) -> None:
        """This is what stops a project raising its own readiness (ADR-0008)."""

        memory = MemoryService(factory)
        project = memory.create_project("Ministry reporting", key="prov-architecture")
        run = memory.start_run(project.id, AgentRole.ARCHITECTURE, idempotency_key="arch-1")

        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="decision",
                    content="Reports are stored in the reporting service.",
                    source="derived from confirmed knowledge",
                )
            ],
        )

        (link,) = [
            link
            for link in memory.provenance_for_item(written[0].id)
            if link.link_type in PRODUCING
        ]
        assert link.source_type is KnowledgeSourceType.KAE_INFERENCE

    def test_a_correction_is_the_persons_own_wording(self, factory: sessionmaker[Session]) -> None:
        """Whatever the original statement was extracted from."""

        memory = MemoryService(factory)
        project = memory.create_project("Ministry reporting", key="prov-correction")
        session = memory.open_session(project.id, SessionType.DISCOVERY)
        run = memory.start_run(
            project.id, AgentRole.REQUIREMENTS, idempotency_key="req-2", session_id=session.id
        )
        written = memory.write_knowledge(
            run.id,
            [
                WriteKnowledgeRequest(
                    kind="rule",
                    content="Any approver may approve a report.",
                    source="discovery interview",
                )
            ],
        )
        correction = memory.record_message(
            project.id, session.id, "No — only an authorised approver may."
        ).message

        memory.correct_knowledge(
            written[0].id,
            "Only an authorised approver may approve a report.",
            source="the owner's correction",
            from_message_id=correction.id,
        )

        message_links = [
            link
            for link in memory.provenance_for_item(written[0].id)
            if link.link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE
        ]
        assert message_links, "the correction is recorded against its message"
        assert message_links[-1].source_type is KnowledgeSourceType.USER_STATEMENT

    def test_ingestion_carries_the_callers_source_type_to_the_run(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The last place that knows the difference says so, once."""

        memory = MemoryService(factory)
        project = memory.create_project("Ministry reporting", key="prov-ingest")
        ingestion = IngestionService(factory, memory)

        result = ingestion.ingest_document(
            project.id,
            "src/api.py",
            "Staff submit monthly reports for their ministry. " * 20,
            source_type=KnowledgeSourceType.REPOSITORY,
        )

        runs = {run.id: run for run in memory.runs_for_project(project.id)}
        assert result.chunks
        for chunk in result.chunks:
            assert source_type_for_run(runs[chunk.run_id]) is KnowledgeSourceType.REPOSITORY

    def test_a_bare_paste_defaults_to_an_imported_document(
        self, factory: sessionmaker[Session]
    ) -> None:
        memory = MemoryService(factory)
        project = memory.create_project("Ministry reporting", key="prov-paste")
        ingestion = IngestionService(factory, memory)

        result = ingestion.ingest_document(
            project.id, "spec.md", "Staff submit monthly reports for their ministry. " * 20
        )

        runs = {run.id: run for run in memory.runs_for_project(project.id)}
        assert result.chunks
        for chunk in result.chunks:
            assert source_type_for_run(runs[chunk.run_id]) is KnowledgeSourceType.IMPORTED_DOCUMENT


class TestTheGuardIsOnTheWrite:
    """`ProvenanceLinkRepository.add` refuses what left the column empty."""

    def _link(
        self,
        link_type: ProvenanceLinkType,
        source_type: KnowledgeSourceType | None = None,
    ) -> ProvenanceLink:
        return ProvenanceLink(
            id=ProvenanceLinkId("33333333-3333-3333-3333-333333333333"),
            project_id=ProjectId("22222222-2222-2222-2222-222222222222"),
            knowledge_item_id=KnowledgeItemId("44444444-4444-4444-4444-444444444444"),
            link_type=link_type,
            created_at=datetime(2026, 8, 16, tzinfo=UTC),
            # Each producing link kind has its own required endpoint. Giving
            # both to both would let the endpoint invariant fire instead of the
            # one under test, which is how a guard passes for the wrong reason.
            agent_run_id=(
                AgentRunId("11111111-1111-1111-1111-111111111111")
                if link_type is not ProvenanceLinkType.DERIVED_FROM_MESSAGE
                else None
            ),
            message_id=(
                MessageId("55555555-5555-5555-5555-555555555555")
                if link_type is ProvenanceLinkType.DERIVED_FROM_MESSAGE
                else None
            ),
            source_type=source_type,
        )

    @pytest.mark.parametrize("link_type", sorted(PRODUCING))
    def test_a_producing_link_without_a_source_type_is_refused(
        self, factory: sessionmaker[Session], link_type: ProvenanceLinkType
    ) -> None:
        with factory() as session, pytest.raises(DomainInvariantError, match="source type"):
            ProvenanceLinkRepository(session).add(self._link(link_type))

    def test_a_used_by_link_carries_none_by_construction(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Consumption is not an origin, so it has no source to name."""

        memory = MemoryService(factory)
        project = memory.create_project("Ministry reporting", key="prov-used-by")
        session = memory.open_session(project.id, SessionType.DISCOVERY)
        writer = memory.start_run(
            project.id, AgentRole.REQUIREMENTS, idempotency_key="req-3", session_id=session.id
        )
        written = memory.write_knowledge(
            writer.id,
            [
                WriteKnowledgeRequest(
                    kind="rule",
                    content="A report cannot be published before it is approved.",
                    source="discovery interview",
                )
            ],
        )
        memory.confirm_knowledge(written[0].id)
        reader = memory.start_run(project.id, AgentRole.ARCHITECTURE, idempotency_key="arch-2")

        (item,) = memory.retrieve_knowledge(project.id, used_by_run_id=reader.id)

        used = [
            link
            for link in memory.provenance_for_item(item.id)
            if link.link_type is ProvenanceLinkType.USED_BY
        ]
        assert used, "consumption is still recorded"
        assert all(link.source_type is None for link in used)

    def test_a_row_written_before_the_rule_is_still_readable(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The reason this is not a domain invariant.

        The live database is at `0025` and holds 4,136 `NULL` rows. A read-side
        invariant would turn an unfed column into a crash the moment anybody
        opened a knowledge item.
        """

        legacy = self._link(ProvenanceLinkType.PRODUCED_BY, source_type=None)

        assert legacy.source_type is None, "constructing one is allowed"
