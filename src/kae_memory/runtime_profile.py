"""What this deployment is allowed to reach, in one word (`ADR-0006` §1, §4).

Provider selection is five independent environment variables read in three
modules — ``KAE_EMBEDDING``, ``KAE_OBSERVATION_CLASSIFIER``, ``KAE_EXTRACTION``,
``KAE_REVIEW``, ``KAE_GOAL_JUDGE``. Each answers *which adapter runs*. None of
them answers *what may this deployment reach*, and until something does, offline
is inferred from an absent credential rather than enforced.

``KAE_RUNTIME_PROFILE`` is that answer, and it **constrains rather than
chooses** (`D-172`). A profile that supplied providers — ``local`` meaning
Ollama everywhere — would decide which model embedded a corpus from a word about
the deployment, and provenance records the adapter that read each sentence. The
explicit variables stay the only thing that picks; the profile refuses what the
deployment may not reach.

The dimension is **reach**, not vendor, because ``KAE_OLLAMA_URL`` pointed at
another machine is a network call wearing the local provider's name.
"""

import os
from collections.abc import Mapping
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlsplit

VARIABLE = "KAE_RUNTIME_PROFILE"

OFFLINE = "offline"
LOCAL = "local"
HYBRID = "hybrid"
PRODUCTION = "production"


class Reach(StrEnum):
    """What building and calling a provider touches."""

    IN_PROCESS = "in_process"
    """A fixture computed here. No socket, no credential, and no meaning."""

    HOST = "host"
    """A model on this machine, over loopback."""

    NETWORK = "network"
    """The same local adapter, pointed at another machine."""

    HOSTED = "hosted"
    """A remote API belonging to somebody else, billed per call."""


_PERMITTED: Mapping[str, frozenset[Reach]] = {
    OFFLINE: frozenset({Reach.IN_PROCESS, Reach.HOST}),
    LOCAL: frozenset({Reach.IN_PROCESS, Reach.HOST, Reach.NETWORK}),
    HYBRID: frozenset(Reach),
    # `in_process` is absent on purpose. The deterministic adapters rank at
    # chance and report as though they worked, so a production deployment
    # embedding a corpus with hash vectors is the failure this module exists to
    # refuse — not a lesser configuration to allow quietly.
    PRODUCTION: frozenset({Reach.HOST, Reach.NETWORK, Reach.HOSTED}),
}

PROFILES = tuple(_PERMITTED)


class ProfileViolation(RuntimeError):
    """The provider can be built; this deployment may not reach it.

    Deliberately not a ``ProviderConfigurationError``. That one means the
    environment cannot produce the adapter — no region, an unknown name. This
    one means the adapter is perfectly configured and the deployment's declared
    posture forbids it, which is a different thing for an operator to read.
    """


def profile_name(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the declared profile, or ``None`` when nothing declares one.

    Unset is unconstrained. Defaulting to ``local`` would change what an
    existing deployment may reach without anybody deciding, and deployment
    posture is the owner's (`D-172`).
    """

    environ = os.environ if environ is None else environ
    value = environ.get(VARIABLE, "").strip().lower()
    if not value:
        return None
    if value not in _PERMITTED:
        raise ProfileViolation(f"unknown {VARIABLE}={value!r}. Valid: {', '.join(PROFILES)}")
    return value


def permits(profile: str | None, reach: Reach) -> bool:
    """Return whether ``profile`` allows a provider with this reach."""

    if profile is None:
        return True
    return reach in _PERMITTED[profile]


def reach_of_url(url: str) -> Reach:
    """Return whether ``url`` stays on this machine.

    A hostname that does not resolve to a literal loopback address is treated as
    the network. Guessing in the other direction would let ``offline`` pass a
    call that leaves the host, which is the one mistake this cannot make.
    """

    host = urlsplit(url).hostname or ""
    if host == "localhost":
        return Reach.HOST
    try:
        return Reach.HOST if ip_address(host).is_loopback else Reach.NETWORK
    except ValueError:
        return Reach.NETWORK


def require(
    reach: Reach,
    *,
    variable: str,
    value: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Refuse a provider this deployment's profile does not permit."""

    profile = profile_name(environ)
    if permits(profile, reach):
        return
    permitted = ", ".join(sorted(member.value for member in _PERMITTED[str(profile)]))
    raise ProfileViolation(
        f"{VARIABLE}={profile} does not permit {variable}={value!r}, which "
        f"reaches {reach.value}. This profile permits: {permitted}."
    )


__all__ = [
    "HYBRID",
    "LOCAL",
    "OFFLINE",
    "PRODUCTION",
    "PROFILES",
    "VARIABLE",
    "ProfileViolation",
    "Reach",
    "permits",
    "profile_name",
    "reach_of_url",
    "require",
]
