"""Choosing an embedding provider, and refusing when it cannot be built.

The failure this guards against is quiet: a deployment that asked for Titan,
received hash-derived vectors, embedded a whole corpus into a space that means
nothing, and found out when recall was measured. Selection therefore raises
rather than falling back.
"""

from __future__ import annotations

import pytest

from kae_memory.agents.embedding import DeterministicEmbeddingAdapter
from kae_memory.agents.provider import (
    DETERMINISTIC,
    TITAN,
    ProviderConfigurationError,
    build_embedder,
    describe,
    embedder_name,
    ranks_by_meaning,
    resolve_region,
)
from kae_memory.agents.titan import TitanEmbeddingAdapter


class TestRegionResolution:
    def test_aws_region_wins(self) -> None:
        assert resolve_region({"AWS_REGION": "ca-central-1"}) == "ca-central-1"

    def test_default_region_is_the_fallback(self) -> None:
        assert resolve_region({"AWS_DEFAULT_REGION": "us-east-1"}) == "us-east-1"

    def test_aws_region_beats_default_region(self) -> None:
        resolved = resolve_region({"AWS_REGION": "ca-central-1", "AWS_DEFAULT_REGION": "us-east-1"})

        assert resolved == "ca-central-1"

    def test_blank_values_are_not_a_region(self) -> None:
        """An exported-but-empty variable must not shadow the profile."""

        assert resolve_region({"AWS_REGION": "   ", "AWS_DEFAULT_REGION": "us-east-1"}) == (
            "us-east-1"
        )


class TestSelection:
    def test_deterministic_is_the_default(self) -> None:
        """A clone must walk the workflow with no account and no bill."""

        embedder, name = build_embedder({})

        assert isinstance(embedder, DeterministicEmbeddingAdapter)
        assert name == DETERMINISTIC

    def test_titan_is_built_when_asked_for(self) -> None:
        embedder, name = build_embedder({"KAE_EMBEDDING": "titan", "AWS_REGION": "ca-central-1"})

        assert isinstance(embedder, TitanEmbeddingAdapter)
        assert name == TITAN

    def test_titan_without_a_region_anywhere_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falling back would embed a corpus into a meaningless space silently.

        The ambient developer profile resolves a region, so it is suppressed
        here: this asserts the behaviour when *nothing* configures one.
        """

        import boto3

        monkeypatch.setattr(
            boto3, "Session", lambda *a, **k: type("S", (), {"region_name": None})()
        )

        with pytest.raises(ProviderConfigurationError) as raised:
            build_embedder({"KAE_EMBEDDING": "titan"})

        assert "AWS_REGION" in str(raised.value)
        assert "active AWS profile" in str(raised.value)

    def test_the_active_profile_alone_is_enough(self) -> None:
        """A correctly configured profile should not also need an env var.

        This is the defect recorded against T8: the worker demanded AWS_REGION
        even when ~/.aws/config already carried one.
        """

        import boto3

        if not boto3.Session().region_name:  # pragma: no cover - depends on host
            pytest.skip("no ambient AWS profile region to exercise the fallback")

        _, name = build_embedder({"KAE_EMBEDDING": "titan"})

        assert name == TITAN

    def test_an_unknown_provider_is_rejected(self) -> None:
        with pytest.raises(ProviderConfigurationError) as raised:
            build_embedder({"KAE_EMBEDDING": "wishful"})

        assert "Valid:" in str(raised.value)

    def test_the_name_is_readable_without_building_anything(self) -> None:
        assert embedder_name({"KAE_EMBEDDING": "titan"}) == TITAN
        assert embedder_name({}) == DETERMINISTIC


class TestSemanticClaim:
    def test_the_deterministic_adapter_never_claims_meaning(self) -> None:
        """It produces unit vectors that pass every structural check.

        That is exactly why it must be listed as non-semantic rather than
        inferred to be one.
        """

        assert ranks_by_meaning(DETERMINISTIC) is False

    def test_titan_ranks_by_meaning(self) -> None:
        assert ranks_by_meaning(TITAN) is True

    def test_an_unlisted_provider_is_not_semantic(self) -> None:
        """A new provider is non-semantic until someone says otherwise."""

        assert ranks_by_meaning("something-new") is False


class TestDescribe:
    def test_it_reports_configuration_not_reachability(self) -> None:
        """A probe that billed for a model call every run is a poor probe."""

        described = describe({"KAE_EMBEDDING": "titan", "AWS_REGION": "ca-central-1"})

        assert described == {
            "provider": "titan",
            "ranks_by_meaning": True,
            "region": "ca-central-1",
            "configured": True,
        }

    def test_a_missing_region_reads_as_unconfigured(self) -> None:
        described = describe({"KAE_EMBEDDING": "titan", "AWS_REGION": "", "AWS_DEFAULT_REGION": ""})

        if described["region"] == "<unresolved>":  # no ambient AWS profile
            assert described["configured"] is False

    def test_the_default_is_configured_and_not_semantic(self) -> None:
        assert describe({}) == {
            "provider": "deterministic",
            "ranks_by_meaning": False,
            "configured": True,
        }
