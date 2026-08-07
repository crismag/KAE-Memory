"""The HTTP trust boundary (N5, ADR-0024).

ADR-0014 recorded "no authentication" as an accepted MVP risk, on the reasoning
that the API was safe behind a network boundary. That reasoning held while the
API was four services on loopback. It does not hold now: N3 put search,
ingestion, clarification, assembly, and classification behind the same
unauthenticated surface, and ADR-0023 made HTTP the transport a browser
application speaks.

Three rules shape everything here.

**Fail closed on exposure, not on suspicion.** A process bound to loopback with
no token configured is a developer's laptop and starts. The same process bound
to any other interface refuses to start. The failure is at startup, loudly,
rather than at the first unauthenticated request nobody was watching for.

**Authentication and authorisation are separate.** A token proves who is
calling. Whether that caller may read a given project is a second question, and
conflating them is how a convenience becomes a security control — the same
mistake `PROJECT_FOCUS.md` §5 warns about for focus.

**A rejection says as little as possible.** An unauthenticated caller learns
that they are unauthenticated, and nothing about whether a project exists.
"""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from .errors import error_response

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_true(value: str) -> bool:
    """Deliberately narrow. An opt-out from authentication should take a value
    someone typed on purpose, not any non-empty string a stray export left."""

    return value.strip().lower() in {"1", "true", "yes", "on"}
"""Interfaces a developer's process may bind to without a token."""

PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})
"""What answers without a token.

`/health` is here because FR-017 requires it to work without authentication —
a health check that needs a credential fails for the two different reasons a
monitor most needs to tell apart. It reports status and revision, never data.
"""

