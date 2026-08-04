"""One schema, whichever provider builds it.

Runs offline, in milliseconds, against no database. That is the point: the
divergence this catches was previously found by a dataset failing to load after
a seven-hour suite and a data migration, and it had been latent for eight
revisions before anyone looked.

What it compares is what each engine *realises*, not what the migration emits.
Both providers compile ``Integer`` to the literal word ``INTEGER``; CockroachDB
stores 64 bits and PostgreSQL stores 32. Nothing in the generated SQL says so,
so a test that diffed DDL strings would have passed while the schemas differed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, Integer

from kae_memory.persistence import providers
from kae_memory.persistence.providers import DatabaseProvider
from kae_memory.persistence.tables import Base

PROVIDERS = tuple(DatabaseProvider)


def _realised_schema(provider: DatabaseProvider) -> dict[str, dict[str, str]]:
    """Return ``{table: {column: realised type}}`` for one provider."""

    adapter = providers.adapter_for(provider)
    return {
        table.name: {
            column.name: adapter.realised_type(column.type) for column in table.columns
        }
        for table in Base.metadata.sorted_tables
    }


class TestRealisedTypes:
    """The check that would have caught the defect that started this."""

    def test_every_column_stores_the_same_thing_on_both_providers(self) -> None:
        schemas = {provider: _realised_schema(provider) for provider in PROVIDERS}
        reference, *others = PROVIDERS

        divergent: list[str] = []
        for table, columns in schemas[reference].items():
            for column, realised in columns.items():
                for other in others:
                    theirs = schemas[other][table][column]
                    if theirs != realised:
                        divergent.append(
                            f"{table}.{column}: {reference.value}={realised} "
                            f"{other.value}={theirs}"
                        )

        assert not divergent, (
            "the same mapping realises different storage per provider:\n  "
            + "\n  ".join(divergent)
        )

    def test_integer_is_the_type_that_diverges(self) -> None:
        """Documents *why* the check above exists, not merely that it passes.

        If this ever stops holding — because CockroachDB narrows its INT, or a
        provider is added that agrees — the test above is measuring less than it
        appears to, and someone should know.
        """

        cockroach = providers.adapter_for(DatabaseProvider.COCKROACHDB)
        postgres = providers.adapter_for(DatabaseProvider.POSTGRESQL)

        assert cockroach.realised_type(Integer()) == "int64"
        assert postgres.realised_type(Integer()) == "int32"
        assert cockroach.realised_type(Integer()) != postgres.realised_type(Integer())

    def test_bigint_is_how_the_mapping_avoids_it(self) -> None:
        for provider in PROVIDERS:
            assert providers.adapter_for(provider).realised_type(BigInteger()) == "int64"

    def test_no_mapped_column_uses_a_bare_integer(self) -> None:
        """Because one that did would silently differ per provider.

        ``knowledge_versions.id`` was exactly this, and CockroachDB generates it
        with ``unique_rowid()`` — values far outside 32 bits, so the dataset
        physically could not load into the PostgreSQL schema.
        """

        offenders = [
            f"{table.name}.{column.name}"
            for table in Base.metadata.sorted_tables
            for column in table.columns
            if type(column.type) is Integer
        ]

        assert not offenders, (
            "Integer realises differently per provider — use BigInteger or "
            f"SmallInteger: {', '.join(offenders)}"
        )


class TestStructuralParity:
    """Shape, not just types. A schema is more than its columns."""

    @pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.value)
    def test_every_table_is_present(self, provider: DatabaseProvider) -> None:
        realised = _realised_schema(provider)

        assert set(realised) == {table.name for table in Base.metadata.sorted_tables}

    def test_column_sets_match(self) -> None:
        schemas = [_realised_schema(provider) for provider in PROVIDERS]
        reference, *others = schemas

        for table, columns in reference.items():
            for other in others:
                assert set(other[table]) == set(columns), f"{table} has different columns"

    def test_the_vector_column_has_one_dimension_everywhere(self) -> None:
        """A different width on one provider is an unloadable corpus."""

        realised = {
            provider: _realised_schema(provider)["knowledge_chunks"]["embedding"]
            for provider in PROVIDERS
        }

        assert len(set(realised.values())) == 1, realised
        assert set(realised.values()) == {"vector(1024)"}


class TestProviderDdl:
    """The DDL each provider emits, checked for what must differ."""

    def test_the_vector_column_is_spelled_per_provider(self) -> None:
        cockroach = providers.adapter_for(DatabaseProvider.COCKROACHDB)
        postgres = providers.adapter_for(DatabaseProvider.POSTGRESQL)

        assert cockroach.vector_column_spec(1024) == "VECTOR(1024)"
        assert postgres.vector_column_spec(1024) == "vector(1024)"

    def test_spelling_differences_do_not_count_as_schema_differences(self) -> None:
        """`VECTOR(1024)` and `vector(1024)` are the same column.

        Without normalisation this test suite would fail on a difference that
        does not exist, and the noise would teach people to ignore it.
        """

        realised = {
            providers.adapter_for(provider).realised_type(
                Base.metadata.tables["knowledge_chunks"].columns["embedding"].type
            )
            for provider in PROVIDERS
        }

        assert realised == {"vector(1024)"}

    @pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.value)
    def test_each_provider_can_build_and_drop_its_vector_index(
        self, provider: DatabaseProvider
    ) -> None:
        adapter = providers.adapter_for(provider)

        create = " ".join(
            adapter.create_vector_index(
                "knowledge_chunks", "embedding", providers.VECTOR_INDEX_NAME
            )
        )
        drop = " ".join(
            adapter.drop_vector_index("knowledge_chunks", providers.VECTOR_INDEX_NAME)
        )

        assert providers.VECTOR_INDEX_NAME in create
        assert providers.VECTOR_INDEX_NAME in drop
        assert "embedding" in create

    @pytest.mark.parametrize("provider", PROVIDERS, ids=lambda p: p.value)
    def test_every_provider_queries_the_distance_it_indexed(
        self, provider: DatabaseProvider
    ) -> None:
        """An index built for one operator is not used by another."""

        adapter = providers.adapter_for(provider)

        assert "<=>" in adapter.cosine_distance("embedding", ":vector")
