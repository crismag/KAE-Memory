"""Where a deliverable may be published, and who says so (N27, N28).

Two records, kept apart on purpose.

A **target** is a place a project has decided to publish to: provider-neutral
identity, safe provider-specific configuration, an optional default per purpose.
It is a product decision, readable by an agent.

A **connection** is permission to reach a provider: authorisation state, whose
credentials, when they were last checked. It is a runtime fact, and its
credentials never leave the runtime layer under any response shape.

Separating them is what lets a target be visible and unusable. "Publish to
`crismag/KAE-Studio`" is a decision that survives a token expiring; the token
expiring is not a reason to forget the decision, and re-asking someone to choose
a destination they already chose is how a system teaches people to ignore it.

**A request may not carry a coordinate.** Not a bucket, not a repository, not an
absolute path. A caller that could name a destination inline would make every
authorisation check advisory — the check would run against a registered target
while the bytes went somewhere else. Requests name a `target_id` or nothing, and
nothing resolves to the project default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import DomainInvariantError
from .identifiers import Identifier, ProjectId


class TargetId(Identifier):
    """Identifies one publication target."""


class ConnectionId(Identifier):
    """Identifies one provider connection."""


class Provider(StrEnum):
    """A kind of destination KAE can write to.

    Three, and each arrives with the provider that implements it (N30–N32).
    Naming a fourth here before its implementation exists would produce a
    target a project could choose and nothing could honour.
    """

    LOCAL = "local"
    S3 = "s3"
    GITHUB = "github"


class TargetPurpose(StrEnum):
    """What class of output a target receives.

    At most one default per purpose, so "the deliverable destination" and "the
    place snapshots go" can differ without either becoming ambiguous.
    """

    DELIVERABLE = "deliverable"
    SNAPSHOT = "snapshot"
    EXPORT = "export"


class AuthorizationState(StrEnum):
    """Whether KAE may currently reach a provider.

    `never_granted` and `revoked` are distinct because the remedies differ: the
    first needs a decision, the second needs a person to find out why. `expired`
    is separated from both because it is routine and usually self-inflicted, and
    a routine event reported as a revocation causes alarm nobody needed.
    """

    NEVER_GRANTED = "never_granted"
    GRANTED = "granted"
    EXPIRED = "expired"
    REVOKED = "revoked"
    UNVERIFIED = "unverified"
    """Credentials exist and have not been exercised. Honest rather than
    optimistic: a connection nobody has tested is not a working connection, and
    reporting it as granted moves the failure to publication time."""


USABLE: frozenset[AuthorizationState] = frozenset({AuthorizationState.GRANTED})
"""The only state a publication may proceed from.

`unverified` is deliberately absent. Attempting anyway would be defensible, and
it would also mean the first thing a person learns about a broken connection is
a failed publication rather than an unavailable capability.
"""


class TargetError(DomainInvariantError):
    """A target, connection, or request is not one this model permits."""


CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "secret",
        "password",
        "access_key",
        "secret_key",
        "private_key",
        "credential",
        "authorization",
        "session_token",
    }
)
"""Configuration keys a target may never carry.

