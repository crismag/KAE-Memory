"""The generation policy contract (N40, scoped to what N42 needs).

One field, deliberately. The product context sketches a whole vocabulary —
provisional inclusion, assumption authority, accepted boundaries, deferred
questions — and inventing a field before its caller exists is exactly how
`supersede_older_versions`, the deliverable qualification, and the assumption
service each shipped unreachable. Three times in one repository is a pattern to
design against rather than a run of bad luck.

What is preserved is *room*: a dataclass takes a field without changing a
signature, an enum takes a value without changing a type. The tests here defend
the two properties that make the room safe to use — defaults that mean the
ordinary behaviour, and an unrecognised key that is refused rather than ignored.
"""

from __future__ import annotations

import pytest

from kae_memory.domain.errors import DomainInvariantError
from kae_memory.domain.generation_policy import (
    SUPPORTED_KEYS,
    DiscoveryExtraction,
    GenerationPolicy,
    from_mapping,
)


class TestTheDefaultIsTheUsefulBehaviour:
    def test_an_absent_policy_extracts_on_submission(self) -> None:
        """The useful case must not be the one a caller has to know to ask for."""

        assert from_mapping(None).extracts_on_submission is True

    def test_an_empty_policy_means_the_same_as_no_policy(self) -> None:
        """What makes the parameter optional everywhere without a second path."""

        assert from_mapping({}) == from_mapping(None) == GenerationPolicy()

    def test_the_opt_out_is_explicit(self) -> None:
        policy = from_mapping({"discovery_extraction": "disabled"})

        assert policy.discovery_extraction is DiscoveryExtraction.DISABLED
        assert policy.extracts_on_submission is False

    def test_only_two_values_exist_so_far(self) -> None:
        """More will be added. None are invented here."""

        assert {value.value for value in DiscoveryExtraction} == {
            "on_submission",
            "disabled",
        }


class TestAnUnhonourablePolicyIsRefused:
    def test_an_unrecognised_key_raises(self) -> None:
        """Accepting it would let a caller believe they configured behaviour
        they had not, and the failure would surface later as the system
        ignoring an instruction rather than as a rejected request."""

        with pytest.raises(DomainInvariantError, match="unsupported generation policy"):
            from_mapping({"assumption_authority": "delegate"})

    def test_the_refusal_names_what_is_supported(self) -> None:
        with pytest.raises(DomainInvariantError) as raised:
            from_mapping({"not_a_policy": True})

        assert "discovery_extraction" in str(raised.value)

    def test_an_unknown_value_names_the_valid_ones(self) -> None:
        with pytest.raises(DomainInvariantError, match="expected one of"):
            from_mapping({"discovery_extraction": "sometimes"})

    def test_wording_is_tolerated_and_meaning_is_not_guessed(self) -> None:
        assert from_mapping({"discovery_extraction": "  DISABLED "}).extracts_on_submission is False


class TestRoomIsPreservedWithoutBeingUsed:
    def test_supported_keys_matches_the_fields(self) -> None:
        """Adding a field is a deliberate two-line change: the field, and its
        admission here. A field in one and not the other fails rather than
        half-working."""

        from dataclasses import fields

        assert {field.name for field in fields(GenerationPolicy)} == SUPPORTED_KEYS

    def test_the_policy_echoes_what_it_resolved(self) -> None:
        """A policy that is not echoed is one a caller cannot verify they set."""

        assert from_mapping({"discovery_extraction": "disabled"}).as_dict() == {
            "discovery_extraction": "disabled"
        }

    def test_it_holds_exactly_one_field_for_now(self) -> None:
        """Asserted so that broadening it is a decision rather than a drift.

        The next field arrives with the caller that needs it, and this test is
        where that intent gets stated out loud.
        """

        from dataclasses import fields

        assert [field.name for field in fields(GenerationPolicy)] == ["discovery_extraction"]
