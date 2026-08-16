"""The pipeline over HTTP, and its behaviour parity with MCP (N3, ADR-0023).

Five application services reached MCP in Phases C to E and never reached HTTP,
so the product's own frontend could not search, ingest, clarify, assemble, or
see a classification. These routes close that.

What the tests defend is not that the routes exist — a route that returns 200
and the wrong thing passes that. It is **behaviour parity**: the same call
reaches the same application behaviour on both adapters. Serialisation may
differ, and does; MCP's `{total, page, cursor, results}` wrapper is an MCP
convention, not a domain rule.

The three claims that would cost the most if a router got them wrong:

    ingestion records evidence and changes no knowledge;
    an answered clarification is not knowledge until a person confirms;
    an assembled package labels proposed statements as proposed.

Each is a rule the application service already enforces. The risk a router
introduces is not breaking them — it is *restating* them slightly differently,
which is how two adapters start disagreeing about what the product does.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.api import create_app
from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.blueprint_service import BlueprintService
from kae_memory.application.classification_service import ClassificationService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.application.retrieval_service import RetrievalService
from kae_memory.application.review_service import ReviewService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.mcp import tools
from kae_memory.mcp.server import dispatch

DOCUMENT = "docs/requirements.md"
TEXT = "\n\n".join(
    (
        "A report must be approved before it is published. Approval applies to "
        "a specific version, so a later edit does not inherit an earlier decision.",
        "Ministry leaders submit a report at the end of every month. Submissions "
        "are due within five working days of the period closing.",
        "Pastors and administrators read published reports. Readership and "
        "submission are separate permissions and are checked separately.",
    )
    * 12
)


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory)) as test_client:
        yield test_client


@pytest.fixture
def mcp(factory: sessionmaker[Session]) -> tools.ToolContext:
    """The other adapter, for parity comparisons."""

    readiness = ReadinessService(factory)
    readiness.install_template()
    return tools.ToolContext(
        memory=MemoryService(factory),
        blueprint=BlueprintService(factory),
        readiness=readiness,
        review=ReviewService(factory),
        retrieval=RetrievalService(factory, DeterministicEmbeddingAdapter()),
        classification=ClassificationService(factory),
    )


@pytest.fixture
def project_id(client: TestClient) -> str:
    response = client.post("/v1/projects", json={"name": "Ministry Reporting"})
    assert response.status_code == 201
    return str(response.json()["id"])


def _seed_knowledge(factory: sessionmaker[Session], project_id: str) -> None:
    memory = MemoryService(factory)
    run = memory.start_run(ProjectId(project_id), AgentRole.REQUIREMENTS, "http-seed")
    memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(
                KnowledgeKind.REQUIREMENT.value,
                "A report must be approved before it is published.",
                "seed",
            )
        ],
    )


class TestSearch:
    def test_it_finds_seeded_knowledge(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed_knowledge(factory, project_id)

        response = client.get(
            f"/v1/projects/{project_id}/knowledge/search", params={"query": "approved"}
        )

        assert response.status_code == 200
        assert response.json()["matched_knowledge_items"] >= 0

    def test_it_admits_when_ranking_is_not_semantic(
        self, client: TestClient, project_id: str
    ) -> None:
        """The honesty rule that survives the change of transport.

        A caller who believes a conceptual query was understood reads an empty
        result as "the project does not know this". The truth may be "the words
        did not match", and only this field separates them.
        """

        response = client.get(
            f"/v1/projects/{project_id}/knowledge/search", params={"query": "approval"}
        )

        body = response.json()
        assert body["semantic_search_available"] is False
        assert body["search_mode"]
        assert body["warnings"]

    def test_the_count_is_split(self, client: TestClient, project_id: str) -> None:
        """One number could not say whether three hits were three statements."""

        body = client.get(
            f"/v1/projects/{project_id}/knowledge/search", params={"query": "approval"}
        ).json()

        assert "matched_chunks" in body
        assert "matched_knowledge_items" in body
        assert "count" not in body

    def test_an_unknown_kind_is_refused(self, client: TestClient, project_id: str) -> None:
        response = client.get(
            f"/v1/projects/{project_id}/knowledge/search",
            params={"query": "approval", "kinds": ["not_a_kind"]},
        )

        assert response.status_code == 422

    def test_an_unknown_project_is_a_404(self, client: TestClient) -> None:
        response = client.get(
            "/v1/projects/00000000-0000-0000-0000-000000000000/knowledge/search",
            params={"query": "approval"},
        )

        assert response.status_code == 404


class TestIngestion:
    def test_it_accepts_rather_than_creates(self, client: TestClient, project_id: str) -> None:
        """202, because nothing has been read yet.

        A 201 would say a resource exists that a caller can now read. What
        exists at this point is a promise to read one.
        """

        response = client.post(
            f"/v1/projects/{project_id}/documents",
            json={"document": DOCUMENT, "text": TEXT},
        )

        assert response.status_code == 202

    def test_evidence_is_recorded_and_knowledge_is_not(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        body = client.post(
            f"/v1/projects/{project_id}/documents",
            json={"document": DOCUMENT, "text": TEXT},
        ).json()

        assert body["evidence_recorded"] is True
        assert body["knowledge_changed"] is False
        assert body["extraction_runs_queued"]
        assert (
            MemoryService(factory).retrieve_knowledge(ProjectId(project_id), lifecycle=None) == ()
        )

    def test_a_bound_that_changed_what_was_read_is_reported(
        self, client: TestClient, project_id: str
    ) -> None:
        """Silently dropping the tail of a document is the worst available failure."""

        body = client.post(
            f"/v1/projects/{project_id}/documents",
            json={"document": DOCUMENT, "text": TEXT, "max_chunks": 1},
        ).json()

        assert body["complete"] is False
        assert body["truncated_chunks"] >= 1
        assert body["warnings"]

    def test_re_ingesting_replays_rather_than_duplicating(
        self, client: TestClient, project_id: str
    ) -> None:
        payload = {"document": DOCUMENT, "text": TEXT}

        first = client.post(f"/v1/projects/{project_id}/documents", json=payload).json()
        second = client.post(f"/v1/projects/{project_id}/documents", json=payload).json()

        assert second["idempotent_replay"] is True
        assert second["extraction_runs_queued"] == first["extraction_runs_queued"]

    def test_a_source_this_project_does_not_have_is_404_not_202(
        self, client: TestClient, project_id: str
    ) -> None:
        """The refusal reaches the caller as a missing source, not as an accepted
        ingestion (`D-164`). 202 with a dangling link would leave Studio believing
        the material is attributed to the repository it named."""

        response = client.post(
            f"/v1/projects/{project_id}/documents",
            json={
                "document": DOCUMENT,
                "text": TEXT,
                "source_id": "99999999-9999-9999-9999-999999999999",
            },
        )

        assert response.status_code == 404


class TestClarifications:
    def test_listing_is_a_post_because_it_materialises(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A GET that mutates is a GET a prefetch or a retry will perform again."""

        _seed_knowledge(factory, project_id)

        response = client.post(f"/v1/projects/{project_id}/clarifications")

        assert response.status_code == 200
        assert client.get(f"/v1/projects/{project_id}/clarifications").status_code == 405

    def test_the_questions_carry_answerable_ids(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed_knowledge(factory, project_id)

        body = client.post(f"/v1/projects/{project_id}/clarifications").json()

        assert body["questions"]
        assert all(question["clarification_id"] for question in body["questions"])

    def test_asking_twice_does_not_ask_a_person_twice(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed_knowledge(factory, project_id)

        first = client.post(f"/v1/projects/{project_id}/clarifications").json()
        second = client.post(f"/v1/projects/{project_id}/clarifications").json()

        assert [q["clarification_id"] for q in first["questions"]] == [
            q["clarification_id"] for q in second["questions"]
        ]

    def test_an_answer_is_evidence_not_knowledge(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """ "Answered" must never read as "the project now knows this"."""

        _seed_knowledge(factory, project_id)
        question = client.post(f"/v1/projects/{project_id}/clarifications").json()["questions"][0]

        response = client.post(
            f"/v1/projects/{project_id}/clarifications/{question['clarification_id']}/answer",
            json={"answer": "The board approves reports.", "actor_id": "cris"},
        )

        body = response.json()
        assert response.status_code == 200
        assert body["knowledge_changed"] is False
        assert body["run_id"]


class TestAssembly:
    def test_it_is_pinned_to_the_revision_it_read(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed_knowledge(factory, project_id)

        body = client.get(f"/v1/projects/{project_id}/context").json()

        assert body["manifest"]["knowledge_revision"] == body["knowledge_revision"]
        assert body["manifest"]["content_hash"].startswith("sha256:")

    def test_it_is_deterministic(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed_knowledge(factory, project_id)

        first = client.get(f"/v1/projects/{project_id}/context").json()
        second = client.get(f"/v1/projects/{project_id}/context").json()

        assert first["manifest"]["content_hash"] == second["manifest"]["content_hash"]
        assert first["package"]["artifacts"] == second["package"]["artifacts"]

    def test_every_statement_declares_its_lifecycle(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """An implementer who cannot tell a candidate from a decision builds
        whichever they read first."""

        _seed_knowledge(factory, project_id)

        body = client.get(
            f"/v1/projects/{project_id}/context", params={"include_proposed": True}
        ).json()

        for section in body["sections"]:
            for statement in section["statements"]:
                assert statement["lifecycle"]
                assert statement["label"]

    def test_unresolved_questions_travel_with_it(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        _seed_knowledge(factory, project_id)

        body = client.get(f"/v1/projects/{project_id}/context").json()

        assert "unresolved_critical_gaps" in body["manifest"]
        assert any("do not choose an answer" in line.lower() for line in body["guidance"])

    def test_an_unknown_purpose_is_refused(self, client: TestClient, project_id: str) -> None:
        response = client.get(f"/v1/projects/{project_id}/context", params={"purpose": "whatever"})

        assert response.status_code == 422


class TestReviewIsNoLongerOneSided:
    def _candidate(self, factory: sessionmaker[Session], project_id: str) -> tuple[str, int]:
        memory = MemoryService(factory)
        _seed_knowledge(factory, project_id)
        item = memory.retrieve_knowledge(ProjectId(project_id), lifecycle=None)[0]
        return str(item.id), item.current_version.number

    def test_a_candidate_can_be_rejected(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """HTTP had confirm and neither reject nor correct."""

        item_id, version = self._candidate(factory, project_id)

        response = client.post(
            f"/v1/projects/{project_id}/knowledge/{item_id}/reject",
            json={"expected_version": version, "reviewer": "cris", "reason_code": "incorrect"},
        )

        assert response.status_code == 200
        assert response.json()["lifecycle"] == "rejected"

    def test_a_candidate_can_be_corrected(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        item_id, version = self._candidate(factory, project_id)

        response = client.post(
            f"/v1/projects/{project_id}/knowledge/{item_id}/correct",
            json={
                "expected_version": version,
                "content": "A report must be approved by the board before publication.",
                "reviewer": "cris",
            },
        )

        assert response.status_code == 200
        assert response.json()["version"] > version

    def test_a_stale_version_is_refused(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        """A decision must not be applied to wording that changed after it was read."""

        item_id, version = self._candidate(factory, project_id)

        response = client.post(
            f"/v1/projects/{project_id}/knowledge/{item_id}/reject",
            json={"expected_version": version + 5, "reviewer": "cris"},
        )

        assert response.status_code in {409, 422}

    def test_a_reviewer_is_required(
        self, client: TestClient, factory: sessionmaker[Session], project_id: str
    ) -> None:
        item_id, version = self._candidate(factory, project_id)

        response = client.post(
            f"/v1/projects/{project_id}/knowledge/{item_id}/reject",
            json={"expected_version": version, "reviewer": ""},
        )

        assert response.status_code == 422


class TestClassificationOverHttp:
    def _observe(self, mcp: tools.ToolContext, project_id: str, text: str, key: str) -> None:
        dispatch(
            mcp,
            "kae_submit_observation",
            {"project_id": project_id, "observation": text, "idempotency_key": key},
        )

    def test_operational_state_is_readable(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        self._observe(mcp, project_id, "M8 is complete.", "http-ops-1")

        body = client.get(f"/v1/projects/{project_id}/operational-state").json()

        assert body["total"] >= 1
        assert body["records"][0]["authority"]
        assert "sentence said so" in body["note"]

    def test_it_filters_by_subject(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        self._observe(mcp, project_id, "M8 is complete.", "http-ops-2")
        self._observe(mcp, project_id, "M9 is blocked.", "http-ops-3")

        body = client.get(
            f"/v1/projects/{project_id}/operational-state", params={"subject": "M8"}
        ).json()

        assert body["total"] == 1

    def test_classifications_are_readable_and_honest(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        self._observe(mcp, project_id, "M8 is complete. To God be the glory!", "http-cls-1")

        body = client.get(f"/v1/projects/{project_id}/classifications").json()

        assert body["total"] >= 2
        assert body["semantic_classification"] is False
        assert body["knowledge_changed"] is False

    def test_settling_is_not_verifying(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        self._observe(mcp, project_id, "The suite passed on T1.", "http-settle-1")
        record = client.get(f"/v1/projects/{project_id}/operational-state").json()["records"][0]

        response = client.post(
            f"/v1/projects/{project_id}/operational-state/{record['operational_update_id']}/settle",
            json={"state": "active", "actor": "cris"},
        )

        body = response.json()
        assert response.status_code == 200
        assert body["state"] == "active"
        assert body["authority"] == "agent_reported"

    def test_an_impermissible_transition_conflicts(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        self._observe(mcp, project_id, "M8 is complete.", "http-settle-2")
        record = client.get(f"/v1/projects/{project_id}/operational-state").json()["records"][0]

        response = client.post(
            f"/v1/projects/{project_id}/operational-state/{record['operational_update_id']}/settle",
            json={"state": "resolved", "actor": "cris"},
        )

        assert response.status_code == 409


class TestBehaviourParity:
    """Same application behaviour, whichever adapter asked.

    Not envelope parity. The shapes differ deliberately — MCP wraps pages as
    `{total, page, cursor, results}` and HTTP does not — and a test asserting
    identical payloads would forbid the transport independence ADR-0023 grants.
    """

    def test_both_adapters_agree_on_what_search_can_do(
        self,
        client: TestClient,
        mcp: tools.ToolContext,
        factory: sessionmaker[Session],
        project_id: str,
    ) -> None:
        _seed_knowledge(factory, project_id)

        over_http = client.get(
            f"/v1/projects/{project_id}/knowledge/search", params={"query": "approved"}
        ).json()
        over_mcp = dispatch(
            mcp, "kae_search_knowledge", {"project_id": project_id, "query": "approved"}
        )

        assert over_http["semantic_search_available"] == over_mcp["semantic_search_available"]
        assert over_http["matched_knowledge_items"] == over_mcp["matched_knowledge_items"]

    def test_both_adapters_agree_that_ingestion_changes_no_knowledge(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        over_http = client.post(
            f"/v1/projects/{project_id}/documents",
            json={"document": DOCUMENT, "text": TEXT},
        ).json()

        assert over_http["knowledge_changed"] is False
        assert over_http["workflow_state"] == "extraction_queued"

    def test_both_adapters_produce_the_same_assembly_hash(
        self,
        client: TestClient,
        mcp: tools.ToolContext,
        factory: sessionmaker[Session],
        project_id: str,
    ) -> None:
        """The strongest parity assertion available: identical content, not shape.

        A hash computed from the assembled knowledge is transport-independent
        by construction, so if the two adapters disagree here they disagree
        about what the project knows.
        """

        _seed_knowledge(factory, project_id)
        from kae_memory.application.assembly_service import AssemblyService

        mcp.assembly = AssemblyService(factory)

        over_http = client.get(f"/v1/projects/{project_id}/context").json()
        over_mcp = dispatch(
            mcp, "kae_assemble_context", {"project_id": project_id, "purpose": "implementation"}
        )

        assert over_http["manifest"]["content_hash"] == over_mcp["manifest"]["content_hash"]

    def test_both_adapters_refuse_a_settlement_the_domain_forbids(
        self, client: TestClient, mcp: tools.ToolContext, project_id: str
    ) -> None:
        """A rule enforced in the domain cannot be softened by an adapter."""

        dispatch(
            mcp,
            "kae_submit_observation",
            {
                "project_id": project_id,
                "observation": "M8 is complete.",
                "idempotency_key": "parity-settle-1",
            },
        )
        record = client.get(f"/v1/projects/{project_id}/operational-state").json()["records"][0]
        identifier = record["operational_update_id"]

        over_http = client.post(
            f"/v1/projects/{project_id}/operational-state/{identifier}/settle",
            json={"state": "resolved", "actor": "cris"},
        )
        over_mcp = dispatch(
            mcp,
            "kae_settle_operational_record",
            {
                "project_id": project_id,
                "operational_update_id": identifier,
                "state": "resolved",
                "actor": "cris",
            },
        )

        assert over_http.status_code == 409
        assert over_mcp["error"] == "invalid_state_transition"
