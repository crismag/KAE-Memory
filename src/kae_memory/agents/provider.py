"""Choosing an embedding provider, and refusing to guess when it cannot.

One place decides which embedder runs, so the MCP server, the worker, and any
script agree about what produced a vector. Selection is explicit — a deployment
that meant to use Titan and silently fell back to hash-derived vectors would
report ``semantic_search_available`` correctly and still be wrong about why.

``KAE_EMBEDDING`` selects:

* ``deterministic`` (default) — hash-derived, offline, no credentials. Exercises
  the pipeline and cannot rank meaning.
* ``titan`` — Amazon Titan Text Embeddings V2 on Bedrock (ADR-0008).

The default is deterministic on purpose. A cloned repository must walk the whole
workflow with no account, no credentials, and no bill.
"""

import os
from collections.abc import Mapping

from .embedding import DeterministicEmbeddingAdapter, EmbeddingPort
from .titan import TitanEmbeddingAdapter

DETERMINISTIC = "deterministic"
TITAN = "titan"

_SEMANTIC_PROVIDERS = frozenset({TITAN})
"""Providers whose vectors encode meaning.

The deterministic adapter is absent by construction: it produces unit vectors
that pass every structural check and rank at chance, so a response ranked by it
must never be presented as semantic.
"""


class ProviderConfigurationError(RuntimeError):
    """The requested provider cannot be built from this environment."""


def resolve_region(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the AWS region, or ``None`` if nothing configures one.

    Checks the two environment variables before falling back to the active
    profile. A correctly configured profile should be sufficient on its own;
    demanding ``AWS_REGION`` when ``~/.aws/config`` already carries a region
    makes a valid configuration look broken.
    """

    environ = os.environ if environ is None else environ
    for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        if value := environ.get(name, "").strip():
            return value
    try:
        import boto3
    except ImportError:  # pragma: no cover - depends on extras
        return None
    return boto3.Session().region_name or None


def embedder_name(environ: Mapping[str, str] | None = None) -> str:
    """Return the configured provider name, without building it."""

    environ = os.environ if environ is None else environ
    return environ.get("KAE_EMBEDDING", DETERMINISTIC).strip().lower() or DETERMINISTIC


def ranks_by_meaning(name: str) -> bool:
    """Return whether vectors from ``name`` carry semantic information."""

    return name in _SEMANTIC_PROVIDERS


def build_embedder(environ: Mapping[str, str] | None = None) -> tuple[EmbeddingPort, str]:
    """Return the configured embedder and its name.

    Raises rather than falling back. A deployment that asked for Titan and
    received hash-derived vectors would embed a whole corpus into a space that
    means nothing, and discover it only when recall was measured.
    """

    environ = os.environ if environ is None else environ
    name = embedder_name(environ)

    if name == DETERMINISTIC:
        return DeterministicEmbeddingAdapter(), name

    if name == TITAN:
        region = resolve_region(environ)
        if not region:
            raise ProviderConfigurationError(
                "KAE_EMBEDDING=titan requires an AWS region via AWS_REGION, "
                "AWS_DEFAULT_REGION, or the active AWS profile."
            )
        return TitanEmbeddingAdapter(region=region), name

    raise ProviderConfigurationError(
        f"unknown KAE_EMBEDDING={name!r}. Valid: {DETERMINISTIC}, {TITAN}"
    )


def describe(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return what a health check should say about embedding.

    Reports configuration rather than reachability: building the adapter opens
    no socket, and a probe that billed for a model call every time it ran would
    be a poor health check.
    """

    environ = os.environ if environ is None else environ
    name = embedder_name(environ)
    described: dict[str, object] = {
        "provider": name,
        "ranks_by_meaning": ranks_by_meaning(name),
    }
    if name == TITAN:
        region = resolve_region(environ)
        described["region"] = region or "<unresolved>"
        described["configured"] = bool(region)
    else:
        described["configured"] = True
    return described


__all__ = [
    "DETERMINISTIC",
    "TITAN",
    "ProviderConfigurationError",
    "build_embedder",
    "describe",
    "embedder_name",
    "ranks_by_meaning",
    "resolve_region",
]
