"""Provider selection, capabilities, and the DDL each provider compiles to.

No database is required to run these. That is the point of the abstraction:
which engine a deployment uses is resolved from configuration, so the resolution
itself can be checked without either engine being present.
"""

from __future__ import annotations

import pytest

from kae_memory.persistence import providers
from kae_memory.persistence.providers import (
    DatabaseProvider,
    ProviderConfigurationError,
)
from kae_memory.persistence.tables import Vector
from kae_memory.persistence.transactions import (
    CockroachDBRetryingTransactionRunner,
    PostgreSQLTransactionRunner,
    runner_for,
)

COCKROACH_URL = "cockroachdb+psycopg://root@localhost:26257/kae?sslmode=disable"
POSTGRES_URL = "postgresql+psycopg://kae:kae@localhost:5432/kae_memory"


class TestSelectionIsExplicit:
    def test_a_missing_provider_is_refused(self) -> None:
        """Choosing one here would start a deployment against an engine nobody
        selected, and the failure would surface later as missing data."""

        with pytest.raises(ProviderConfigurationError, match="KAE_DATABASE_PROVIDER"):
            providers.resolve_provider({})

    def test_an_unknown_provider_is_refused(self) -> None:
        with pytest.raises(ProviderConfigurationError, match="unknown database provider"):
            providers.resolve_provider({"KAE_DATABASE_PROVIDER": "mysql"})

    def test_the_error_names_the_supported_providers(self) -> None:
        with pytest.raises(ProviderConfigurationError) as raised:
            providers.resolve_provider({})

        assert "cockroachdb" in str(raised.value)
        assert "postgresql" in str(raised.value)

    def test_provider_names_are_case_insensitive(self) -> None:
        resolved = providers.resolve_provider({"KAE_DATABASE_PROVIDER": "PostgreSQL"})

        assert resolved is DatabaseProvider.POSTGRESQL

    def test_a_url_alone_does_not_select_a_provider(self) -> None:
        """Reading identity out of a connection string is how a deployment ends
        up pointed at the right host with the wrong assumptions."""

        with pytest.raises(ProviderConfigurationError):
            providers.resolve({"KAE_DATABASE_URL": POSTGRES_URL})


class TestUrlResolution:
    def test_the_provider_specific_url_is_preferred(self) -> None:
        """A machine may hold settings for both without either being ambiguous."""

        config = providers.resolve(
            {
                "KAE_DATABASE_PROVIDER": "postgresql",
                "KAE_POSTGRESQL_URL": POSTGRES_URL,
                "KAE_COCKROACHDB_URL": COCKROACH_URL,
            }
        )

        assert config.url == POSTGRES_URL

    def test_the_shared_url_is_honoured_once_a_provider_is_named(self) -> None:
        """An existing deployment adds one variable rather than rewriting."""

        config = providers.resolve(
            {"KAE_DATABASE_PROVIDER": "cockroachdb", "KAE_DATABASE_URL": COCKROACH_URL}
        )

        assert config.url == COCKROACH_URL

    def test_a_provider_with_no_url_is_refused(self) -> None:
        with pytest.raises(ProviderConfigurationError, match="KAE_POSTGRESQL_URL"):
            providers.resolve({"KAE_DATABASE_PROVIDER": "postgresql"})

    def test_selecting_an_unconfigured_provider_does_not_fall_back(self) -> None:
        """Silently using whichever database answers is worse than not starting."""

        with pytest.raises(ProviderConfigurationError):
            providers.resolve(
                {"KAE_DATABASE_PROVIDER": "postgresql", "KAE_COCKROACHDB_URL": COCKROACH_URL}
            )


class TestCapabilities:
    def test_cockroachdb_reports_native_vectors_and_required_retries(self) -> None:
        capabilities = providers.adapter_for(DatabaseProvider.COCKROACHDB).capabilities

        assert capabilities.native_vector
        assert not capabilities.pgvector_extension
        assert capabilities.transaction_retry_required
        assert capabilities.distributed_sql

    def test_postgresql_reports_pgvector_and_no_required_retries(self) -> None:
        capabilities = providers.adapter_for(DatabaseProvider.POSTGRESQL).capabilities

        assert not capabilities.native_vector
        assert capabilities.pgvector_extension
        assert not capabilities.transaction_retry_required
        assert not capabilities.distributed_sql

    def test_both_providers_support_vector_search(self) -> None:
        """Neither is a degraded mode of the other."""

        for provider in DatabaseProvider:
            capabilities = providers.adapter_for(provider).capabilities
            assert capabilities.native_vector or capabilities.pgvector_extension
            assert capabilities.approximate_vector_index


