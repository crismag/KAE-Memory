"""Test-only database configuration.

Deliberately separate from ``kae_memory.persistence.providers``. That module
resolves where the *application* stores knowledge; this one resolves where tests
are allowed to destroy things, and the two must never be the same resolution
path. A test suite that can read the application's configuration is one
mistaken environment away from truncating a real database.

So nothing here falls back to ``KAE_DATABASE_URL``, ``KAE_POSTGRESQL_URL``, or
``KAE_COCKROACHDB_URL``. A missing test URL means tests skip, never that they
quietly use the application's.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from kae_memory.persistence.providers import DatabaseProvider

PROVIDER_VARIABLE = "KAE_TEST_DATABASE_PROVIDER"
URL_VARIABLE = "KAE_TEST_DATABASE_URL"
PROVIDER_URL_VARIABLES: dict[DatabaseProvider, str] = {
    DatabaseProvider.POSTGRESQL: "KAE_TEST_POSTGRESQL_URL",
    DatabaseProvider.COCKROACHDB: "KAE_TEST_COCKROACHDB_URL",
}

DEFAULT_TEST_PROVIDER = DatabaseProvider.POSTGRESQL
"""What a developer gets without saying anything.

A default provider is safe; a default *URL* is not. Choosing an engine decides
which dialect compiles, and is corrected by one variable. Choosing a connection
would mean guessing credentials and connecting somewhere nobody named.
"""

TEST_NAME_MARKERS = ("_test", "test_", "testing")
"""Substrings that designate a database as disposable.

Hostname is not enough. A developer's laptop holds their real work on
``localhost`` too, and the database this suite drops tables in has to say so in
its own name.
"""

FORBIDDEN_NAMES = frozenset(
    {"kae", "kae_memory", "kae_dev", "kae_prod", "kae_production", "postgres", "defaultdb"}
)
"""Names that are never a test target, whatever else they contain."""


class DatabaseUnavailableError(RuntimeError):
    """No test database is configured for the selected provider."""


class UnsafeTestTargetError(RuntimeError):
    """The configured target is not clearly a disposable test database."""


@dataclass(frozen=True, slots=True)
class DatabaseTestSettings:
    """Where this run is allowed to create, fill, and drop databases."""

    provider: DatabaseProvider
    url: str

    @property
    def marker(self) -> str:
        """The pytest marker naming this provider."""

        return self.provider.value


def selected_provider(environ: Mapping[str, str] | None = None) -> DatabaseProvider:
    """Return the provider this run exercises."""

    env = os.environ if environ is None else environ
    name = (env.get(PROVIDER_VARIABLE) or "").strip().lower()
    if not name:
        return DEFAULT_TEST_PROVIDER
    try:
        return DatabaseProvider(name)
    except ValueError:
        raise DatabaseUnavailableError(
            f"unknown {PROVIDER_VARIABLE}={name!r}. Choose one of: "
            f"{', '.join(sorted(p.value for p in DatabaseProvider))}."
        ) from None


def resolve_settings(environ: Mapping[str, str] | None = None) -> DatabaseTestSettings:
    """Return the test database settings, or explain what is missing.

    Resolution order is ``KAE_TEST_DATABASE_URL``, then the provider-specific
    test URL. There is no third step: the application's variables are not a
    fallback, by design.
    """

    env = os.environ if environ is None else environ
    provider = selected_provider(env)

    specific = (env.get(PROVIDER_URL_VARIABLES[provider]) or "").strip()
    shared = (env.get(URL_VARIABLE) or "").strip()
    url = shared or specific
    if not url:
        raise DatabaseUnavailableError(
            f"no test database configured for provider {provider.value!r}. Set "
            f"{URL_VARIABLE} or {PROVIDER_URL_VARIABLES[provider]}, for example "
            f"'{_example_url(provider)}'. The application's database variables "
            "are deliberately not used here."
        )
    return DatabaseTestSettings(provider=provider, url=url)


def _example_url(provider: DatabaseProvider) -> str:
    if provider is DatabaseProvider.POSTGRESQL:
        return "postgresql+psycopg://kae:kae@localhost:5432/kae_memory_test"
    return "cockroachdb+psycopg://root@localhost:26258/kae_memory_test?sslmode=disable"


def database_name(url: str) -> str:
    """Return the database a URL names, without its query string."""

    path = url.split("?", 1)[0]
    return path.rsplit("/", 1)[-1] if "/" in path else ""


def require_safe_test_target(url: str) -> None:
    """Refuse anything that is not clearly a disposable test database.

    Called before creating, truncating, or dropping. The check is on the
    database *name* rather than the host: a local developer keeps real work on
    ``localhost``, and "it is not production" is not the same claim as "losing
    this costs nothing".

    Fails closed — an unparseable or unnamed target is refused, not allowed.
    """

    name = database_name(url).strip().lower()
    if not name:
        raise UnsafeTestTargetError(
            f"refusing a destructive test operation: no database name in {url.split('@')[-1]!r}"
        )
    if name in FORBIDDEN_NAMES:
        raise UnsafeTestTargetError(
            f"Refusing destructive test operation against database {name!r}.\n"
            f"Set {URL_VARIABLE} to a database explicitly designated for testing, "
            "for example 'kae_memory_test'."
        )
    if not any(marker in name for marker in TEST_NAME_MARKERS):
        raise UnsafeTestTargetError(
            f"Refusing destructive test operation against database {name!r}.\n"
            f"Its name does not designate it as a test database — expected one of "
            f"{', '.join(TEST_NAME_MARKERS)} in the name.\n"
            f"Set {URL_VARIABLE} to a database explicitly designated for testing, "
            "for example 'kae_memory_test'."
        )


def with_database(url: str, name: str) -> str:
    """Return ``url`` pointed at a different database on the same server."""

    root, separator, query = url.partition("?")
    base = root.rsplit("/", 1)[0]
    return f"{base}/{name}" + (f"{separator}{query}" if separator else "")


__all__ = [
    "DEFAULT_TEST_PROVIDER",
    "FORBIDDEN_NAMES",
    "PROVIDER_URL_VARIABLES",
    "PROVIDER_VARIABLE",
    "TEST_NAME_MARKERS",
    "URL_VARIABLE",
    "DatabaseTestSettings",
    "DatabaseUnavailableError",
    "UnsafeTestTargetError",
    "database_name",
    "require_safe_test_target",
    "resolve_settings",
    "selected_provider",
    "with_database",
]
