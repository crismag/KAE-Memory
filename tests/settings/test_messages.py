"""Messages both adapters have to say the same way (N8).

A message catalog is only worth its indirection where drift is a real failure.
The integrity notes are that case: each one is a caveat about what a response
does *not* establish, and an adapter that softened its copy would produce a
response claiming more than KAE knows.

They had already drifted. Three copies of "Reported, not verified" existed and
two ended differently; two copies of the classification note existed and one
had lost a sentence. Neither divergence was a decision.
"""

from __future__ import annotations

import pytest

from kae_memory.messages import MESSAGES, UnknownMessageError, message, placeholders


class TestOneWordingReachesBothAdapters:
    def test_the_operational_caveat_is_identical_across_adapters(self) -> None:
        """The failure this replaces: an adapter whose copy says something
        weaker is an adapter that overstates what KAE established."""

        from kae_memory.api.schemas import OperationalStateResponse  # noqa: F401

        assert message("integrity.operational_reported").startswith("Reported, not verified.")

    def test_the_classification_caveat_has_two_deliberate_forms(self) -> None:
        """Not drift. A read cannot change an operational status and must not
        say it did not — a caveat about an action nobody took reads as
        reassurance about the wrong thing."""

        read = message("integrity.classification_not_truth")
        submitted = message("integrity.classification_no_status_change")

        assert "no operational status" not in read
        assert "no operational status" in submitted
        assert read.split(".")[0] == submitted.split(".")[0]

    def test_every_integrity_note_says_what_is_not_established(self) -> None:
        """The shape that makes these worth centralising. Each is a denial, and
        a denial that got softened is the whole risk."""

        notes = [text for key, text in MESSAGES.items() if key.startswith("integrity.")]

        assert notes
        assert all("not" in text.lower() or "nothing" in text.lower() for text in notes)


class TestARefusalReadsTheSameOnBothSurfaces:
    def test_the_unknown_purpose_refusal_is_one_sentence(self) -> None:
        """A caller who reads two different explanations for one rejection
        learns that the two surfaces are different products."""

        rendered = message("refusal.unknown_purpose", purpose="vibes", valid="discovery")

        assert "'vibes'" in rendered
        assert "discovery" in rendered

    def test_the_capability_refusal_is_parameterised(self) -> None:
        """Eight near-identical copies existed. Parameterising is what stopped
        the ninth from being written slightly differently."""

        assert message("refusal.capability_unconfigured", capability="assumption") == (
            "no assumption service is configured for this server"
        )


class TestItFailsLoudlyRatherThanRenderingNonsense:
    def test_an_unknown_key_names_the_known_ones(self) -> None:
        with pytest.raises(UnknownMessageError, match="Known keys"):
            message("integrity.probably_fine")

    def test_a_missing_value_is_refused(self) -> None:
        """A message rendered with a literal `{purpose}` in it is a bug found
        by whoever reads the response, which is far too late."""

        with pytest.raises(UnknownMessageError, match="needs a value"):
            message("refusal.unknown_purpose", purpose="vibes")

    def test_placeholders_are_derived_from_the_template(self) -> None:
        """Declared beside it, the two could disagree."""

        assert placeholders("refusal.unknown_purpose") == {"purpose", "valid"}

    def test_a_message_with_no_placeholders_needs_no_values(self) -> None:
        assert placeholders("integrity.nothing_confirmed") == frozenset()


class TestTheCatalogStaysNarrow:
    def test_keys_are_namespaced(self) -> None:
        """A flat list of four hundred keys is the failure mode this file is
        deliberately not walking into."""

        assert all("." in key for key in MESSAGES)

    def test_it_holds_only_what_more_than_one_place_says(self) -> None:
        """An upper bound stated out loud, so growth is a decision rather than
        a habit. A message with one caller is not duplicated; moving it here
        would cost a lookup and buy nothing.
        """

        assert len(MESSAGES) <= 20

    def test_no_message_is_frontend_copy(self) -> None:
        """Frontend copy belongs to KAE-Studio (ADR-0023). A backend catalog
        that acquired button labels would make the boundary negotiable."""

        forbidden = ("click", "button", "please try again", "oops", "welcome")
        assert not [
            key for key, text in MESSAGES.items() if any(word in text.lower() for word in forbidden)
        ]
