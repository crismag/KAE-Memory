# ADR-0024 — HTTP trust boundary

**Status:** accepted, 2026-08-05. Target **N5** of
`docs/09_development/NEXT_PHASE_CHECKLIST.md`. **Supersedes ADR-0014's "no
authentication"**; the rest of ADR-0014 is unaffected.

## Decision

> The HTTP API authenticates callers with a bearer token, authorises project
> access **separately** from authentication, and **refuses to start** if it
> would listen on a non-loopback interface without a token configured.

CORS is not authentication and never was.

## What changed since ADR-0014

ADR-0014 recorded no authentication as an accepted MVP risk, with the mitigation
that "the API is safe only behind a network boundary". That was a defensible
trade for four services on loopback.

Two things then happened. **N3** put search, ingestion, clarification, assembly,
and classification behind the same surface — thirty-eight routes reaching every
durable thing the platform holds. **ADR-0023** made HTTP the transport
KAE-Studio speaks, and Studio is a browser application on a different origin.

The mitigation was a network boundary that a browser client is specifically
designed to cross.

## Fail closed on exposure

A process bound to loopback with no tokens configured runs unauthenticated. That
is a developer's laptop, and requiring a credential there buys nothing but
friction.

The same process bound to any other interface **raises at startup**. Not a
warning: a warning about an unauthenticated public API is a line in a log that a
deployment scrolls past, and the failure it predicts arrives later, quietly, as
a request nobody was watching for. A refusal to start is a deployment that does
not happen.

This mirrors `KAE_CORS_ORIGINS`, which ADR-0017 made empty by default so that a
misconfigured split-origin deployment fails closed. The two now agree.

## Authentication and authorisation are separate

`KAE_API_TOKENS` maps a token to a **principal**. A principal may carry a
project scope; an unscoped one reaches every project, because the restriction is
opt-in — a token scoped to nothing would authenticate and then do nothing, which
is a configuration mistake rather than a useful state.

Authorisation is applied **by path**, at the boundary, rather than in each
router. A route added later under `/v1/projects/{id}/` is covered the day it is
added rather than the day someone remembers to add a check to it.

This keeps the separation `PROJECT_FOCUS.md` §5 insists on for focus: a caller
who may not read project B is stopped by permission, not by a convenience that
happened to point elsewhere.

**An unauthorised project returns 404, not 403.** Telling a caller that a
project exists is itself a disclosure, and the answer is now indistinguishable
from the one someone gets when they are simply wrong about the id.

## Limits, stated rather than implied

**Path-based authorisation cannot cover paths that do not name a project.**
`/v1/knowledge/{id}/trace`, `/v1/sessions/{id}/messages`, and `/v1/runs/{id}`
identify a resource whose project is only knowable after a lookup. A scoped
token still reaches them. Closing it means those handlers resolving their
project before answering, which is a change to them and not to the boundary.

**No rate limiting.** A token bucket in one process is not a rate limit when two
processes run, and implementing one here would give a false sense that abuse is
bounded. Rate limiting belongs to whatever terminates TLS in front of this.

**No timeouts.** Set by the ASGI server, and configured at deployment.

**Tokens are static and come from the environment.** No rotation, no expiry, no
introspection endpoint. Rotation is an operational procedure — replace the
value, restart — and pretending otherwise would need a credential store this
repository does not have.

## Consequences

**Accepted.** Every non-public HTTP call needs a header. `/health` does not,
because FR-017 requires it to answer without one, and a health check that needs
a credential fails for the two different reasons a monitor most needs to tell
apart.

**Accepted.** Local development is unauthenticated by default and that is a
documented mode, not an oversight.

**Rejected: authenticating with CORS.** An allowlisted origin is a browser
convention, not a credential; it is trivially bypassed by anything that is not a
browser.

**Rejected: per-router dependency checks.** They work until the router someone
adds without one, and that router is indistinguishable from a correct one until
it is exploited.

**Rejected: deferring until deployment.** The gap exists now. Thirty-eight
routes and no credential is not a smaller problem for being local, because
"local" is a property of the current configuration rather than of the code.

## Evidence

`src/kae_memory/api/security.py`, and `tests/api/test_trust_boundary.py` — 22
tests, the first of which asserts that an exposed unauthenticated process
refuses to start.
