"""Governed backend configuration (N7).

A small, validated settings system: committed defaults in `defaults.toml`, the
contract for each one in `catalog.py`, and a resolver that reports where every
effective value came from.

Deliberately not a policy framework, an administration UI, or a database-backed
configuration store — the focus file rules out all three, and each would need an
authorisation model this repository does not have.

The first governed slice is pagination and response limits, chosen because its
contract is already covered by T4/T5 tests: a migration that changes behaviour
fails loudly rather than being taken on trust.
"""

from .catalog import BY_KEY, CATALOG, Reload, Scope, Setting, SettingError, Source
from .resolution import Resolved, Settings, settings, unknown_overrides

__all__ = [
    "BY_KEY",
    "CATALOG",
    "Reload",
    "Resolved",
    "Scope",
    "Setting",
    "SettingError",
    "Settings",
    "Source",
    "settings",
    "unknown_overrides",
]
