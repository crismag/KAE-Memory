"""The relationship vocabulary (N16, ADR-0025).

Four lists existed and they were never four versions of one thing. Three
described system structure and one described how statements relate, which is
why `depends_on` appeared in three of four and why picking a winner would have
produced a vocabulary serving neither purpose.

What these tests hold is the boundary:

    an edge between two statements is epistemic;
    an edge that touches a module is structural.

And the rule that shrank the epistemic register from seven terms to three: **a
vocabulary term nobody writes has no defined meaning.** The first caller to use
one would be inventing the semantics rather than applying them, and this was the
last moment retiring a term was a rename rather than a migration — zero rows
existed in `knowledge_relationships` when the decision was made.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.models import RelationshipType
from kae_memory.domain.relationships import (
    ACYCLIC,
    DIRECTIONS,
    EXCLUSIVE,
    RETIRED,
    KnowledgeRelation,
    ModuleRelation,
    is_structural,
    resolve,
)


class TestTheTwoRegistersAreSeparate:
    def test_no_name_appears_in_both(self) -> None:
        """The boundary this decision exists to draw."""

        overlap = {r.value for r in KnowledgeRelation} & {r.value for r in ModuleRelation}

        assert not overlap

    def test_statements_do_not_depend_on_statements(self) -> None:
        """`depends_on` is structural, and its absence here is the point.

        One statement does not depend on another. It follows from it,
        contradicts it, or is replaced by it.
        """

        assert "depends_on" not in {r.value for r in KnowledgeRelation}

    def test_modules_do_not_contradict(self) -> None:
        """Readiness gates on contradiction. Build order does not."""

        assert "contradicts" not in {r.value for r in ModuleRelation}

    def test_is_structural_separates_them(self) -> None:
        assert is_structural(ModuleRelation.DEPENDS_ON) is True
        assert is_structural(KnowledgeRelation.CONTRADICTS) is False


class TestTheEpistemicRegisterIsWhatIsWritten:
    def test_it_holds_exactly_the_three_relations_code_writes(self) -> None:
        """Seven became three, and the count is the decision."""

        assert {r.value for r in KnowledgeRelation} == {"supports", "contradicts", "supersedes"}

    def test_the_shipped_name_still_resolves(self) -> None:
        """`RelationshipType` is an alias, so ADR-0015's call sites keep working."""

        assert RelationshipType is KnowledgeRelation
        assert RelationshipType.CONTRADICTS.value == "contradicts"

    @pytest.mark.parametrize("retired", ["derives_from", "implements", "validates", "blocks"])
    def test_the_unused_values_are_gone(self, retired: str) -> None:
        assert retired not in {r.value for r in KnowledgeRelation}


class TestRetiredNamesResolveToTheirReplacement:
    """Three of the four source documents use at least one retired name."""

    @pytest.mark.parametrize("name", sorted(RETIRED))
    def test_a_retired_name_raises_with_the_reason(self, name: str) -> None:
        """Louder than ignoring it, and more useful than "unknown"."""

        with pytest.raises(DomainInvariantError) as raised:
            resolve(name)

        assert RETIRED[name] in str(raised.value)

    def test_the_two_that_moved_name_where_they_went(self) -> None:
        assert "SATISFIES" in RETIRED["implements"]
        assert "VERIFIED_BY" in RETIRED["validates"]

    def test_the_two_that_were_retired_say_why(self) -> None:
        assert "provenance" in RETIRED["derives_from"]
        assert "blockers are their own record" in RETIRED["blocks"]

    def test_an_unknown_name_lists_the_vocabulary(self) -> None:
        with pytest.raises(DomainInvariantError) as raised:
            resolve("relates_to")

        assert "depends_on" in str(raised.value)
        assert "contradicts" in str(raised.value)

    def test_every_current_name_resolves(self) -> None:
        for relation in (*KnowledgeRelation, *ModuleRelation):
            assert resolve(relation.value) is relation

    def test_resolution_tolerates_wording_not_meaning(self) -> None:
        assert resolve("  DEPENDS_ON  ") is ModuleRelation.DEPENDS_ON


class TestTheStructuralRegisterMatchesItsConsumer:
    def test_it_is_studios_six_terms(self) -> None:
        """A vocabulary the consumer must translate gets translated twice, differently."""

        assert {r.value for r in ModuleRelation} == {
            "depends_on",
            "owns",
            "exposes",
            "consumes",
            "satisfies",
            "verified_by",
        }

    def test_dependency_and_ownership_must_stay_acyclic(self) -> None:
        assert ModuleRelation.DEPENDS_ON in ACYCLIC
        assert ModuleRelation.OWNS in ACYCLIC

    def test_consumption_may_be_mutual(self) -> None:
        """Forbidding it would model a rule the architecture does not have."""

        assert ModuleRelation.CONSUMES not in ACYCLIC

    def test_ownership_is_exclusive(self) -> None:
        """Two modules that each own the target means nobody is answerable."""

        assert {ModuleRelation.OWNS} == EXCLUSIVE

    def test_every_relation_states_which_way_it_reads(self) -> None:
        """ "A depends_on B" and "B depends_on A" are both readable English.

        Only one is true, and getting it backwards is a build order that runs
        in reverse.
        """

        described = {direction.relation for direction in DIRECTIONS}

        assert described == set(ModuleRelation)
        for direction in DIRECTIONS:
            assert direction.forward and direction.inverse
            assert direction.forward != direction.inverse


class TestNothingIsDeclaredAheadOfAWriter:
    def test_the_epistemic_register_has_no_speculative_terms(self) -> None:
        """The rule that shrank it, asserted so it cannot quietly grow back.

        A term added here needs a code path that writes it. `ModuleRelation` is
        exempt while N17-N19 are open, and that exemption ends when they close.
        """

        assert len(KnowledgeRelation) == 3
