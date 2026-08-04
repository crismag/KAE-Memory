"""The guard standing between a destructive test and a real database.

Needs no database, and runs on every invocation of the suite. That is
deliberate: this is the check that protects the databases the other tests
cannot be trusted around, so it must not itself depend on one being reachable.

Every refused URL below was reachable in practice — a cloud cluster from a
loaded ``.env``, the local development store, and the application database a
provider switch had just created.
"""

from __future__ import annotations

import pytest
from tests.support.database import (
    DatabaseUnavailableError,
    UnsafeTestTargetError,
    database_name,
    require_safe_test_target,
    resolve_settings,
    selected_provider,
    with_database,
)

CLOUD = (
    "cockroachdb+psycopg://root@mighty-seeker-28528.j77.aws-us-east-1"
    ".cockroachlabs.cloud:26257/kae_memory?sslmode=verify-full"
)
LOCAL_DEV = "cockroachdb+psycopg://root@localhost:26259/kae_dev?sslmode=disable"
APPLICATION = "postgresql+psycopg://kae:kae@localhost:5432/kae_memory"
DISPOSABLE = "postgresql+psycopg://kae:kae@localhost:5432/kae_memory_test"


class TestDestructiveTargetGuard:
    def test_the_application_database_is_refused(self) -> None:
        """The name a provider switch creates is not a test database."""

        with pytest.raises(UnsafeTestTargetError, match="kae_memory"):
            require_safe_test_target(APPLICATION)

    def test_the_development_store_is_refused(self) -> None:
        """`kae_dev` holds the real corpus, on localhost."""

        with pytest.raises(UnsafeTestTargetError):
            require_safe_test_target(LOCAL_DEV)

    def test_a_cloud_database_without_a_test_name_is_refused(self) -> None:
        with pytest.raises(UnsafeTestTargetError):
            require_safe_test_target(CLOUD)

    def test_being_local_is_not_sufficient(self) -> None:
        """A developer keeps work they care about on localhost too.

        The earlier guard checked the host. That would have accepted every
        database on this machine, including the one holding the corpus.
        """

        with pytest.raises(UnsafeTestTargetError):
            require_safe_test_target("postgresql+psycopg://kae:kae@localhost:5432/kae")

    def test_an_unnamed_target_is_refused(self) -> None:
        """Fails closed: unparseable is refused, not allowed."""

        with pytest.raises(UnsafeTestTargetError):
            require_safe_test_target("not a url at all")

    def test_a_designated_test_database_is_accepted(self) -> None:
        require_safe_test_target(DISPOSABLE)

    @pytest.mark.parametrize(
        "name", ["kae_memory_test", "test_kae", "kae_testing", "kae_test_abc123"]
    )
    def test_every_designation_marker_is_honoured(self, name: str) -> None:
        require_safe_test_target(with_database(DISPOSABLE, name))

    def test_the_refusal_says_how_to_fix_it(self) -> None:
        """A guard that only says no teaches nothing."""

        with pytest.raises(UnsafeTestTargetError) as raised:
            require_safe_test_target(APPLICATION)

        message = str(raised.value)
        assert "KAE_TEST_DATABASE_URL" in message
        assert "kae_memory_test" in message


class TestConfigurationIsolation:
    """Test configuration must never resolve to the application's."""

    def test_application_variables_are_not_a_fallback(self) -> None:
        """The failure this prevents has already happened once here."""

        with pytest.raises(DatabaseUnavailableError):
            resolve_settings(
                {
                    "KAE_DATABASE_URL": APPLICATION,
                    "KAE_POSTGRESQL_URL": APPLICATION,
                    "KAE_COCKROACHDB_URL": LOCAL_DEV,
                }
            )

    def test_the_shared_test_url_is_used(self) -> None:
        settings = resolve_settings({"KAE_TEST_DATABASE_URL": DISPOSABLE})

        assert settings.url == DISPOSABLE

    def test_a_provider_specific_test_url_is_used(self) -> None:
        settings = resolve_settings(
            {
                "KAE_TEST_DATABASE_PROVIDER": "cockroachdb",
                "KAE_TEST_COCKROACHDB_URL": "cockroachdb+psycopg://root@h:26258/kae_test",
            }
        )

        assert settings.provider.value == "cockroachdb"
        assert settings.url.endswith("kae_test")

    def test_postgresql_is_the_default_provider(self) -> None:
        """A default engine is safe; a default connection would not be."""

        assert selected_provider({}).value == "postgresql"

    def test_no_url_is_invented_for_the_default_provider(self) -> None:
        """Guessing credentials would connect somewhere nobody named."""

        with pytest.raises(DatabaseUnavailableError, match="KAE_TEST_DATABASE_URL"):
            resolve_settings({})

    def test_an_unknown_test_provider_is_refused(self) -> None:
        with pytest.raises(DatabaseUnavailableError, match="mysql"):
            selected_provider({"KAE_TEST_DATABASE_PROVIDER": "mysql"})

    def test_the_message_names_what_to_set(self) -> None:
        with pytest.raises(DatabaseUnavailableError) as raised:
            resolve_settings({"KAE_TEST_DATABASE_PROVIDER": "postgresql"})

        assert "KAE_TEST_POSTGRESQL_URL" in str(raised.value)


class TestUrlHandling:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            (DISPOSABLE, "kae_memory_test"),
            ("cockroachdb+psycopg://root@h:26258/kae_test?sslmode=disable", "kae_test"),
            ("postgresql+psycopg://u@h/db", "db"),
        ],
    )
    def test_the_database_name_is_read_without_the_query(self, url: str, expected: str) -> None:
        assert database_name(url) == expected

    def test_repointing_preserves_connection_options(self) -> None:
        """Dropping sslmode while switching database would change how it connects."""

        moved = with_database(
            "cockroachdb+psycopg://root@h:26258/one?sslmode=disable", "kae_test_two"
        )

        assert moved == "cockroachdb+psycopg://root@h:26258/kae_test_two?sslmode=disable"
