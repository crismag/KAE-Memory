"""The suite must never contact a model provider.

ADR-0006 makes this a hard constraint rather than a convention: determinism comes
from fixtures, and a test that silently reached a provider would be
non-deterministic, slow, billable, and unable to run in CI.
"""

import sys

import pytest

from kae_memory.agents.bedrock import BedrockExtractionAdapter
from kae_memory.agents.extraction import ExtractionRequest, ProviderUnavailableError
from kae_memory.domain.execution import AgentRole


def test_the_provider_sdk_is_never_imported_by_the_suite() -> None:
    """A lazy import is only lazy if nothing above it imports eagerly."""

    assert "anthropic" not in sys.modules, (
        "the provider SDK was imported during the test run; extraction must stay "
        "behind the port and tests must use the deterministic adapter"
    )


def test_constructing_the_bedrock_adapter_opens_no_connection() -> None:
    """Construction is inert; the client is built on first use."""

    adapter = BedrockExtractionAdapter(region="eu-west-1")

    assert adapter.model.startswith("anthropic.")
    assert "anthropic" not in sys.modules


def test_missing_extra_is_reported_as_provider_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the optional extra, the failure is typed rather than an ImportError.

    The absence is *simulated* rather than inferred from the environment. An
    earlier version skipped when ``anthropic`` was already in ``sys.modules``,
    which never fired: installing the extra does not import it. With the extra
    present the test therefore fell through to a real ``extract`` call and
    contacted Bedrock — the exact thing this file exists to prevent.

    Binding the name to ``None`` in ``sys.modules`` makes the import raise
    ``ImportError`` whether or not the package is installed, so the typed-error
    path is exercised identically in both environments and no socket opens.
    """

    monkeypatch.setitem(sys.modules, "anthropic", None)
    adapter = BedrockExtractionAdapter(region="eu-west-1")
    request = ExtractionRequest(role=AgentRole.REQUIREMENTS, source_text="text")

    with pytest.raises(ProviderUnavailableError, match="bedrock extra"):
        adapter.extract(request)
