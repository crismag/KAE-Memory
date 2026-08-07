"""F-002 — a later session knows what an earlier one established.

**Correction to the register.** F-002 says the claim "has no end-to-end test".
It has one: `tests/agents/test_collaboration.py` (AT-006) runs a requirements
agent in a discovery session, confirms a rule, discards the process, and has an
architecture agent in a second session derive from confirmed knowledge alone.
That is the composition, and it passes.

What AT-006 does not cover is the half of continuity that is about *not*
carrying things forward, and the hop that actually reaches a consumer. This file
covers only that remainder, so the two do not overlap:

* a statement a person **rejected** must not return in a later session;
* the rejection must stay readable **as a decision**, so the second session can
  tell "we ruled this out" from "nobody has looked at this";
* provenance must survive the boundary, or a later reader cannot tell agreement
  from assertion;
* it must reach the **assembled package**, since an agent reads assembled
  context and not the knowledge table.

The negative cases are the ones worth having. Continuity that resurrects
discarded candidates silently undoes a person's decision, which is worse than no
continuity at all — and it is the failure mode a positive-only test cannot see.

**What continuity means here, precisely.** Not that the second session sees the
first session's *messages*; a transcript is not knowledge, and a system that
replays conversation has not established anything. It means the second session
sees the statements the first session produced and a person confirmed, with
their provenance intact, through the ordinary read path — with no reference to
the session that created them.

The negative case matters as much as the positive one: knowledge a person
rejected in the first session must **not** come back in the second. Continuity
that resurrects discarded statements is worse than none, because it silently
undoes a decision someone made.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyPurpose, AssemblyService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.workspace import ActorType, SessionType

SETTLED = "Invoices must be sent within three days of a job finishing."
DISCARDED = "Invoices are approved by a second person before sending."
ALSO_SETTLED = "Every invoice carries a client reference."


@pytest.fixture
def first_session(factory: sessionmaker[Session]) -> dict[str, Any]:
    """Everything the first conversation leaves behind.

    Returns identifiers only — deliberately no service objects and no domain
    objects. The second half of the test must reach the same facts by reading
    the database, which is the only route a genuinely later session has.
    """

    ReadinessService(factory).install_template()
    memory = MemoryService(factory)

    project = ProjectId(str(memory.create_project("Freelance invoicing").id))
    session = memory.open_session(project, SessionType.DISCOVERY)

    memory.record_message(
        project,
        session.id,
        "Invoices go out within three days and always name the client.",
        ActorType.USER,
        idempotency_key="continuity-first-turn",
    )

    run = memory.start_run(project, AgentRole.REQUIREMENTS, "continuity-extraction")
    written = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(KnowledgeKind.RULE.value, SETTLED, "interview"),
            WriteKnowledgeRequest(KnowledgeKind.RULE.value, ALSO_SETTLED, "interview"),
            WriteKnowledgeRequest(KnowledgeKind.ASSUMPTION.value, DISCARDED, "interview"),
        ],
    )
    by_text = {item.current_version.content: item for item in written}

    # A person rules on each one. This is the step that makes the difference
    # between "the system extracted something" and "the project knows something".
    memory.confirm_knowledge(by_text[SETTLED].id)
    memory.confirm_knowledge(by_text[ALSO_SETTLED].id)
    memory.reject_knowledge(by_text[DISCARDED].id)

    readiness = ReadinessService(factory)
    for content in (SETTLED, ALSO_SETTLED):
        readiness.assign_area(project, by_text[content].id, "domain_model_and_data")

    return {
        "project": project,
        "session_id": session.id,
        "run_id": run.id,
        "confirmed": {content: by_text[content].id for content in (SETTLED, ALSO_SETTLED)},
        "rejected": by_text[DISCARDED].id,
    }


class TestASecondSessionInheritsWhatWasSettled:
    def test_the_second_session_is_genuinely_a_different_one(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        """Guard the premise before testing the conclusion.

        If the two sessions were the same record, everything below would pass
        for an uninteresting reason.
        """

        memory = MemoryService(factory)
        later = memory.open_session(first_session["project"], SessionType.ARCHITECTURE)

        assert later.id != first_session["session_id"]
        assert len(memory.sessions_for_project(first_session["project"])) == 2

    def test_confirmed_knowledge_is_visible_without_naming_the_first_session(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        """Kept despite AT-006, as the premise the negative cases rest on.

        Every test below asserts something is *absent*. If nothing were visible
        at all they would all pass while continuity was completely broken, so
        one positive assertion has to sit in front of them.

        Note what is *not* passed: no session id, no run id. The second session
        asks the project what it knows, and the answer does not depend on
        knowing where it came from.
        """

        memory = MemoryService(factory)
        known = memory.retrieve_knowledge(first_session["project"], LifecycleState.VALIDATED)
        contents = {item.current_version.content for item in known}

        assert SETTLED in contents
        assert ALSO_SETTLED in contents

    def test_rejected_knowledge_does_not_come_back(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        """A decision made in the first session survives into the second."""

        memory = MemoryService(factory)
        known = memory.retrieve_knowledge(first_session["project"], LifecycleState.VALIDATED)

        assert DISCARDED not in {item.current_version.content for item in known}

    def test_the_rejection_is_still_readable_as_a_decision(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        """Rejection is not deletion (ADR: rejected items are retained).

        Continuity has to carry "we considered this and said no" as well as
        "we agreed this", or the second session is free to propose it again.
        """

        memory = MemoryService(factory)
        everything = memory.retrieve_knowledge(first_session["project"], None)
        discarded = [item for item in everything if item.current_version.content == DISCARDED]

        assert len(discarded) == 1
        assert discarded[0].lifecycle is LifecycleState.REJECTED

    def test_provenance_survives_the_session_boundary(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        """Knowing a thing is not enough — the second session must be able to
        ask where it came from, or it cannot tell agreement from assertion."""

        memory = MemoryService(factory)
        known = memory.retrieve_knowledge(first_session["project"], LifecycleState.VALIDATED)
        settled = next(i for i in known if i.current_version.content == SETTLED)

        # Compared by value, not by identifier type. `AgentRunId` is recorded
        # as `Provenance.execution_id`, which is an `ExecutionId` wrapping the
        # same string — two distinct types that never compare equal, so `==` on
        # the wrappers is always False and would make this assertion untestable
        # rather than strict.
        assert (
            settled.current_version.provenance.execution_id.value == first_session["run_id"].value
        )


class TestTheAssembledPackageCarriesIt:
    """Continuity that only a database query can see is not continuity.

    The consumer is an agent receiving assembled context, so the last hop —
    knowledge reaching the package a later session actually reads — is part of
    the claim, not a separate feature.
    """

    def test_the_package_contains_what_was_settled(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        assembly = AssemblyService(factory).assemble(
            first_session["project"], AssemblyPurpose.IMPLEMENTATION
        )

        rendered = _text_of(assembly)
        assert SETTLED in rendered
        assert ALSO_SETTLED in rendered

    def test_the_package_omits_what_was_rejected(
        self, factory: sessionmaker[Session], first_session: dict[str, Any]
    ) -> None:
        assembly = AssemblyService(factory).assemble(
            first_session["project"], AssemblyPurpose.IMPLEMENTATION, include_proposed=True
        )

        assert DISCARDED not in _text_of(assembly), (
            "include_proposed widens to unconfirmed candidates; it must not "
            "reach back for statements a person ruled out"
        )


def _text_of(assembly: Any) -> str:
    """Everything the assembly renders, flattened.

    Deliberately structure-agnostic: this test is about whether a statement
    survives to the package, and pinning it to the manifest's current shape
    would make it fail for reasons that have nothing to do with continuity.
    """

    return repr(assembly)
