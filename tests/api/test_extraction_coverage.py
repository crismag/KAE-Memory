"""How much of what was submitted actually became knowledge.

`PLANNING_MODEL.md` requires this and nothing implemented it:

    Content loss is reported separately and never folded in. While F-018 is
    open, a project whose extraction abandoned chunks must say so.

F-018 measured 29–65% of chunks abandoned across four real corpora, every one
`retry_budget_exhausted` after `verify_quotes` rejected a citation that was a
directory tree or a code fence. Everything downstream is computed over what
survived — and what survived looks exactly like a complete project.

This does not repair the loss. It makes the existing number honest, which is
what makes deferring the repair defensible rather than convenient.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.api import create_app
from kae_memory.api.security import AuthPolicy
from kae_memory.application import MemoryService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.persistence.workspace_repositories import AgentRunRepository


@pytest.fixture
def client(factory: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(factory, auth=AuthPolicy())) as test_client:
        yield test_client


def _abandon(
    memory: MemoryService,
    factory: sessionmaker[Session],
    project_id: str,
    key: str,
    role: AgentRole,
) -> None:
    """Drive a run to the state F-018 leaves behind.

    Failed once, then abandoned — the transition the worker performs when the
    retry budget is spent. There is no service method for it because nothing
    outside the worker should abandon a run, so this reaches the domain the way
    the worker does.
    """

    run = memory.start_run(ProjectId(project_id), role, key)
    failed = memory.fail_run(
        run.id, "retry_budget_exhausted", "item 3 cites a quote that does not occur"
    )
    moment = datetime.now(UTC)
    with factory() as session:
        AgentRunRepository(session).save(
            failed.abandon(moment, "3 attempts exhausted: verify_quotes"), moment
        )
        session.commit()


def test_a_project_that_lost_nothing_says_nothing(client: TestClient) -> None:
    """Silence when there is nothing to disclose.

    A banner on every project saying something might be missing is a banner
    nobody reads — and the previous slice was about not handing people more to
    sort out.
    """

    project = client.post("/v1/projects", json={"name": "Clean"}).json()

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["complete"] is True
    assert coverage["abandoned"] == 0


def test_a_project_that_lost_content_says_how_much(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    memory = MemoryService(factory)
    project = client.post("/v1/projects", json={"name": "Lossy"}).json()
    memory.start_run(ProjectId(project["id"]), AgentRole.DISCOVERY, "ok-1")
    _abandon(memory, factory, project["id"], "lost-1", AgentRole.DISCOVERY)

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["abandoned"] == 1
    assert coverage["complete"] is False


def test_only_runs_that_read_source_content_count(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    """Review and architecture read what already exists.

    Abandoning one loses classification or a derived decision — not source
    content — and counting it here would report a loss that did not happen.
    """

    memory = MemoryService(factory)
    project = client.post("/v1/projects", json={"name": "Review lost"}).json()
    _abandon(memory, factory, project["id"], "review-lost", AgentRole.REVIEW)

    coverage = client.get(f"/v1/projects/{project['id']}/extraction-coverage").json()

    assert coverage["total"] == 0
    assert coverage["complete"] is True
