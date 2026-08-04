"""Which database this process talks to.

Provider *selection* is configuration, and configuration is not persistence.
Keeping it here rather than inside ``kae_memory.persistence`` is what lets the
API, the worker, and the MCP adapter all resolve their connection without any
of them importing the persistence package — the dependency rule that ADR-0018
enforces with a test, and that the first version of this abstraction broke.

Persistence owns the other half: which DDL a provider compiles, how its vector
index is built, whether its transactions retry. Those need SQL. This does not.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DatabaseProvider(StrEnum):
    """A supported persistence backend."""

    COCKROACHDB = "cockroachdb"
    POSTGRESQL = "postgresql"


class ProviderConfigurationError(RuntimeError):
    """The persistence provider is missing, unknown, or has no connection URL."""


@dataclass(frozen=True, slots=True)
class DatabaseCapabilities:
    """What a provider can do, separately from which provider it is.

    Code should ask what is possible rather than which name is configured. The
    two are related and not the same: a third provider with pgvector would share
    PostgreSQL's capabilities without being PostgreSQL, and a check written
    against the name would silently exclude it.
    """

    native_vector: bool
    """The engine has a built-in vector type, needing no extension."""

    pgvector_extension: bool
    """Vector support comes from pgvector, which must be created in the database."""

    approximate_vector_index: bool
    """An approximate nearest-neighbour index is available."""

    transaction_retry_required: bool
    """Serialization failures are expected and a caller must retry them."""

    distributed_sql: bool
    """The engine distributes SQL execution across nodes."""


CAPABILITIES: dict[DatabaseProvider, DatabaseCapabilities] = {
    DatabaseProvider.COCKROACHDB: DatabaseCapabilities(
        native_vector=True,
        pgvector_extension=False,
        approximate_vector_index=True,
        # Serializable isolation by default, so conflicts surface as SQLSTATE
        # 40001 and a caller that does not retry shows contention to a user.
        transaction_retry_required=True,
        distributed_sql=True,
    ),
    DatabaseProvider.POSTGRESQL: DatabaseCapabilities(
        native_vector=False,
        pgvector_extension=True,
        approximate_vector_index=True,
        # The default isolation cannot raise a serialization failure. Retrying
        # would import a distributed engine's assumptions into one that does
        # not share them.
        transaction_retry_required=False,
        distributed_sql=False,
    ),
}

PROVIDER_VARIABLE = "KAE_DATABASE_PROVIDER"
URL_VARIABLES: dict[DatabaseProvider, str] = {
    DatabaseProvider.COCKROACHDB: "KAE_COCKROACHDB_URL",
    DatabaseProvider.POSTGRESQL: "KAE_POSTGRESQL_URL",
}
FALLBACK_URL_VARIABLE = "KAE_DATABASE_URL"
"""Honoured only once a provider has been named explicitly.

Kept so an existing deployment adds one variable rather than rewriting its
configuration. It never implies a provider: a URL is a connection string, and
reading provider identity out of one is how a deployment ends up pointed at the
right host with the wrong assumptions.
"""


def capabilities_for(provider: DatabaseProvider) -> DatabaseCapabilities:
    """Return what ``provider`` can do."""

    return CAPABILITIES[provider]


def resolve_provider(environ: Mapping[str, str] | None = None) -> DatabaseProvider:
    """Return the configured provider, or refuse.

    No default. Choosing one here would make an unconfigured deployment start
    successfully against an engine nobody selected, and the failure would appear
    later as missing data rather than as a configuration error.
    """

    env = os.environ if environ is None else environ
    name = (env.get(PROVIDER_VARIABLE) or "").strip().lower()
    if not name:
        raise ProviderConfigurationError(
            f"{PROVIDER_VARIABLE} is not set. Choose one of: "
            f"{', '.join(sorted(p.value for p in DatabaseProvider))}."
        )
    try:
        return DatabaseProvider(name)
    except ValueError:
        raise ProviderConfigurationError(
            f"unknown database provider {name!r}. Choose one of: "
            f"{', '.join(sorted(p.value for p in DatabaseProvider))}."
        ) from None


def resolve_url(provider: DatabaseProvider, environ: Mapping[str, str] | None = None) -> str:
    """Return the connection URL for ``provider``.

    Prefers the provider-specific variable so a machine can hold settings for
    both without either becoming ambiguous.
    """

    env = os.environ if environ is None else environ
    specific = (env.get(URL_VARIABLES[provider]) or "").strip()
    if specific:
        return specific
    fallback = (env.get(FALLBACK_URL_VARIABLE) or "").strip()
    if fallback:
        return fallback
    raise ProviderConfigurationError(
        f"no connection URL for provider {provider.value!r}. Set "
        f"{URL_VARIABLES[provider]}, or {FALLBACK_URL_VARIABLE} to use one URL "
        "for whichever provider is selected."
    )


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    """The resolved persistence configuration for one process.

    One process, one provider. Switching is a deployment change, not something
    that happens while running.
    """

    provider: DatabaseProvider
    url: str
    capabilities: DatabaseCapabilities

    def describe(self) -> dict[str, Any]:
        """Return diagnostics safe to log or return over an API.

        Carries no URL, host, or credential. It reports what the store can do,
        without ranking the providers against each other — a diagnostic that
        called one of them primary would be stating a preference the
        architecture does not hold.
        """

        return {
            "database_provider": self.provider.value,
            "vector_provider": (
                "cockroachdb_native" if self.capabilities.native_vector else "pgvector"
            ),
            "distributed_sql": self.capabilities.distributed_sql,
            "transaction_retry_required": self.capabilities.transaction_retry_required,
            "approximate_vector_index": self.capabilities.approximate_vector_index,
        }


def resolve(environ: Mapping[str, str] | None = None) -> DatabaseSettings:
    """Return the configuration this process should use.

    The one place provider identity is decided. Everywhere else asks this.
    """

    provider = resolve_provider(environ)
    return DatabaseSettings(
        provider=provider,
        url=resolve_url(provider, environ),
        capabilities=capabilities_for(provider),
    )


__all__ = [
    "CAPABILITIES",
    "FALLBACK_URL_VARIABLE",
    "PROVIDER_VARIABLE",
    "URL_VARIABLES",
    "DatabaseCapabilities",
    "DatabaseProvider",
    "DatabaseSettings",
    "ProviderConfigurationError",
    "capabilities_for",
    "resolve",
    "resolve_provider",
    "resolve_url",
]
