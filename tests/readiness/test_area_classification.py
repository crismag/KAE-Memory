"""The offline content classifier, checked on its own terms.

Where it is *scored* is the AWS Compute Lab fixture, against `EXPECTED_AREAS`
labels written before the classifier existed. That is the test of whether it
places statements correctly, and it belongs there because a table graded on
examples chosen next to it grades nothing (`D-16`).

What is checked here is the property the scoring cannot see: that the module
stays inside the template. A signal naming an area `SOFTWARE_TEMPLATE` does not
define is dead vocabulary that never fires and reports nothing; a placement
outside the areas a kind is already accepted by would widen the mapping by the
back door, which `RUN-C1` rules out. Both failures raise the score on the
fixture rather than lowering it, so no accuracy measurement will catch either.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.area_classification import (
    _SIGNALS,
    DEFAULT_AREA_FOR_KIND,
    HIGH,
    LOW,
    areas_accepting,
    classify_by_content,
    classify_corpus,
)
from kae_memory.domain.readiness import SOFTWARE_TEMPLATE

KINDS = sorted({member.value for area in SOFTWARE_TEMPLATE.areas for member in area.kinds})


class TestTheVocabularyIsAboutAreasThatExist:
    @pytest.mark.parametrize("area_key", sorted({area for area, _, _, _ in _SIGNALS}))
    def test_every_signal_names_an_area_the_template_defines(self, area_key: str) -> None:
        """A misspelt area key is a signal that can never fire.

        `classify_by_content` only scores signals whose area is among the
        candidates, so a typo is discarded in silence — the statement falls to
        its kind's default and the run reports ``low`` as if the wording had
        been uninformative. Nothing else in the suite distinguishes a signal
        that found no evidence from one that cannot be reached.
        """

        assert area_key in {area.key for area in SOFTWARE_TEMPLATE.areas}


class TestPlacementStaysInsideTheTemplate:
    @pytest.mark.parametrize("kind", KINDS)
    def test_a_placement_is_always_an_area_the_kind_already_reaches(self, kind: str) -> None:
        """`RUN-C1`: redistribution is not the cheap route to a better number."""

        candidates = areas_accepting(kind)
        placement = classify_by_content(kind, "Reports must be approved by an authorised approver.")

        if not candidates:
            assert placement is None
            return
        assert placement is not None
        assert placement.area_key in candidates

    @pytest.mark.parametrize("kind", sorted(DEFAULT_AREA_FOR_KIND))
    def test_each_default_is_an_area_that_kind_can_reach(self, kind: str) -> None:
        """The default is taken without re-checking the candidates.

        A default outside them would place the statement where the template
        does not accept it, for exactly the statements that said nothing — the
        majority.
        """

        assert DEFAULT_AREA_FOR_KIND[kind] in areas_accepting(kind)

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_kind_with_a_choice_to_make_has_a_default(self, kind: str) -> None:
        """Otherwise an uninformative statement of that kind raises."""

        if len(areas_accepting(kind)) > 1:
            assert kind in DEFAULT_AREA_FOR_KIND


class TestConfidenceMeansWhatItSays:
    def test_a_kind_only_one_area_accepts_is_placed_with_no_reading_at_all(self) -> None:
        assert areas_accepting("actor") == ("users_and_stakeholders",)

        placement = classify_by_content("actor", "Ministry leaders submit monthly reports.")

        assert placement is not None
        assert placement.area_key == "users_and_stakeholders"
        assert placement.confidence == HIGH

    def test_a_statement_that_chooses_nothing_is_reported_low(self) -> None:
        """`low` is the run's honesty about how much the text contributed.

        The worker carries the split out as ``offline_confidence`` precisely so
        a run that read its statements is distinguishable from one that
        defaulted them all.
        """

        placement = classify_by_content("requirement", "The thing must happen.")

        assert placement is not None
        assert placement.area_key == DEFAULT_AREA_FOR_KIND["requirement"]
        assert placement.confidence == LOW

    def test_a_statement_that_chooses_is_not_reported_low(self) -> None:
        placement = classify_by_content(
            "requirement", "A consumer must not need to know which producer wrote the record."
        )

        assert placement is not None
        assert placement.area_key == "quality_attributes"
        assert placement.confidence != LOW
        assert placement.rationale


class TestKindsWithNoAreaAtAll:
    def test_an_open_question_is_not_placed(self) -> None:
        """``unknown`` reaches no area, and abstaining there is correct.

        The classifier exists because abstaining put 692 rows in front of a
        person. It does not follow that everything must be placed: an open
        question is not knowledge about a discovery area however it is worded.
        """

        assert areas_accepting("unknown") == ()
        assert classify_by_content("unknown", "Do we need a second approver?") is None


def test_a_corpus_keeps_its_order_and_its_gaps() -> None:
    """Callers zip the result against the items they passed in."""

    placements = classify_corpus(
        [
            ("actor", "Ministry leaders submit monthly reports."),
            ("unknown", "Do we need a second approver?"),
            ("requirement", "The system must notify the approver."),
        ]
    )

    assert len(placements) == 3
    assert placements[0] is not None and placements[0].area_key == "users_and_stakeholders"
    assert placements[1] is None
    assert placements[2] is not None