REQUEST_ID_HEADER = "X-Request-ID"
MAX_BODY_BYTES = 2 * 1024 * 1024
"""Two megabytes. Large enough for a substantial document, small enough that a
mistaken paste is refused rather than chunked into a thousand runs."""


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is calling, and what they may reach.

    ``projects`` empty means every project. A token scoped to none would be a
    token that can authenticate and do nothing, which is a configuration
    mistake rather than a useful state, so absence means unrestricted and the
    restriction is opt-in.
    """

    name: str
    projects: frozenset[str] = field(default_factory=frozenset)

    def may_read(self, project_id: str) -> bool:
        return not self.projects or project_id in self.projects


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    """The resolved authentication configuration for one process."""

    tokens: dict[str, Principal] = field(default_factory=dict)
    required: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.tokens)


class InsecureDeploymentError(RuntimeError):
    """A process would listen off-loopback without a way to authenticate."""


def resolve_policy(environ: dict[str, str] | None = None, host: str = "127.0.0.1") -> AuthPolicy:
    """Return the authentication policy, refusing an exposed unauthenticated one.

    ``KAE_API_TOKENS`` is a comma-separated list of ``name:token`` pairs, each
    optionally scoped as ``name:token:project_id[,project_id]``. Tokens come
    from the environment and never from a committed file.

    Raising here rather than warning is the whole point. A warning about an
    unauthenticated public API is a line in a log that a deployment scrolls
    past; a refusal to start is a deployment that does not happen.
    """

    source = os.environ if environ is None else environ
    raw = source.get("KAE_API_TOKENS", "").strip()
    tokens: dict[str, Principal] = {}

    for entry in (part.strip() for part in raw.split(";") if part.strip()):
        name, _, remainder = entry.partition(":")
        token, _, scopes = remainder.partition(":")
        if not name.strip() or not token.strip():
            raise InsecureDeploymentError(
                "KAE_API_TOKENS entries must be `name:token` or `name:token:project,project`"
            )
        tokens[token.strip()] = Principal(
            name=name.strip(),
            projects=frozenset(p.strip() for p in scopes.split(",") if p.strip()),
        )

    # The interface the process binds to is not the interface a user reaches.
    #
    # This guard was written for a service listening on a public address, and
    # it works there. It does not fire for the shape ADR-0024 actually
    # recommends: nginx terminating TLS and the API bound to loopback. In that
    # deployment `exposed` is false however public the proxy is, so a missing
    # `KAE_API_TOKENS` produced an API that started cleanly, reported healthy,
    # and accepted every request from the internet.
    #
    # So loopback no longer implies development. A deployment that genuinely
    # wants no authentication says so, and says it somewhere a reviewer reading
    # the environment can see.
    exposed = host not in LOOPBACK
    unauthenticated = _is_true(source.get("KAE_ALLOW_UNAUTHENTICATED", ""))

    if not tokens and not unauthenticated:
        raise InsecureDeploymentError(
            f"refusing to start on {host!r} without authentication: set KAE_API_TOKENS.\n"
            f"Binding to loopback is not a reason to skip it — a reverse proxy in front of "
            f"a loopback listener is a public API, and this process cannot see the "
            f"difference.\n"
            f"For local development with no authentication, set "
            f"KAE_ALLOW_UNAUTHENTICATED=1 deliberately."
        )

    if exposed and unauthenticated:
        # The opt-out is for a developer's own machine. Off-loopback it would be
        # an unauthenticated public API with a note attached.
        raise InsecureDeploymentError(
            f"refusing to listen on {host!r} with KAE_ALLOW_UNAUTHENTICATED set: "
            f"the opt-out exists for loopback development, not for an exposed interface."
        )

    return AuthPolicy(tokens=tokens, required=bool(tokens))


class TrustBoundaryMiddleware(BaseHTTPMiddleware):
    """Authenticate, bound the request, and stamp it with a correlation id.

    One middleware rather than three, because the order between them matters
    and separating them would let a later edit reorder it. A body is rejected
    before it is read, and a request is identified before it can fail — an
    error a caller cannot correlate to a log line is an error nobody can
    diagnose.
    """

    def __init__(self, app: object, policy: AuthPolicy, max_body: int = MAX_BODY_BYTES) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._policy = policy
        self._max_body = max_body

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request.state.request_id = request_id

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._max_body:
            return _refuse(
                413,
                "request_too_large",
                f"the request body exceeds {self._max_body} bytes",
                request_id,
            )

        if self._policy.enabled and request.url.path not in PUBLIC_PATHS:
            principal = _authenticate(request, self._policy)
            if principal is None:
                # No detail about what was wrong with the credential. "Unknown
                # token" and "expired token" are different facts, and telling
                # them apart is useful to an attacker and to nobody else.
                return _refuse(401, "unauthenticated", "a valid API token is required", request_id)
            request.state.principal = principal

            scoped = _project_in_path(request.url.path)
            if scoped is not None and not principal.may_read(scoped):
                # 404, not 403. Telling an unauthorised caller that a project
                # exists is itself a disclosure, and this is indistinguishable
                # from the answer someone gets when they are simply wrong about
                # the id.
                return _refuse(404, "project_not_found", f"No project {scoped}.", request_id)

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


_PROJECT_PREFIX = "/v1/projects/"


def _project_in_path(path: str) -> str | None:
    """Return the project a path names, if it names one.

    Authorisation happens here rather than in each router so that a route added
    later is covered the day it is added, not the day someone remembers. The
    limitation is real and worth stating: paths that identify a resource
    *without* naming its project — `/v1/knowledge/{id}/trace`,
    `/v1/sessions/{id}/messages`, `/v1/runs/{id}` — cannot be authorised this
    way, and a scoped token still reaches them. Closing that needs the resource
    to resolve its project first, which is a change to those handlers rather
    than to this one.
    """

    if not path.startswith(_PROJECT_PREFIX):
        return None
    remainder = path[len(_PROJECT_PREFIX) :]
    identifier = remainder.split("/", 1)[0]
    return identifier or None


def _authenticate(request: Request, policy: AuthPolicy) -> Principal | None:
    """Resolve the bearer token to a principal, in constant time."""

    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented.strip():
        return None

    candidate = presented.strip()
    # Compared against every configured token rather than by dictionary lookup,
    # so the time taken does not depend on how much of the token was correct.
    matched: Principal | None = None
    for token, principal in policy.tokens.items():
        if hmac.compare_digest(token, candidate):
            matched = principal
    return matched


def _refuse(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    response = error_response(status_code, code, message)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def generate_token() -> str:
    """Return a token suitable for an operator to configure.

    Provided so that "make one up" is not the documented instruction. 32 bytes
    of URL-safe randomness, which is beyond guessing and short enough to paste.
    """

    return secrets.token_urlsafe(32)