A bucket name is configuration; the key that writes to it is not. Refused at
construction rather than filtered on the way out, because a credential that
reached a target record has already been written somewhere readable — and a
response shape that redacts it does not unwrite it.
"""


def ensure_no_credentials(configuration: dict[str, str]) -> None:
    """Refuse target configuration that carries a secret."""

    offending = sorted(
        key for key in configuration if any(fragment in key.lower() for fragment in CREDENTIAL_KEYS)
    )
    if offending:
        raise TargetError(
            f"target configuration may not carry credentials: {offending}. "
            f"Credentials belong to a connection in the runtime layer, which "
            f"never returns them (N28)."
        )


@dataclass(frozen=True, slots=True)
class PublicationTarget:
    """One registered destination, described without the means to reach it."""

    id: TargetId
    project_id: ProjectId
    provider: Provider
    name: str
    purpose: TargetPurpose = TargetPurpose.DELIVERABLE
    is_default: bool = False
    """Whether this receives a request that names no target.

    At most one per purpose, enforced by the service that writes it — a second
    default is not a conflict a domain object can see on its own.
    """

    configuration: dict[str, str] | None = None
    """Provider-specific and **credential-free**: a bucket, a repository
    coordinate, a path prefix, a branch."""

    connection_id: str | None = None
    """The authorisation this target publishes through, if any.

    `None` for a local target, which needs no permission KAE does not already
    have. Optional rather than required, so a project can register where it
    intends to publish before anyone has granted access — a decision recorded
    early is a decision that does not have to be made under pressure.
    """

    enabled: bool = True
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise TargetError("a publication target needs a name a person can recognise")
        ensure_no_credentials(self.configuration or {})
        if self.provider is not Provider.LOCAL and not self.connection_id:
            raise TargetError(
                f"a {self.provider.value} target needs a connection: reaching it "
                f"requires authorisation, and a target without one would be "
                f"selectable and unusable with no way to say why"
            )

    def available(self, authorization: AuthorizationState) -> bool:
        """Whether a publication may proceed to this target right now."""

        if not self.enabled:
            return False
        if self.provider is Provider.LOCAL:
            return True
        return authorization in USABLE

    def unavailable_reason(self, authorization: AuthorizationState) -> str | None:
        """Why this cannot be published to, or `None`.

        Each state gets its own sentence. "Unavailable" with no reason leaves a
        person to guess between "I never set this up", "it stopped working",
        and "somebody turned it off", which have three different remedies.
        """

        if self.available(authorization):
            return None
        if not self.enabled:
            return f"the target {self.name!r} is disabled"
        return {
            AuthorizationState.NEVER_GRANTED: (
                f"nobody has authorised KAE to reach {self.provider.value} for "
                f"{self.name!r}. This is a decision, not a failure."
            ),
            AuthorizationState.EXPIRED: (
                f"the {self.provider.value} authorisation for {self.name!r} has "
                f"expired and needs renewing."
            ),
            AuthorizationState.REVOKED: (
                f"the {self.provider.value} authorisation for {self.name!r} was "
                f"revoked. Find out why before renewing it."
            ),
            AuthorizationState.UNVERIFIED: (
                f"the {self.provider.value} authorisation for {self.name!r} has "
                f"never been exercised, so it is not yet known to work."
            ),
        }.get(authorization, f"{self.name!r} is unavailable")


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    """Permission to reach one provider, without the means of doing so (N28).

    **This record never carries a credential**, and that is not an oversight
    about where they go. A credential lives wherever the runtime keeps
    secrets — an environment variable, an instance role, a secret manager — and
    this holds only a reference to it plus the authorisation state.

    A record that held one would be returned by some response shape eventually.
    Not because anyone decided to, but because a field that exists gets
    serialised, and the response that leaks it will be the one written in a
    hurry by someone who did not know.
    """

    id: ConnectionId
    project_id: ProjectId
    provider: Provider
    state: AuthorizationState = AuthorizationState.NEVER_GRANTED
    credential_reference: str | None = None
    """*Where* the credential is, never the credential. An environment variable
    name, a secret-manager path, an instance-role marker."""

    authorized_by: str | None = None
    last_verified_at: datetime | None = None
    detail: str = ""
    """Anything a person needs to act on: which account, which role, what
    failed. Never a value that grants access."""

    def __post_init__(self) -> None:
        if self.credential_reference and _looks_like_a_secret(self.credential_reference):
            raise TargetError(
                "credential_reference holds what looks like a credential rather "
                "than a reference to one. This record is returned to callers; a "
                "secret in it is a secret disclosed."
            )
        if self.state in USABLE and not (self.authorized_by or "").strip():
            raise TargetError(
                f"a {self.state.value} connection names nobody who granted it. "
                f"Authorisation is an act a person performs, and an "
                f"unattributed grant records that the system permitted itself."
            )

    @property
    def usable(self) -> bool:
        return self.state in USABLE


def _looks_like_a_secret(reference: str) -> bool:
    """Whether a reference looks like the thing it should be pointing at.

    Heuristic, and deliberately so. It cannot catch every secret and does not
    try; it catches the shapes people paste by accident — a GitHub token, an
    AWS key id, a long opaque blob — which is where this mistake actually
    happens.
    """

    value = reference.strip()
    prefixes = ("ghp_", "github_pat_", "gho_", "AKIA", "ASIA", "xoxb-", "sk-")
    if value.startswith(prefixes):
        return True
    # A reference names a location and locations are short. Forty opaque
    # characters with no separator is not a path or a variable name.
    return len(value) >= 40 and not any(char in value for char in "/.: -")


def ensure_no_inline_destination(request: dict[str, object]) -> None:
    """Refuse a publication request that names where to write.

    The rule that makes authorisation mean anything. A request able to carry a
    bucket, a repository coordinate, or an absolute path would let the check run
    against a registered target while the bytes went somewhere else — and every
    audit afterwards would describe the wrong destination.
    """

    inline = sorted(
        key
        for key in request
        if key
        in {
            "bucket",
            "repository",
            "repo",
            "path",
            "absolute_path",
            "destination",
            "endpoint",
            "url",
            "prefix",
            "branch",
        }
    )
    if inline:
        raise TargetError(
            f"a publication request may not name a destination inline: {inline}. "
            f"Register a target and name it by target_id, or omit it and use the "
            f"project default. A request that could name its own destination "
            f"would make every authorisation check advisory."
        )
