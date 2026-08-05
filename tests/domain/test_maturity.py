"""Deliverable maturity and accepted sufficiency (N38).

Maturity is the most gate-shaped idea in this phase. "Exploratory" through
"production-review candidate" reads as a ladder, and a ladder invites "what
level are you at" — which is one refactor from "you are only at level two, so
you cannot generate". That is the readiness gate again in a third set of words,
and the tests here are mostly about making sure it never arrives.

The second claim: an acceptance is a **record**, not a permission. It says a
named person, at a named time, for a named purpose, decided the current
knowledge was enough for one generation. It marks no question answered and
carries forward to nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.generation import GenerationMode
from kae_memory.domain.maturity import (
    DESCRIBES,
    MATURITY_IS_UNORDERED,
    SUGGESTED_FOR,
    AcceptedSufficiency,
    DeliverableQualification,
    Maturity,
)


def _accepted(**overrides: object) -> AcceptedSufficiency:
    fields: dict[str, object] = {
        "purpose": "prototype implementation",
        "accepted_by": "cris",
        "accepted_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return AcceptedSufficiency(**fields)  # type: ignore[arg-type]


class TestMaturityIsNotALadder:
    def test_nothing_defines_an_order(self) -> None:
        """The guard, findable by anyone about to add one.

        A rank is what turns a description into a threshold, and a threshold is
        what turns "this is exploratory" into "this is not enough".
        """

        from kae_memory.domain import maturity

        assert MATURITY_IS_UNORDERED is True

        # The flag itself is excluded by name. Being findable is its whole job,
        # and a check that flagged its own guard would be removed rather than
        # heeded.
        defined = {name for name in vars(maturity)} - {"MATURITY_IS_UNORDERED"}

        assert not [name for name in defined if "ORDER" in name.upper()]
        assert not [name for name in defined if "RANK" in name.upper()]
        assert not [name for name in defined if "LEVEL" in name.upper()]

    def test_nothing_decides_whether_a_maturity_is_enough(self) -> None:
        """No `is_sufficient`, no `at_least`, no `meets`.

        Each would be a comparison, and a comparison is a gate with a friendly
        name.
        """

        from kae_memory.domain import maturity

        callables = {
            name
            for name, value in vars(maturity).items()
            if callable(value) and not name.startswith("_")
        }

        assert not [n for n in callables if "sufficient" in n.lower()]
        assert not [n for n in callables if "at_least" in n.lower()]
        assert not [n for n in callables if "meets" in n.lower()]

    def test_every_value_says_what_it_means(self) -> None:
        """A label nobody can act on is a label that gets treated as a rank."""

        assert set(DESCRIBES) == set(Maturity)
        for description in DESCRIBES.values():
            assert len(description) > 40

    def test_production_review_candidate_claims_no_verdict(self) -> None:
        """The value most likely to be read as an achievement."""

        assert "the reviewer decides" in DESCRIBES[Maturity.PRODUCTION_REVIEW_CANDIDATE]
        assert "does not claim the review passed" in DESCRIBES[Maturity.PRODUCTION_REVIEW_CANDIDATE]

    def test_a_mode_suggests_a_maturity_and_requires_none(self) -> None:
        """A caller labelling a build package exploratory has described their
        own output accurately, and nothing second-guesses that."""

        assert set(SUGGESTED_FOR) == set(GenerationMode)

        qualification = DeliverableQualification(
            maturity=Maturity.EXPLORATORY, mode=GenerationMode.BUILD
        )

        assert qualification.maturity is Maturity.EXPLORATORY
        assert qualification.mode is GenerationMode.BUILD


class TestAcceptanceIsARecordNotAPermission:
    def test_it_names_the_purpose_it_applies_to(self) -> None:
        """Without one it reads as approval of the project."""

        with pytest.raises(DomainInvariantError, match="names the purpose"):
            _accepted(purpose="  ")

    def test_it_names_who_made_it(self) -> None:
        with pytest.raises(DomainInvariantError, match="nobody is named for"):
            _accepted(accepted_by="")

    def test_it_says_out_loud_that_it_applies_once(self) -> None:
        """Stated in the record rather than left to a reader's assumption.

        This is the field that stops an acceptance being read as standing
        permission for every later generation.
        """

        assert _accepted().as_dict()["applies_to"] == "this generation only"

    def test_it_records_what_was_disclosed(self) -> None:
        """A later reader must be able to tell whether the person accepting
        knew what they were accepting."""

        accepted = _accepted(disclosed=("tenancy is assumed single-user",))

        assert accepted.as_dict()["disclosed"] == ["tenancy is assumed single-user"]

    def test_it_marks_no_question_answered(self) -> None:
        """There is no field for it, deliberately.

        An acceptance that could resolve questions would let "I'll proceed
        anyway" quietly become "these are settled".
        """

        fields = set(_accepted().as_dict())

        assert not [name for name in fields if "resolved" in name or "answered" in name]


class TestQualificationMustBeHonest:
    def test_unconfirmed_content_demands_a_qualification(self) -> None:
        """Silence here is the package claiming more than its evidence."""

        with pytest.raises(DomainInvariantError, match="claiming more than its evidence"):
            DeliverableQualification(
                maturity=Maturity.IMPLEMENTATION_ORIENTED,
                mode=GenerationMode.BUILD,
                unconfirmed_count=3,
            )

    def test_a_qualified_package_is_allowed_to_rest_on_nothing_confirmed(self) -> None:
        """The whole point: qualified, not refused."""

        qualification = DeliverableQualification(
            maturity=Maturity.IMPLEMENTATION_ORIENTED,
            mode=GenerationMode.BUILD,
            confirmed_count=0,
            unconfirmed_count=2,
            qualifications=("Includes statements nobody has confirmed.",),
        )

        assert qualification.rests_on_unconfirmed is True
        assert qualification.as_dict()["confirmed_statements"] == 0

    def test_a_fully_confirmed_package_needs_no_qualification(self) -> None:
        assert DeliverableQualification(
            maturity=Maturity.VALIDATION_ORIENTED,
            mode=GenerationMode.VALIDATE,
            confirmed_count=9,
        )

    def test_the_rendered_record_says_maturity_is_not_permission(self) -> None:
        """Carried in the payload, because the reader who most needs it is the
        one who never read this module."""

        rendered = DeliverableQualification(
            maturity=Maturity.PROVISIONAL, mode=GenerationMode.PLAN
        ).as_dict()

        assert "not a permission level" in str(rendered["note"])
        assert rendered["maturity_means"] == DESCRIBES[Maturity.PROVISIONAL]

    def test_gaps_travel_with_the_qualification(self) -> None:
        rendered = DeliverableQualification(
            maturity=Maturity.PROVISIONAL,
            mode=GenerationMode.PLAN,
            material_assumptions=("single tenant",),
            open_decisions=("which database",),
            contradictions=("two sources disagree on retention",),
            deferred_questions=("payment provider",),
        ).as_dict()

        assert rendered["material_assumptions"] == ["single tenant"]
        assert rendered["open_decisions"] == ["which database"]
        assert rendered["contradictions"] == ["two sources disagree on retention"]
        assert rendered["deferred_questions"] == ["payment provider"]
