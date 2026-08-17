"""What a deployment may reach, and what each of the four words refuses.

The guard these tests hold is that the profile **constrains and never chooses**
(`D-172`): no case here asserts that a profile selects a provider, because a word
about the deployment deciding which model embedded a corpus would make provenance
a property of the posture rather than of the adapter that read the sentence.
"""

from __future__ import annotations

import pytest

from kae_memory import runtime_profile
from kae_memory.agents.provider import build_classifier, build_embedder
from kae_memory.runtime_profile import (
    HYBRID,
    LOCAL,
    OFFLINE,
    PRODUCTION,
    ProfileViolation,
    Reach,
    permits,
    profile_name,
    reach_of_url,
    require,
)


class TestDeclaringAProfile:
    def test_unset_is_unconstrained(self) -> None:
        assert profile_name({}) is None
        assert permits(None, Reach.HOSTED)

    def test_blank_is_unset_rather_than_invalid(self) -> None:
        assert profile_name({runtime_profile.VARIABLE: "  "}) is None

    def test_case_and_spacing_do_not_make_a_second_profile(self) -> None:
        assert profile_name({runtime_profile.VARIABLE: " Offline "}) == OFFLINE

    def test_an_unknown_word_refuses_rather_than_falling_through(self) -> None:
        # A misspelled profile silently meaning "unconstrained" is the shape
        # `KAE_REVIEW` was fixed for: the operator believes they declared a
        # posture and nothing holds them to it.
        with pytest.raises(ProfileViolation) as error:
            profile_name({runtime_profile.VARIABLE: "airgapped"})

        assert "airgapped" in str(error.value)


class TestTheFourProfilesDiffer:
    """Each word permits a different set, so none of them is decoration."""

    def test_offline_refuses_the_network_and_the_hosted_api(self) -> None:
        assert permits(OFFLINE, Reach.IN_PROCESS)
        assert permits(OFFLINE, Reach.HOST)
        assert not permits(OFFLINE, Reach.NETWORK)
        assert not permits(OFFLINE, Reach.HOSTED)

    def test_local_allows_a_model_on_another_machine_and_no_hosted_api(self) -> None:
        assert permits(LOCAL, Reach.NETWORK)
        assert not permits(LOCAL, Reach.HOSTED)

    def test_hybrid_permits_everything(self) -> None:
        assert all(permits(HYBRID, reach) for reach in Reach)

    def test_production_refuses_the_fixture_adapters(self) -> None:
        # The one refusal that is not about the network: a deployment calling
        # itself production while ranking at chance.
        assert not permits(PRODUCTION, Reach.IN_PROCESS)
        assert permits(PRODUCTION, Reach.HOSTED)

    def test_no_two_profiles_permit_the_same_set(self) -> None:
        sets = [frozenset(r for r in Reach if permits(p, r)) for p in runtime_profile.PROFILES]

        assert len(set(sets)) == len(sets)


class TestReachOfAUrl:
    @pytest.mark.parametrize(
        "url",
        ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"],
    )
    def test_loopback_stays_on_this_machine(self, url: str) -> None:
        assert reach_of_url(url) is Reach.HOST

    @pytest.mark.parametrize("url", ["http://10.0.0.4:11434", "http://gpu-box:11434", ""])
    def test_anything_else_is_the_network(self, url: str) -> None:
        # Including a name that cannot be read: guessing "host" for an
        # unresolvable name would let `offline` pass a call that leaves the
        # machine, which is the one mistake this cannot make.
        assert reach_of_url(url) is Reach.NETWORK


class TestRequire:
    def test_the_refusal_names_the_variable_the_value_and_the_profile(self) -> None:
        with pytest.raises(ProfileViolation) as error:
            require(
                Reach.HOSTED,
                variable="KAE_EMBEDDING",
                value="titan",
                environ={runtime_profile.VARIABLE: OFFLINE},
            )

        message = str(error.value)
        assert "KAE_EMBEDDING" in message
        assert "titan" in message
        assert OFFLINE in message

    def test_a_permitted_reach_passes_silently(self) -> None:
        require(
            Reach.HOST,
            variable="KAE_EMBEDDING",
            value="ollama",
            environ={runtime_profile.VARIABLE: OFFLINE},
        )


class TestTheBuildersHonourTheProfile:
    """The profile is only worth having where a provider is actually built."""

    def test_offline_refuses_titan(self) -> None:
        with pytest.raises(ProfileViolation):
            build_embedder({"KAE_EMBEDDING": "titan", runtime_profile.VARIABLE: OFFLINE})

    def test_offline_refuses_titan_before_asking_for_a_region(self) -> None:
        # A profile that forbids Bedrock should say so whether or not the
        # deployment happens to have a region configured.
        with pytest.raises(ProfileViolation):
            build_embedder(
                {
                    "KAE_EMBEDDING": "titan",
                    "AWS_REGION": "ca-central-1",
                    runtime_profile.VARIABLE: OFFLINE,
                }
            )

    def test_offline_refuses_an_ollama_url_on_another_machine(self) -> None:
        with pytest.raises(ProfileViolation):
            build_embedder(
                {
                    "KAE_EMBEDDING": "ollama",
                    "KAE_OLLAMA_URL": "http://gpu-box:11434",
                    runtime_profile.VARIABLE: OFFLINE,
                }
            )

    def test_local_allows_that_same_url(self) -> None:
        _, name = build_embedder(
            {
                "KAE_EMBEDDING": "ollama",
                "KAE_OLLAMA_URL": "http://gpu-box:11434",
                runtime_profile.VARIABLE: LOCAL,
            }
        )

        assert name == "ollama"

    def test_production_refuses_the_deterministic_embedder(self) -> None:
        with pytest.raises(ProfileViolation):
            build_embedder({runtime_profile.VARIABLE: PRODUCTION})

    def test_production_refuses_the_deterministic_classifier(self) -> None:
        with pytest.raises(ProfileViolation):
            build_classifier({runtime_profile.VARIABLE: PRODUCTION})

    def test_offline_refuses_the_bedrock_classifier(self) -> None:
        with pytest.raises(ProfileViolation):
            build_classifier(
                {"KAE_OBSERVATION_CLASSIFIER": "semantic", runtime_profile.VARIABLE: OFFLINE}
            )

    def test_an_undeclared_profile_leaves_every_provider_selectable(self) -> None:
        # The default has to stay permissive or every existing deployment
        # changes posture without anybody deciding.
        _, name = build_embedder({"KAE_EMBEDDING": "titan", "AWS_REGION": "ca-central-1"})

        assert name == "titan"
