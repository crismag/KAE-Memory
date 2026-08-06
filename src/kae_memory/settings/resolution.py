"""Resolving a governed setting, and saying where the answer came from (N7).

Precedence, highest first:

1. **a coded ceiling** — an absolute boundary no deployment may cross. Not a
   value it supplies, but a refusal it cannot argue with;
2. **an environment override** — what this installation chose;
3. **the committed default** — what ships.

Two layers the focus file reserves — an administrative override and a
project-level one — are deliberately absent. Both need an authorisation model
this repository does not have, and building the plumbing before the authority
would produce a system that can be overridden by whoever reaches it first.

**Every resolution reports its source.** "Why is the page size 40" is a question
asked at the worst possible moment, and an answer that requires reading three
files is not one. `explain()` returns the whole picture for a diagnostic; the
ordinary path returns just the value.

TOML rather than YAML, which the focus file's placement table names. `tomllib`
is in the standard library and is read-only, which is exactly the shape of a
committed defaults file: the application never writes it, and a parser that
*cannot* write it removes a whole category of mistake. YAML would have added a
dependency to gain nothing this file needs.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .catalog import CATALOG, Setting, SettingError, Source, coerce, require

DEFAULTS_FILE = Path(__file__).with_name("defaults.toml")


@dataclass(frozen=True, slots=True)
class Resolved:
    """One effective value, and everything needed to explain it."""

    key: str
    value: Any
    source: Source
    unit: str
    scope: str
    reload: str
    overridable: bool
    env_var: str | None
    rationale: str
    committed_default: Any
    """What would apply with no override. Carried so a diagnostic can show the
    difference rather than making a reader go and look it up."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source.value,
            "unit": self.unit,
            "scope": self.scope,
            "reload": self.reload,
            "overridable": self.overridable,
            "env_var": self.env_var,
            "committed_default": self.committed_default,
            "rationale": self.rationale,
        }


class Settings:
    """The effective configuration for one process.

    Constructed with an environment rather than reading `os.environ` itself, so
    a test can exercise a deployment's configuration without becoming one. The
    same reason the test suite resolves its database separately from the
    application: a process that reads ambient state is a process whose
    behaviour cannot be reproduced.
    """

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        defaults: Mapping[str, Any] | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._defaults = dict(load_defaults() if defaults is None else defaults)
        self._resolved: dict[str, Resolved] = {}
        # Resolved eagerly. A misconfigured deployment must fail at startup,
        # not on the first call that happens to read the setting — which is
        # reliably the one furthest from anyone who could fix it.
        for setting in CATALOG:
            self._resolved[setting.key] = self._resolve(setting)

    def __getitem__(self, key: str) -> Any:
        return self.value(key)

    def value(self, key: str) -> Any:
        """Return the effective value for ``key``."""

        return self.explain(key).value

    def explain(self, key: str) -> Resolved:
        """Return the effective value and where it came from."""

        resolved = self._resolved.get(key)
        if resolved is None:
            require(key)  # raises with the known keys
            raise SettingError(f"{key} was never resolved")  # pragma: no cover
        return resolved

    def explain_all(self) -> tuple[Resolved, ...]:
        """Every governed setting, for a diagnostic that shows the whole picture."""

        return tuple(self._resolved[setting.key] for setting in CATALOG)

    def _resolve(self, setting: Setting) -> Resolved:
        committed = self._committed(setting)
        value, source = committed, Source.COMMITTED_DEFAULT

        if setting.env_var:
            raw = self._environ.get(setting.env_var, "")
            # An exported-but-empty variable is not an override. Treating it as
            # one would let a shell that sets everything blank silently
            # reconfigure the process.
            if str(raw).strip():
                value = coerce(setting, raw, Source.ENVIRONMENT)
                source = Source.ENVIRONMENT

        return Resolved(
            key=setting.key,
            value=value,
            source=source,
            unit=setting.unit,
            scope=setting.scope.value,
            reload=setting.reload.value,
            overridable=setting.overridable,
            env_var=setting.env_var,
            rationale=setting.rationale,
            committed_default=committed,
        )

    def _committed(self, setting: Setting) -> Any:
        section, _, name = setting.key.partition(".")
        try:
            raw = self._defaults[section][name]
        except (KeyError, TypeError):
            raise SettingError(
                f"{setting.key} is declared in the catalog and absent from "
                f"{DEFAULTS_FILE.name}. Every governed setting needs a committed "
                f"default; a catalog entry with no value is a contract for "
                f"something that does not exist."
            ) from None
        return coerce(setting, raw, Source.COMMITTED_DEFAULT)


