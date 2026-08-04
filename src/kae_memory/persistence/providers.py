"""Provider-specific persistence behaviour.

Which provider a deployment uses is decided in :mod:`kae_memory.config`; this
module is the other half — the DDL each one compiles, how its vector index is
built, how it discards a database. Everything here needs SQL, which is why it
lives below the repository boundary and why configuration does not.

Nothing above that boundary asks which database it is talking to. The moment a
service does, switching providers stops being configuration and becomes a code
change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from kae_memory.config import (
    CAPABILITIES,
    DatabaseCapabilities,
    DatabaseProvider,
    ProviderConfigurationError,
    capabilities_for,
    resolve_provider,
    resolve_url,
)
from kae_memory.config import DatabaseSettings as _Settings

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

    def drop_database(self, name: str) -> str:
        """Return DDL dropping a database along with anything connected to it.

        Used by test tooling, which creates and discards databases constantly.
        The engines spell "drop it regardless of what is attached" differently,
        and getting it wrong strands databases behind open sessions.
        """
        ...


@dataclass(frozen=True, slots=True)
class CockroachDBAdapter:
    """CockroachDB, using its native vector type and index.

    Serialization failures are ordinary here rather than exceptional: the engine
    runs serializable isolation by default, so a caller that does not retry
    SQLSTATE 40001 will surface contention to a user as an error.
    """

    provider: DatabaseProvider = DatabaseProvider.COCKROACHDB
    capabilities: DatabaseCapabilities = CAPABILITIES[DatabaseProvider.COCKROACHDB]

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

    def drop_database(self, name: str) -> str:
        return f"DROP DATABASE IF EXISTS {name} CASCADE"


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
    capabilities: DatabaseCapabilities = CAPABILITIES[DatabaseProvider.POSTGRESQL]

    def vector_column_spec(self, dimensions: int) -> str:
        return f"vector({dimensions})"

    def prepare_statements(self) -> tuple[str, ...]:
        return ("CREATE EXTENSION IF NOT EXISTS vector",)

    def create_vector_index(self, table: str, column: str, name: str) -> tuple[str, ...]:
        # HNSW with the cosine operator class, matching the distance the
        # repository queries with. An index built for a different operator is
        # not merely slower — the planner will not use it.
        return (
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING hnsw ({column} vector_cosine_ops)",
        )

    def drop_vector_index(self, table: str, name: str) -> tuple[str, ...]:
        return (f"DROP INDEX IF EXISTS {name}",)

    def cosine_distance(self, column: str, parameter: str) -> str:
        return f"{column} <=> {parameter}"

    def drop_database(self, name: str) -> str:
        # PostgreSQL rejects CASCADE here and refuses to drop a database with
        # live connections. FORCE terminates them, which is what a disposable
        # test database needs and what CASCADE achieves on CockroachDB.
        return f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"


_ADAPTERS: dict[DatabaseProvider, ProviderAdapter] = {
    DatabaseProvider.COCKROACHDB: CockroachDBAdapter(),
    DatabaseProvider.POSTGRESQL: PostgreSQLAdapter(),
}


def adapter_for(provider: DatabaseProvider) -> ProviderAdapter:
    """Return the adapter implementing ``provider``."""

    return _ADAPTERS[provider]


@dataclass(frozen=True, slots=True)
class DatabaseConfiguration:
    """Settings plus the adapter that implements them.

    :class:`kae_memory.config.DatabaseSettings` says which provider and where;
    this adds how, which is the part that needs SQL. Callers outside persistence
    want the former and should not import this.
    """

    provider: DatabaseProvider
    url: str
    adapter: ProviderAdapter

    @property
    def capabilities(self) -> DatabaseCapabilities:
        return self.adapter.capabilities

    def describe(self) -> dict[str, object]:
        """Return diagnostics safe to log or return over an API."""

        return _Settings(self.provider, self.url, self.capabilities).describe()


def resolve(environ: Mapping[str, str] | None = None) -> DatabaseConfiguration:
    """Return the persistence configuration this process should use.

    Selection itself happens in :mod:`kae_memory.config`; this pairs the result
    with the adapter that knows the provider's SQL.
    """

    provider = resolve_provider(environ)
    return DatabaseConfiguration(
        provider=provider,
        url=resolve_url(provider, environ),
        adapter=adapter_for(provider),
    )


__all__ = [
    "CAPABILITIES",
    "VECTOR_INDEX_NAME",
    "CockroachDBAdapter",
    "DatabaseCapabilities",
    "DatabaseConfiguration",
    "DatabaseProvider",
    "PostgreSQLAdapter",
    "ProviderAdapter",
    "ProviderConfigurationError",
    "adapter_for",
    "capabilities_for",
    "resolve",
    "resolve_provider",
    "resolve_url",
]
