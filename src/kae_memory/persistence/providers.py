"""Selectable database providers.

KAE-Memory stores knowledge in a relational database with vector search over it.
Which database is a deployment decision, not an architectural one: CockroachDB
and PostgreSQL with pgvector are both first-class, and neither is a fallback for
the other.

Everything provider-specific lives here or below the repository boundary — the
column type a vector compiles to, how a vector index is built, whether a
transaction needs retrying. Nothing above that boundary asks which database it
is talking to, because the moment a service does, switching providers stops
being configuration and becomes a code change.

Selection is explicit. A missing or unknown provider raises rather than guessing
from a URL or falling back to whichever database happens to answer: silently
running against the wrong store is worse than not starting.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


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


VECTOR_INDEX_NAME = "knowledge_chunks_embedding_idx"
"""One vector index, on the embedding column. Kind is a metadata filter."""


class ProviderAdapter(Protocol):
    """The provider-specific behaviour the persistence layer needs.

    ``provider`` and ``capabilities`` are read-only properties rather than
    attributes so a frozen dataclass satisfies the protocol: a mutable
    attribute would be invariant, and every adapter here is immutable.
    """

    @property
    def provider(self) -> DatabaseProvider: ...

    @property
    def capabilities(self) -> DatabaseCapabilities: ...

    def vector_column_spec(self, dimensions: int) -> str:
        """Return the DDL type for a fixed-dimension vector column."""
        ...

    def prepare_statements(self) -> tuple[str, ...]:
        """Return DDL a database needs before the schema can be created."""
        ...

    def create_vector_index(self, table: str, column: str, name: str) -> tuple[str, ...]:
        """Return the DDL that builds the vector index."""
        ...

    def drop_vector_index(self, table: str, name: str) -> tuple[str, ...]:
        """Return the DDL that removes the vector index."""
        ...

    def cosine_distance(self, column: str, parameter: str) -> str:
        """Return an expression for cosine distance between column and parameter."""
        ...


@dataclass(frozen=True, slots=True)
class CockroachDBAdapter:
    """CockroachDB, using its native vector type and index.

    Serialization failures are ordinary here rather than exceptional: the engine
    runs serializable isolation by default, so a caller that does not retry
    SQLSTATE 40001 will surface contention to a user as an error.
    """

    provider: DatabaseProvider = DatabaseProvider.COCKROACHDB
    capabilities: DatabaseCapabilities = DatabaseCapabilities(
        native_vector=True,
        pgvector_extension=False,
        approximate_vector_index=True,
        transaction_retry_required=True,
        distributed_sql=True,
    )

    def vector_column_spec(self, dimensions: int) -> str:
        return f"VECTOR({dimensions})"

    def prepare_statements(self) -> tuple[str, ...]:
        return ()

    def create_vector_index(self, table: str, column: str, name: str) -> tuple[str, ...]:
        # CREATE VECTOR INDEX has no Alembic operation, so it is raw DDL.
        return (f"CREATE VECTOR INDEX {name} ON {table} ({column})",)

    def drop_vector_index(self, table: str, name: str) -> tuple[str, ...]:
        return (f"DROP INDEX IF EXISTS {name}",)

    def cosine_distance(self, column: str, parameter: str) -> str:
        return f"{column} <=> {parameter}"


@dataclass(frozen=True, slots=True)
class PostgreSQLAdapter:
    """PostgreSQL with pgvector.

    The extension must exist in the database before any vector column can be
    created, which is why ``prepare_statements`` is not empty here and is for
    CockroachDB.

    Retries are not required. PostgreSQL's default isolation does not raise
    serialization failures, and retrying transactions that cannot fail that way
    would import a distributed engine's assumptions into one that does not share
    them.
    """

    provider: DatabaseProvider = DatabaseProvider.POSTGRESQL
    capabilities: DatabaseCapabilities = DatabaseCapabilities(
        native_vector=False,
        pgvector_extension=True,
        approximate_vector_index=True,
        transaction_retry_required=False,
        distributed_sql=False,
    )

    def vector_column_spec(self, dimensions: int) -> str:
        return f"vector({dimensions})"

    def prepare_statements(self) -> tuple[str, ...]:
        return ("CREATE EXTENSION IF NOT EXISTS vector",)

    def create_vector_index(self, table: str, column: str, name: str) -> tuple[str, ...]:
        # HNSW with the cosine operator class, matching the distance the
        # repository queries with. An index built for a different operator is
        # not merely slower — the planner will not use it.
        return (
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"USING hnsw ({column} vector_cosine_ops)",
        )

    def drop_vector_index(self, table: str, name: str) -> tuple[str, ...]:
        return (f"DROP INDEX IF EXISTS {name}",)

    def cosine_distance(self, column: str, parameter: str) -> str:
        return f"{column} <=> {parameter}"


_ADAPTERS: dict[DatabaseProvider, ProviderAdapter] = {
    DatabaseProvider.COCKROACHDB: CockroachDBAdapter(),
    DatabaseProvider.POSTGRESQL: PostgreSQLAdapter(),
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


def adapter_for(provider: DatabaseProvider) -> ProviderAdapter:
    """Return the adapter implementing ``provider``."""

    return _ADAPTERS[provider]


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


def resolve_url(
    provider: DatabaseProvider, environ: Mapping[str, str] | None = None
) -> str:
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
class DatabaseConfiguration:
    """The resolved persistence configuration for one process.

    One process, one provider. Switching is a deployment change, not something
    that happens while running.
    """

    provider: DatabaseProvider
    url: str
    adapter: ProviderAdapter

    @property
    def capabilities(self) -> DatabaseCapabilities:
        return self.adapter.capabilities

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


def resolve(environ: Mapping[str, str] | None = None) -> DatabaseConfiguration:
    """Return the configuration this process should use.

    The one place provider identity is decided. Everywhere else asks this.
    """

    provider = resolve_provider(environ)
    return DatabaseConfiguration(
        provider=provider,
        url=resolve_url(provider, environ),
        adapter=adapter_for(provider),
    )


__all__ = [
    "VECTOR_INDEX_NAME",
    "CockroachDBAdapter",
    "DatabaseCapabilities",
    "DatabaseConfiguration",
    "DatabaseProvider",
    "PostgreSQLAdapter",
    "ProviderAdapter",
    "ProviderConfigurationError",
    "adapter_for",
    "resolve",
    "resolve_provider",
    "resolve_url",
]