@lru_cache(maxsize=1)
def load_defaults() -> Mapping[str, Any]:
    """Read the committed defaults once per process.

    Cached because it is read at startup for every setting and the file cannot
    change under a running process — `reload: restart` is the contract, not an
    aspiration.
    """

    with DEFAULTS_FILE.open("rb") as handle:
        return tomllib.load(handle)


@lru_cache(maxsize=1)
def settings() -> Settings:
    """The process-wide settings, resolved from the real environment.

    One instance, so that two subsystems reading the same key cannot disagree —
    which is the failure this target found: `MAX_PAGE_SIZE` and `MAX_PAGE` were
    the same number written twice, in two adapters, with the same docstring.
    """

    return Settings()


def unknown_overrides(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Return `KAE_*` variables that look like settings and govern nothing.

    A variable nothing reads is worse than no variable: someone sets it,
    watches nothing change, and concludes the setting does not work. This
    cannot distinguish a typo from a variable belonging to another subsystem,
    so it reports rather than refuses.
    """

    environ = os.environ if environ is None else environ
    governed = {setting.env_var for setting in CATALOG if setting.env_var}
    known = governed | _UNGOVERNED
    return tuple(sorted(name for name in environ if name.startswith("KAE_") and name not in known))


_UNGOVERNED: frozenset[str] = frozenset(
    {
        # Deployment facts and secrets, correctly outside the committed
        # defaults: connection strings, provider selection, credentials, and
        # the bind address. None of these has a safe product default.
        "KAE_DATABASE_URL",
        "KAE_DATABASE_PROVIDER",
        "KAE_POSTGRESQL_URL",
        "KAE_COCKROACHDB_URL",
        "KAE_API_TOKENS",
        "KAE_API_HOST",
        "KAE_API_PORT",
        "KAE_CORS_ORIGINS",
        "KAE_ENVIRONMENT",
        "KAE_LOG_LEVEL",
        "KAE_EMBEDDING",
        "KAE_EXTRACTION",
        "KAE_REVIEW",
        "KAE_OBSERVATION_CLASSIFIER",
        "KAE_WORKER_ID",
        "KAE_LEASE_DURATION_SECONDS",
        "KAE_WORKER_POLL_SECONDS",
        "KAE_MCP_PROFILE",
        "KAE_MCP_DETAIL",
        "KAE_MCP_PROSE",
        "KAE_MCP_MAX_TOKENS",
        "KAE_MCP_MAX_ENTITIES",
        "KAE_INGESTION_MAX_CHUNKS",
        "KAE_INGESTION_MAX_ITEMS",
        # The test suite resolves its own target, deliberately never falling
        # back to the application's (ADR-0011).
        "KAE_TEST_DATABASE_URL",
        "KAE_TEST_DATABASE_PROVIDER",
        "KAE_TEST_POSTGRESQL_URL",
        "KAE_TEST_COCKROACHDB_URL",
    }
)
"""`KAE_*` variables that exist and are deliberately not governed settings.

Listed so the audit above can tell "not a setting" from "a typo". Each is
either a secret, a deployment fact with no safe default, or a subsystem knob
that has not been migrated — and this list is the honest record of the second
category rather than a claim that the first slice covered everything.
"""