class TestVectorDdl:
    def test_each_provider_compiles_its_own_column_type(self) -> None:
        cockroach = providers.adapter_for(DatabaseProvider.COCKROACHDB)
        postgres = providers.adapter_for(DatabaseProvider.POSTGRESQL)

        assert cockroach.vector_column_spec(1024) == "VECTOR(1024)"
        assert postgres.vector_column_spec(1024) == "vector(1024)"

    def test_the_mapped_column_follows_the_configured_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One declaration, not two schemas kept in step by hand."""

        monkeypatch.setenv("KAE_DATABASE_PROVIDER", "postgresql")
        monkeypatch.setenv("KAE_POSTGRESQL_URL", POSTGRES_URL)

        assert Vector(1024).get_col_spec() == "vector(1024)"

    def test_only_postgresql_needs_preparing(self) -> None:
        """pgvector must exist before any vector column can be created."""

        postgres = providers.adapter_for(DatabaseProvider.POSTGRESQL)
        cockroach = providers.adapter_for(DatabaseProvider.COCKROACHDB)

        assert any("CREATE EXTENSION" in sql for sql in postgres.prepare_statements())
        assert cockroach.prepare_statements() == ()

    def test_the_postgres_index_matches_the_distance_it_is_queried_with(self) -> None:
        """An index built for another operator class is not used at all."""

        postgres = providers.adapter_for(DatabaseProvider.POSTGRESQL)

        ddl = " ".join(
            postgres.create_vector_index("knowledge_chunks", "embedding", "idx")
        )
        assert "vector_cosine_ops" in ddl
        assert "<=>" in postgres.cosine_distance("embedding", ":vector")

    def test_cockroachdb_uses_its_native_index_statement(self) -> None:
        cockroach = providers.adapter_for(DatabaseProvider.COCKROACHDB)

        ddl = " ".join(cockroach.create_vector_index("knowledge_chunks", "embedding", "idx"))
        assert ddl.startswith("CREATE VECTOR INDEX")


class TestTransactionStrategy:
    def test_a_retrying_provider_gets_the_retrying_runner(self) -> None:
        runner = runner_for(None, retry_required=True)  # type: ignore[arg-type]

        assert isinstance(runner, CockroachDBRetryingTransactionRunner)

    def test_a_non_retrying_provider_gets_a_single_attempt_runner(self) -> None:
        """Retrying where 40001 cannot occur implies a guarantee never made."""

        runner = runner_for(None, retry_required=False)  # type: ignore[arg-type]

        assert isinstance(runner, PostgreSQLTransactionRunner)

    def test_the_strategy_follows_capability_not_provider_name(self) -> None:
        """A future engine sharing PostgreSQL's semantics gets the right
        strategy without being named here."""

        for provider in DatabaseProvider:
            capabilities = providers.adapter_for(provider).capabilities
            runner = runner_for(None, capabilities.transaction_retry_required)  # type: ignore[arg-type]
            retrying = isinstance(runner, CockroachDBRetryingTransactionRunner)
            assert retrying is capabilities.transaction_retry_required


class TestDiagnostics:
    def test_diagnostics_carry_no_credentials(self) -> None:
        config = providers.resolve(
            {
                "KAE_DATABASE_PROVIDER": "postgresql",
                "KAE_POSTGRESQL_URL": "postgresql+psycopg://kae:hunter2@host:5432/kae",
            }
        )

        described = config.describe()

        assert "hunter2" not in str(described)
        assert "host" not in str(described)
        assert config.url not in str(described)

    def test_diagnostics_name_the_vector_implementation(self) -> None:
        postgres = providers.resolve(
            {"KAE_DATABASE_PROVIDER": "postgresql", "KAE_POSTGRESQL_URL": POSTGRES_URL}
        )
        cockroach = providers.resolve(
            {"KAE_DATABASE_PROVIDER": "cockroachdb", "KAE_COCKROACHDB_URL": COCKROACH_URL}
        )

        assert postgres.describe()["vector_provider"] == "pgvector"
        assert cockroach.describe()["vector_provider"] == "cockroachdb_native"

    def test_diagnostics_do_not_rank_the_providers(self) -> None:
        """A field calling one primary would state a preference the
        architecture does not hold."""

        for provider, url in (("postgresql", POSTGRES_URL), ("cockroachdb", COCKROACH_URL)):
            described = providers.resolve(
                {"KAE_DATABASE_PROVIDER": provider, "KAE_DATABASE_URL": url}
            ).describe()
            rendered = str(described).lower()
            for word in ("primary", "fallback", "default", "secondary", "preferred"):
                assert word not in rendered
