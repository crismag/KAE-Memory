"""An area may ask for more than one thing, and must say when it has only one.

`RUN-D14`. `problem_and_value` covers two distinguishable claims — what hurts,
and why solving it is worth doing — and nothing inside it distinguished them.
So `value` was reported empty for every project in existence, and the Definition
page said so for a reason it could not explain.

## The alternative that was rejected

Splitting the area in two would rebalance every weight and change the readiness
of every project already evaluated. `RUN-C1` ruled against redistribution for
exactly that reason. A claim subdivides an area **without touching its weight**,
which is why the other nine areas are unaffected and why the arithmetic of a
project that never touched `problem_and_value` is identical.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kae_memory.application import MemoryService, ReadinessService, WriteKnowledgeRequest
from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.execution import AgentRole
from kae_memory.domain.identifiers import ProjectId
from kae_memory.domain.models import KnowledgeItem
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE, AreaState

AREA = "problem_and_value"


@pytest.fixture
def services(factory: sessionmaker[Session]) -> tuple[MemoryService, ReadinessService]:
    readiness = ReadinessService(factory)
    readiness.install_template()
    return MemoryService(factory), readiness


def _state(readiness: ReadinessService, project: ProjectId, key: str = AREA) -> AreaState:
    snapshot = readiness.calculate(project)
    return next(area.state for area in snapshot.areas if area.key == key)


def _confirmed(memory: MemoryService, project: ProjectId, key: str, text: str) -> KnowledgeItem:
    run = memory.start_run(project, AgentRole.REQUIREMENTS, key)
    item = memory.write_knowledge(
        run.id, [WriteKnowledgeRequest(kind="goal", content=text, source="test")]
    )[0]
    return memory.confirm_knowledge(item.id)


class TestADividedAreaNeedsEveryClaim:
    def test_the_problem_alone_does_not_complete_it(
        self, services: tuple[MemoryService, ReadinessService], factory: sessionmaker[Session]
    ) -> None:
        """The finding, stated as behaviour.

        Three confirmed problem statements and no value statement is one of two
        claims established. Calling that sufficient is what let `value` read as
        covered while being empty.
        """

        memory, readiness = services
        project = memory.create_project("Divided", key="claims-problem-only")
        for n in range(3):
            item = _confirmed(memory, project.id, f"p{n}", f"Scattered thinking, {n}.")
            readiness.assign_area(project.id, item.id, AREA, claim_key="problem_statement")

        assert _state(readiness, project.id) is AreaState.PARTIAL

    def test_both_claims_complete_it(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        memory, readiness = services
        project = memory.create_project("Divided", key="claims-both")

        problem = _confirmed(memory, project.id, "p", "People cannot move a project forward.")
        readiness.assign_area(project.id, problem.id, AREA, claim_key="problem_statement")
        value = _confirmed(memory, project.id, "v", "Deciding once is worth the time it saves.")
        readiness.assign_area(project.id, value.id, AREA, claim_key="value_proposition")

        assert _state(readiness, project.id) is AreaState.SUFFICIENT

    def test_an_unclaimed_assignment_counts_toward_the_area_but_completes_nothing(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Every link written before claims existed is one of these.

        It said "this is about the problem and value of this project", which is
        still true and simply does not say which half. So it earns partial
        credit and cannot earn full — which is the honest reading, and the
        reason the migration backfills nothing.
        """

        memory, readiness = services
        project = memory.create_project("Divided", key="claims-unclaimed")
        item = _confirmed(memory, project.id, "u", "Something about the problem.")
        readiness.assign_area(project.id, item.id, AREA)

        assert _state(readiness, project.id) is AreaState.PARTIAL

    def test_an_untouched_divided_area_is_still_missing(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Partial must mean *some*, not *any area with claims*."""

        memory, readiness = services
        project = memory.create_project("Divided", key="claims-empty")

        assert _state(readiness, project.id) is AreaState.MISSING


class TestUndividedAreasAreUnaffected:
    def test_one_confirmed_item_still_completes_a_single_claim_area(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Nine of ten areas must behave exactly as they did.

        This is what makes the change additive: if a claim-less area started
        needing something new, every project's number would move for a reason
        nobody asked for.
        """

        memory, readiness = services
        project = memory.create_project("Undivided", key="claims-undivided")
        item = _confirmed(memory, project.id, "s", "In scope: the inbox.")
        readiness.assign_area(project.id, item.id, "scope_and_boundaries")

        assert _state(readiness, project.id, "scope_and_boundaries") is AreaState.SUFFICIENT

    def test_a_claim_key_on_an_area_that_has_none_is_refused(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        memory, readiness = services
        project = memory.create_project("Undivided", key="claims-refused")
        item = _confirmed(memory, project.id, "s", "In scope: the inbox.")

        with pytest.raises(DomainInvariantError) as raised:
            readiness.assign_area(
                project.id, item.id, "scope_and_boundaries", claim_key="problem_statement"
            )

        assert "has no claim" in str(raised.value)

    def test_an_unknown_claim_is_refused_rather_than_ignored(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """A typo silently dropped leaves a statement counting toward nothing.

        Its author would believe they had completed something. Refusing names
        the claims that exist, so the fix is in the message.
        """

        memory, readiness = services
        project = memory.create_project("Divided", key="claims-typo")
        item = _confirmed(memory, project.id, "p", "People cannot move forward.")

        with pytest.raises(DomainInvariantError) as raised:
            readiness.assign_area(project.id, item.id, AREA, claim_key="problem_statment")

        assert "problem_statement" in str(raised.value)
        assert "value_proposition" in str(raised.value)


class TestTheTemplateSaysWhatChanged:
    def test_the_version_moved_because_the_rule_did(self) -> None:
        """A stricter rule under an unchanged version rewrites history silently.

        `problem_and_value` used to complete on one confirmed item and now needs
        both claims, so a project evaluated under v1 could report lower under
        v2. That is precisely what a version number is for.
        """

        assert SOFTWARE_TEMPLATE.version == 2

    def test_no_weight_changed(self) -> None:
        """`RUN-C1` ruled against redistribution, and claims obey it.

        Subdividing an area must not alter what it is worth, or the ruling would
        have been circumvented by a different route.
        """

        weights = {area.key: area.weight for area in SOFTWARE_TEMPLATE.areas}

        assert weights[AREA] == 1.5
        assert sum(weights.values()) == 12.5

    def test_exactly_one_area_is_divided(self) -> None:
        divided = [area.key for area in SOFTWARE_TEMPLATE.areas if area.is_divided]

        assert divided == [AREA]


class TestAStoredVersionIsImmutable:
    """Editing a version in place makes every snapshot recorded against it a lie.

    `upsert` rewrote `definition` for an existing `(key, version)` and its own
    docstring said a version was "immutable in intent". Intent is not
    enforcement: changing `SOFTWARE_TEMPLATE` without bumping the version
    silently rewrote the stored v1, and readiness history is only interpretable
    if a version means one thing forever.
    """

    def test_installing_the_same_template_twice_is_a_no_op(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Which is what makes startup idempotent, and must keep working."""

        readiness = ReadinessService(factory)
        readiness.install_template()
        readiness.install_template()

    def test_a_different_definition_under_the_same_version_is_refused(
        self, factory: sessionmaker[Session]
    ) -> None:
        from dataclasses import replace

        readiness = ReadinessService(factory)
        readiness.install_template()

        # The same version, one area's requirement quietly raised. This is the
        # edit that used to succeed.
        edited = replace(
            SOFTWARE_TEMPLATE,
            areas=tuple(
                replace(area, minimum_confirmed=area.minimum_confirmed + 1)
                if area.key == "scope_and_boundaries"
                else area
                for area in SOFTWARE_TEMPLATE.areas
            ),
        )

        with pytest.raises(DomainInvariantError) as raised:
            ReadinessService(factory, template=edited).install_template()

        assert "immutable" in str(raised.value)
        # And it says what to do instead, because the correct action is not
        # obvious at the moment somebody hits this.
        assert "publish a new version" in str(raised.value)


class TestAProjectIsPinnedToTheTemplateItWasEvaluatedUnder:
    """A recalculation must not change what a number means.

    Every review run now recalculates readiness, and the service holds the
    *current* shipped template. Publishing version 2 would therefore have
    re-evaluated every existing project under stricter semantics nobody adopted
    — and a user watching their percentage would have seen it fall for a reason
    that had nothing to do with their project.
    """

    def test_a_new_project_uses_the_current_template(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        """Nothing to preserve, so nothing to pin."""

        memory, readiness = services
        project = memory.create_project("Fresh", key="pin-fresh")

        snapshot = readiness.calculate(project.id)

        assert snapshot.template_version == SOFTWARE_TEMPLATE.version

    def test_a_pinned_project_keeps_its_version_across_recalculation(
        self, factory: sessionmaker[Session]
    ) -> None:
        """The scenario the pin exists for, built rather than described.

        A project is evaluated under v1, v2 is published, and the project is
        recalculated — by a review run, on its own, with nobody asking.
        """

        from dataclasses import replace

        v1 = replace(SOFTWARE_TEMPLATE, version=1)
        memory = MemoryService(factory)
        older = ReadinessService(factory, template=v1)
        older.install_template()
        project = memory.create_project("Pinned", key="pin-v1")
        first = older.calculate(project.id)
        assert first.template_version == 1

        current = ReadinessService(factory)
        current.install_template()
        again = current.calculate(project.id)

        assert again.template_version == 1, (
            "a recalculation moved the project to a template version nobody adopted"
        )

    def test_adopting_the_current_template_is_an_explicit_act(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Moving forward is available — it just has to be asked for."""

        from dataclasses import replace

        v1 = replace(SOFTWARE_TEMPLATE, version=1)
        memory = MemoryService(factory)
        older = ReadinessService(factory, template=v1)
        older.install_template()
        project = memory.create_project("Adopting", key="pin-adopt")
        older.calculate(project.id)

        current = ReadinessService(factory)
        current.install_template()
        moved = current.calculate(project.id, adopt_current_template=True)

        assert moved.template_version == SOFTWARE_TEMPLATE.version

    def test_the_history_of_a_moved_project_keeps_both_versions(
        self, factory: sessionmaker[Session]
    ) -> None:
        """Snapshots are append-only, so the old number keeps its own label.

        Which is the whole reason a version is worth having: two numbers that
        disagree are interpretable when each says what it was computed under.
        """

        from dataclasses import replace

        v1 = replace(SOFTWARE_TEMPLATE, version=1)
        memory = MemoryService(factory)
        older = ReadinessService(factory, template=v1)
        older.install_template()
        project = memory.create_project("History", key="pin-history")
        older.calculate(project.id)

        current = ReadinessService(factory)
        current.install_template()
        current.calculate(project.id, adopt_current_template=True)

        versions = [s.template_version for s in current.history(project.id)]
        assert set(versions) == {1, SOFTWARE_TEMPLATE.version}


class TestAPinnedProjectCanTellItIsPinned:
    """The pin must be visible, or a deliberate choice becomes a silent one.

    `is_stale_against` asks whether the *project* moved. Nothing asked whether
    the meaning of the number moved — so a project could sit on version 1
    indefinitely, with every snapshot computed under semantics no longer
    current, and no surface anywhere said so.
    """

    def test_a_current_project_is_not_behind(
        self, services: tuple[MemoryService, ReadinessService]
    ) -> None:
        memory, readiness = services
        project = memory.create_project("Current", key="behind-current")

        snapshot = readiness.calculate(project.id)

        assert snapshot.is_behind_template(SOFTWARE_TEMPLATE.version) is False

    def test_a_pinned_project_reports_that_a_newer_template_exists(
        self, factory: sessionmaker[Session]
    ) -> None:
        from dataclasses import replace

        v1 = replace(SOFTWARE_TEMPLATE, version=1)
        memory = MemoryService(factory)
        older = ReadinessService(factory, template=v1)
        older.install_template()
        project = memory.create_project("Behind", key="behind-pinned")
        older.calculate(project.id)

        current = ReadinessService(factory)
        current.install_template()
        again = current.calculate(project.id)

        assert again.template_version == 1
        # Not stale — nothing about the project changed. Behind, which is the
        # distinction that had no expression.
        assert again.is_stale_against(again.knowledge_revision) is False
        assert again.is_behind_template(SOFTWARE_TEMPLATE.version) is True

    def test_being_behind_does_not_move_the_project(self, factory: sessionmaker[Session]) -> None:
        """Reported, never acted on.

        A number that adopted a new template because it noticed one exists would
        be exactly the silent re-evaluation the pin was built to prevent.
        """

        from dataclasses import replace

        v1 = replace(SOFTWARE_TEMPLATE, version=1)
        memory = MemoryService(factory)
        older = ReadinessService(factory, template=v1)
        older.install_template()
        project = memory.create_project("Behind", key="behind-noop")
        older.calculate(project.id)

        current = ReadinessService(factory)
        current.install_template()
        for _ in range(3):
            snapshot = current.calculate(project.id)

        assert snapshot.template_version == 1
