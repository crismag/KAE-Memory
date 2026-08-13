"""`J8` — the project is not ready, and somebody wants the package anyway.

From `END_TO_END_JOURNEYS.md`, verbatim:

> **J8 — Enough for now.** At an incomplete stage, user requests the best
> package available. Pass when KAE returns a useful preliminary package with
> **explicit gaps and uncertainty** instead of refusing because readiness is
> incomplete.

This is item 7 of the product's own value proposition — *"a preliminary
development package show what is known and what remains open"* — and it is the
journey a person meets soonest, because every project is incomplete for far
longer than it is finished.

## Why this is not already covered

`tests/api/test_preliminary_context.py` covers the endpoint's semantics
thoroughly: a candidate is not `known`, an assumption carries its consequence,
unknowns arrive split, composing confirms nothing. **None of them asks what
happens when somebody wants the package and the project is not ready.**

It also closes `D-32` from the other side. `D-32` established that nothing
refuses to generate — a correction to a false claim I had made about a gate that
does not exist. That established the behaviour *exists*. This asks whether it is
the **right** behaviour by the product's own specification, which is a different
question and the one the journey answers.

## The two halves, kept apart

1. **It does not refuse.** A project far below any threshold still yields an
   assembly with real content in it.
2. **It does not overstate.** The result says what is missing, what is merely
   proposed, and that it is not fit to implement — because a package that
   returns cheerfully and hides its gaps fails this journey more damagingly
   than one that refuses, and passes clause one while doing it.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.assembly_service import AssemblyPurpose, AssemblyService
from kae_memory.application.preliminary_context_service import PreliminaryContextService
from kae_memory.application.readiness_service import ReadinessService
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.workspace import ActorType, SessionType

#: The one thing this project has settled. Deliberately a single confirmed
#: statement in a single area: enough that the package is not empty, nowhere
#: near enough for any mandatory-coverage threshold.
#:
#: A `constraint`, because `constraints_and_assumptions` accepts assumptions and
#: constraints and refuses rules — the template enforces which kinds an area
#: takes, and a fixture that ignored that would be testing an arrangement the
#: product does not allow.
SETTLED = "Thoughts captured on a phone must be reviewable on a laptop later."

#: Extracted and never ruled on. The journey's *uncertainty*, and the thing a
#: package must not present as settled.
PROPOSED = "An item nobody has triaged within a week is archived automatically."


@pytest.fixture
def unfinished(factory: sessionmaker[Session]) -> dict[str, Any]:
    """A real project, early. One confirmed statement and one candidate."""

    ReadinessService(factory).install_template()
    memory = MemoryService(factory)

    project = ProjectId(str(memory.create_project("Thought inbox").id))
    session = memory.open_session(project, SessionType.DISCOVERY)
    memory.record_message(
        project,
        session.id,
        "I want an inbox where I can dump thoughts and have them turned into useful things.",
        ActorType.USER,
        idempotency_key="j8-first-turn",
    )

    run = memory.start_run(project, AgentRole.REQUIREMENTS, "j8-extraction")
    written = memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, SETTLED, "interview"),
            WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, PROPOSED, "interview"),
        ],
    )
    by_text = {item.current_version.content: item for item in written}
    memory.confirm_knowledge(by_text[SETTLED].id)

    readiness = ReadinessService(factory)
    # `constraints_and_assumptions`, which every purpose reads — *"constraints
    # bind every audience"*. The first version of this used
    # `domain_model_and_data`, an architecture and implementation area, and the
    # discovery view then held nothing known. That was correct behaviour and a
    # badly chosen fixture: it tested purpose filtering, not this journey.
    for content in (SETTLED, PROPOSED):
        # **Both**, including the candidate. A statement nobody has filed into
        # an area does not appear in the preliminary view at all — it is
        # reachable only as an `unclassified_knowledge` review finding — so a
        # fixture that left the candidate unassigned would have tested that
        # omission rather than this journey. Worth knowing either way: a
        # project's uncertainty is only as visible as its filing.
        readiness.assign_area(project, by_text[content].id, "constraints_and_assumptions")

    return {"project": project, "confirmed": by_text[SETTLED].id}


class TestThePremise:
    def test_this_project_really_is_incomplete(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        """Guard the premise before testing the conclusion.

        If the fixture were accidentally complete, everything below would pass
        for an uninteresting reason — the failure mode `J8` is least able to
        afford, because its whole subject is what happens when a project is not
        ready.
        """

        snapshot = ReadinessService(factory).calculate(unfinished["project"])

        assert snapshot.implementation_eligible is False
        assert snapshot.missing_mandatory_areas


class TestItDoesNotRefuse:
    """Clause one. *"Instead of refusing because readiness is incomplete."*"""

    def test_a_package_is_assembled_at_all(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        assembled = AssemblyService(factory).assemble(
            unfinished["project"], AssemblyPurpose.IMPLEMENTATION
        )

        assert assembled.manifest.package_id

    def test_it_carries_what_the_project_did_settle(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        """*"Useful"* is the word the journey uses, and an empty package that
        technically assembled satisfies clause one while being worthless."""

        assembled = AssemblyService(factory).assemble(
            unfinished["project"], AssemblyPurpose.IMPLEMENTATION
        )
        texts = [
            statement.text for section in assembled.sections for statement in section.statements
        ]

        assert SETTLED in texts

    def test_a_preliminary_view_composes_too(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        preliminary = PreliminaryContextService(factory).compose(
            unfinished["project"], AssemblyPurpose.DISCOVERY
        )

        assert preliminary.project_id


class TestItDoesNotOverstate:
    """Clause two, and the one that matters more.

    A package that returns cheerfully and hides its gaps passes clause one while
    failing this journey more damagingly than a refusal would — the reader acts
    on it.
    """

    def test_the_package_says_it_is_not_fit_to_implement(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        assembled = AssemblyService(factory).assemble(
            unfinished["project"], AssemblyPurpose.IMPLEMENTATION
        )

        # The manifest's own gap list. Empty here would mean a project with one
        # confirmed statement claiming nothing is outstanding.
        assert assembled.manifest.unresolved_critical_gaps

    def test_an_unruled_candidate_is_not_carried_as_settled(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        """The uncertainty half. A proposal in the package without a label is a
        proposal a coding agent implements."""

        assembled = AssemblyService(factory).assemble(
            unfinished["project"], AssemblyPurpose.IMPLEMENTATION
        )
        texts = [
            statement.text for section in assembled.sections for statement in section.statements
        ]

        assert PROPOSED not in texts

    def test_the_preliminary_view_keeps_known_and_proposed_apart(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        """*"Explicit gaps and uncertainty"*, in the shape Memory holds them.

        Four separate collections, which is the property `PreliminaryContext`
        exists for: *"a reader who cannot tell a confirmed requirement from a
        plausible guess has a document that is worse than nothing — the same
        document with the warning removed."*
        """

        preliminary = PreliminaryContextService(factory).compose(
            unfinished["project"], AssemblyPurpose.DISCOVERY
        )

        known = [statement.text for statement in preliminary.known]
        proposed = [statement.text for statement in preliminary.proposed]

        assert SETTLED in known
        assert PROPOSED in proposed
        assert SETTLED not in proposed

    def test_it_says_out_loud_that_it_rests_on_unconfirmed_material(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        preliminary = PreliminaryContextService(factory).compose(
            unfinished["project"], AssemblyPurpose.DISCOVERY
        )

        assert preliminary.is_preliminary is True

    def test_readiness_did_not_rise_because_a_package_was_asked_for(
        self, factory: sessionmaker[Session], unfinished: dict[str, Any]
    ) -> None:
        """Asking is not progress.

        The failure this guards is subtle and would be invisible: a system that
        counted assembly as advancement would report a project improving each
        time somebody looked at it.
        """

        readiness = ReadinessService(factory)
        before = readiness.calculate(unfinished["project"]).percentage

        AssemblyService(factory).assemble(unfinished["project"], AssemblyPurpose.IMPLEMENTATION)
        PreliminaryContextService(factory).compose(unfinished["project"], AssemblyPurpose.DISCOVERY)

        assert readiness.calculate(unfinished["project"]).percentage == before
