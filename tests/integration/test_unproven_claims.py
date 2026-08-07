"""Executable proof for the claims the findings register could only reason about.

`specifications/FINDINGS_REGISTER.md` carries an S4 table — "reasonable,
unconfirmed" — of five claims believed true because the code appears to say so.
Reading code is how you form a hypothesis, not how you settle one, and the
register is explicit that none of them may be stated as fact until checked.

Each test below is the "confirm by" column of that table, run rather than
argued. Two of the five entries turned out to be wrong about their own status:

* **F-014's claim is false.** See `TestF014`.
* **F-015 was already proven.** `tests/application/test_message_idempotency.py`
  has run eight concurrent submissions of one key against the real engine since
  ADR-0018, and asserts something stricter than the register asked for — exactly
  one creator and seven replays. It is not repeated here; the register was
  simply unaware of it.

These are integration tests on purpose. Every claim here is about a *seam* —
between the domain and the schema, between two projects, between a service and
its adapter — and a unit test with a mock on one side of a seam is a test of the
mock.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, WriteKnowledgeRequest
from kae_memory.application.module_service import ModuleService
from kae_memory.domain.errors import InvalidLifecycleTransitionError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.lifecycle import LifecycleState
from kae_memory.domain.models import KnowledgeKind
from kae_memory.domain.modules import CyclicModuleGraphError
from kae_memory.domain.relationships import ModuleRelation


def _one(memory: MemoryService, project: ProjectId, item_id: Any) -> Any:
    """The one item with this id. There is no single-item read on the service."""

    match = [item for item in memory.retrieve_knowledge(project, None) if item.id == item_id]
    assert len(match) == 1, f"expected one item {item_id}, found {len(match)}"
    return match[0]


def _project(memory: MemoryService, name: str) -> ProjectId:
    return ProjectId(str(memory.create_project(name).id))


def _write(memory: MemoryService, project: ProjectId, *texts: str) -> tuple[Any, ...]:
    run = memory.start_run(project, AgentRole.REQUIREMENTS, f"proof-{project}-{texts[0][:12]}")
    return memory.write_knowledge(
        run.id,
        [
            WriteKnowledgeRequest(KnowledgeKind.CONSTRAINT.value, body, "interview")
            for body in texts
        ],
    )


@pytest.fixture
def memory(factory: sessionmaker[Session]) -> MemoryService:
    return MemoryService(factory)


class TestF011DirectWritesBypassTheDomain:
    """ADR-0027's central premise, previously reasoned rather than demonstrated.

    The ADR says application contracts are *the* write path. That is only worth
    stating if going around them actually loses something — so this writes a
    state the domain forbids, straight into the table, and shows it lands.

    This is a test that the system is **not** defended at the schema level. It
    passing is not good news; it is the evidence for the ADR. If it ever fails
    because a constraint was added, delete it and say so in the ADR — a database
    that enforces the transition is strictly better than a document asking
    people to.
    """

    def test_the_domain_refuses_the_transition(self, memory: MemoryService) -> None:
        """First half: establish that the rule exists."""

        project = _project(memory, "F-011 domain")
        (item,) = _write(memory, project, "Invoices carry a client reference.")
        memory.reject_knowledge(item.id)

        # rejected is terminal — _ALLOWED_TRANSITIONS gives it an empty set.
        with pytest.raises(InvalidLifecycleTransitionError):
            memory.confirm_knowledge(item.id)

    def test_a_direct_write_lands_the_forbidden_state_anyway(
        self, memory: MemoryService, factory: sessionmaker[Session]
    ) -> None:
        """Second half: the same transition, in SQL, is simply accepted."""

        project = _project(memory, "F-011 sql")
        (item,) = _write(memory, project, "Invoices are sent within three days.")
        memory.reject_knowledge(item.id)

        with factory() as session:
            session.execute(
                text("UPDATE knowledge_items SET lifecycle = :target WHERE id = :id"),
                {"target": LifecycleState.VALIDATED.value, "id": str(item.id)},
            )
            session.commit()

        reloaded = _one(memory, project, item.id)
        assert reloaded.lifecycle is LifecycleState.VALIDATED, (
            "the database accepted rejected -> validated, which the domain refuses. "
            "This is the gap ADR-0027 exists to describe."
        )

    def test_the_bypassed_state_is_indistinguishable_afterwards(
        self, memory: MemoryService, factory: sessionmaker[Session]
    ) -> None:
        """And nothing downstream can tell.

        The reason the bypass matters is not that one row is wrong. It is that
        the row is *unremarkable* once written — it reads as ordinary confirmed
        knowledge, counts toward readiness, and reaches assembly. There is no
        marker, so no consumer can filter it out.
        """

        project = _project(memory, "F-011 downstream")
        (honest,) = _write(memory, project, "A thought is captured in one step.")
        (smuggled,) = _write(memory, project, "Nothing is ever deleted.")
        memory.confirm_knowledge(honest.id)
        memory.reject_knowledge(smuggled.id)

        with factory() as session:
            session.execute(
                text("UPDATE knowledge_items SET lifecycle = 'validated' WHERE id = :id"),
                {"id": str(smuggled.id)},
            )
            session.commit()

        confirmed = {
            item.id for item in memory.retrieve_knowledge(project, LifecycleState.VALIDATED)
        }
        assert {honest.id, smuggled.id} <= confirmed


class TestF012ProjectsAreIsolated:
    """Two projects holding near-identical records must never see each other.

    Deliberately *near-identical* text. Isolation that only works when the
    contents differ is not isolation, it is a coincidence — and a collapse-key
    or embedding path that keys on content is exactly where a leak would come
    from.
    """

    SHARED = "Invoices must be sent within three days of a job finishing."

    def test_reads_do_not_bleed(self, memory: MemoryService) -> None:
        left = _project(memory, "F-012 left")
        right = _project(memory, "F-012 right")
        _write(memory, left, self.SHARED)
        _write(memory, right, self.SHARED)

        for project in (left, right):
            items = memory.retrieve_knowledge(project, None)
            assert len(items) == 1, f"{project} sees {len(items)} items, expected only its own"
            assert items[0].project_id == project

    def test_identical_text_does_not_collapse_across_projects(self, memory: MemoryService) -> None:
        """The collapse key must be project-scoped.

        `write_knowledge` merges a new statement into an existing one with the
        same kind and content. If that lookup were global, the second project's
        write would attach its provenance to the first project's item — and the
        symptom would be a project silently missing knowledge someone recorded.
        """

        left = _project(memory, "F-012 collapse left")
        right = _project(memory, "F-012 collapse right")
        (first,) = _write(memory, left, self.SHARED)
        (second,) = _write(memory, right, self.SHARED)

        assert first.id != second.id

    def test_a_confirmation_in_one_project_does_not_move_the_other(
        self, memory: MemoryService
    ) -> None:
        left = _project(memory, "F-012 confirm left")
        right = _project(memory, "F-012 confirm right")
        (mine,) = _write(memory, left, self.SHARED)
        (theirs,) = _write(memory, right, self.SHARED)

        memory.confirm_knowledge(mine.id)

        assert _one(memory, right, theirs.id).lifecycle is LifecycleState.PROPOSED


class TestF013CyclesAreRefused:
    """`module_service.relate` "appears to check". It does."""

    @pytest.fixture
    def modules(self, factory: sessionmaker[Session]) -> ModuleService:
        return ModuleService(factory)

    def test_a_two_step_cycle_is_refused(
        self, memory: MemoryService, modules: ModuleService
    ) -> None:
        project = _project(memory, "F-013 direct")
        modules.define(project, "billing", "Billing")
        modules.define(project, "ledger", "Ledger")
        modules.relate(project, "billing", ModuleRelation.DEPENDS_ON, "ledger")

        with pytest.raises(CyclicModuleGraphError):
            modules.relate(project, "ledger", ModuleRelation.DEPENDS_ON, "billing")

    def test_a_longer_cycle_is_refused(self, memory: MemoryService, modules: ModuleService) -> None:
        """Three hops, because a check that only looks one edge back would pass
        the test above and still let a real graph close on itself."""

        project = _project(memory, "F-013 transitive")
        for key in ("a", "b", "c"):
            modules.define(project, key, key.upper())
        modules.relate(project, "a", ModuleRelation.DEPENDS_ON, "b")
        modules.relate(project, "b", ModuleRelation.DEPENDS_ON, "c")

        with pytest.raises(CyclicModuleGraphError):
            modules.relate(project, "c", ModuleRelation.DEPENDS_ON, "a")

    def test_the_refusal_leaves_no_edge_behind(
        self, memory: MemoryService, modules: ModuleService
    ) -> None:
        """A rejected write must not be a partial write.

        The check runs inside the transaction that would insert the row, so the
        interesting failure is not "did it raise" but "did it raise *after*
        adding the edge". A cycle recorded and then reported as refused is worse
        than no check.
        """

        project = _project(memory, "F-013 rollback")
        modules.define(project, "billing", "Billing")
        modules.define(project, "ledger", "Ledger")
        modules.relate(project, "billing", ModuleRelation.DEPENDS_ON, "ledger")

        with pytest.raises(CyclicModuleGraphError):
            modules.relate(project, "ledger", ModuleRelation.DEPENDS_ON, "billing")

        graph = modules.graph(project)
        ledger = next(m for m in modules.list_modules(project) if m.key == "ledger")
        assert graph.outgoing(ledger.id, ModuleRelation.DEPENDS_ON) == ()

    def test_a_diamond_is_allowed(self, memory: MemoryService, modules: ModuleService) -> None:
        """Two paths to the same module is not a cycle.

        A depth-first check that marks nodes visited and never clears them
        reports this as one, which would make the graph unusable for exactly
        the shape real systems have.
        """

        project = _project(memory, "F-013 diamond")
        for key in ("api", "left", "right", "store"):
            modules.define(project, key, key.upper())
        modules.relate(project, "api", ModuleRelation.DEPENDS_ON, "left")
        modules.relate(project, "api", ModuleRelation.DEPENDS_ON, "right")
        modules.relate(project, "left", ModuleRelation.DEPENDS_ON, "store")
        modules.relate(project, "right", ModuleRelation.DEPENDS_ON, "store")

        assert len(modules.list_modules(project)) == 4


class TestF014:
    """**The register's claim is wrong.** Recorded here rather than quietly fixed.

    F-014 reads: "Extraction always falls back to a fixture without a model."
    It does not, and the difference matters because the claim describes a system
    that degrades silently — the thing F-008 warns readers about.

    What is actually true:

    * the deterministic fixture is the **default**, and Bedrock is opt-in via
      `KAE_EXTRACTION=bedrock`;
    * an opt-in that cannot be satisfied **raises**, rather than quietly
      returning the fixture;
    * the only component that does degrade is the **reviewer**, and it labels
      the degradation in the run summary.

    So there is no silent fallback to disprove. There is a safe default and a
    loud failure, which is the better design and was never written down.
    """

    def test_the_default_is_the_fixture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kae_memory.agents.deterministic import DeterministicExtractionAdapter
        from kae_memory.worker.execution import default_extractor

        monkeypatch.delenv("KAE_EXTRACTION", raising=False)
        assert isinstance(default_extractor(), DeterministicExtractionAdapter)

    def test_the_fixture_says_it_is_a_fixture(self) -> None:
        """F-008's disposition depends on this string reaching run summaries."""

        from kae_memory.agents.deterministic import DeterministicExtractionAdapter

        assert DeterministicExtractionAdapter.model == "deterministic-fixture"

    def test_an_unsatisfiable_opt_in_raises_rather_than_degrading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The claim's actual counter-example.

        Ask for Bedrock with no region resolvable and the answer is an error.
        Had it returned the fixture, a deployment that believed it was running a
        model would have been running a canned response — and the run summary
        would have been the only clue.
        """

        from kae_memory.worker import execution

        monkeypatch.setenv("KAE_EXTRACTION", "bedrock")
        monkeypatch.setattr(execution, "resolve_region", lambda: "")

        with pytest.raises(RuntimeError, match="region"):
            execution.default_extractor()

    def test_the_reviewer_is_what_degrades_and_it_labels_itself(self) -> None:
        """The real fallback, so the register points at the right component."""

        import inspect

        from kae_memory.worker import execution

        source = inspect.getsource(execution.AgentStepExecutor)
        assert "offline_by_kind_after_reviewer_error" in source, (
            "the reviewer's degraded path must remain labelled in the run summary"
        )
