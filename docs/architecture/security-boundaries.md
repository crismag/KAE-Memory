# Security boundaries

What KAE-Memory currently protects, what it does not, and where the edges are.

> **Read this before exposing the service.** It describes the supported security
> model honestly, including where that model is thinner than a reader would
> assume. KAE-Memory is under active development and makes no production-
> readiness claim.

---

## The trust boundary

Two boundaries, and only one of them is enforced by KAE-Memory.

**Client to KAE-Memory** — a bearer token, `KAE_API_TOKENS`, optionally scoped to
named projects. This is the boundary the application enforces.

**KAE-Memory to database** — the application holds the credential; clients do not
([ADR-0027](../../specifications/ADR/ADR-0027-application-contracts-are-the-write-path.md)).
This is a boundary of construction, not of enforcement: nothing stops someone who
has database credentials from using them.

## Refusing to start

Two guards, in `build_auth_policy`:

- an entry in `KAE_API_TOKENS` that is not `name:token` raises and the process
  does not start;
- binding to a non-loopback interface with no tokens raises and the process does
  not start ([ADR-0024](../../specifications/ADR/ADR-0024-http-trust-boundary.md)).

A refusal to start is a deployment that does not happen. A warning is a line a
deployment scrolls past.

## What those guards do not cover

**They protect the interface the process binds to — not the interface a user
reaches.**

The recommended shape puts a reverse proxy in front and binds the API to
loopback. In that shape the second guard cannot fire, because the API is
genuinely bound to loopback. Whether requests arriving there came from the host
or from the internet is not something the API can see.

**So a proxied deployment must supply `KAE_API_TOKENS` deliberately.** Nothing
will refuse to start if it does not. The service will run, `/health` will be
green, and requests will succeed.

### Verify it, do not assume it

After any deployment or restart, from **outside** the host:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://your-host/v1/projects
# expect 401
```

A `200` means the deployment is unauthenticated. Check it after every restart,
not only at first deployment — a unit that fails to pick up new configuration
looks identical to one that did.

This is the single check most worth automating in a deployment pipeline.

> A related weakness in this area is recorded privately and is not described
> here. It is on the development backlog. **Public-hosting configurations should
> not be assumed secure on the strength of the process having started.**

---

## What is not protected

Stated plainly, because each is a real limitation rather than an oversight.

**Reviewer identity is unattested.** The `reviewer` on a confirmation is
caller-supplied free text. An authenticated caller can attribute a decision to
someone who never made it. Provenance is reliable about *what* and *when*, and
only as reliable as the caller about *who*
([#83](https://github.com/crismag/KAE-Memory/issues/83)).

**Tokens are static.** No rotation, expiry, or revocation beyond changing the
environment and restarting.

**No per-user identity.** A token identifies a *caller*, not a person. Several
people sharing a token are one principal in every record.

**No rate limiting.**

**No audit of reads.** Writes carry provenance; reads do not.

**Project scoping is by token.** A token without a project list reaches every
project the deployment can read.

---

## What is protected

**Domain invariants cannot be bypassed through the supported interfaces.**
Lifecycle transitions, version checks and provenance are enforced in application
code, so no sequence of API calls produces state the rules did not permit.

**They can be bypassed by direct database access**, which is why ADR-0027 puts
that outside normal workflows. That claim is currently reasoned from where the
enforcement lives rather than demonstrated
([#86](https://github.com/crismag/KAE-Memory/issues/86)).

**Request bodies are bounded.** `MAX_BODY_BYTES` is a ceiling in code and
deliberately not configurable — a deployment able to raise it has removed a
protection rather than tuned it.

**CORS fails closed.** `KAE_CORS_ORIGINS` defaults to empty.

**Secrets stay out of the repository.** Connection strings and tokens are
environment-only, by decision recorded in the settings catalog.

---

## Deploying responsibly

1. Bind to loopback and terminate TLS at a proxy.
2. Set `KAE_API_TOKENS` **explicitly**, even though loopback will not force you.
3. Scope tokens to projects where a caller does not need all of them.
4. Verify a `401` from outside the host, after every restart.
5. Keep the database unreachable from anywhere but the application.
6. Treat reviewer attribution as advisory until
   [#83](https://github.com/crismag/KAE-Memory/issues/83) closes.

## Related

- [Configuration](../reference/configuration.md) — token format
- [Access and mutation policy](../reference/access-and-mutation-policy.md)
- [Deployment](../operations/deployment.md)
