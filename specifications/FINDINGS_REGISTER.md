# Findings and action register

Everything credible found while documenting KAE-Memory: defects, limitations,
missing capability, verification gaps, unresolved decisions.

**This register exists so that documenting the system honestly does not require
fixing it first.** A known limitation, written down, is documentable. A hidden
one is not. Nothing here is normalised, and nothing is closed by being described.

It is also the handoff. When work returns to Studio–CIE–KAE productisation, this
is the list that goes with it — with evidence, impact, and priority attached.

## Tracking

Actionable findings are public issues on this repository. **F-001 is not**, and
must not be filed while it stands — this repository is public and the finding
describes an unauthenticated-access path. It is tracked here and privately.

| Finding | Issue |
|---|---|
| F-002 cross-session continuity | [#80](https://github.com/crismag/KAE-Memory/issues/80) |
| F-003 CockroachDB parity | [#81](https://github.com/crismag/KAE-Memory/issues/81) |
| F-004 reviewer identity | [#83](https://github.com/crismag/KAE-Memory/issues/83) |
| F-005 retrieval threshold | [#82](https://github.com/crismag/KAE-Memory/issues/82) |
| F-006 / N12 module curation | [#85](https://github.com/crismag/KAE-Memory/issues/85) |
| F-008 fixture-fallback visibility | [#84](https://github.com/crismag/KAE-Memory/issues/84) |
| F-011 direct-write bypass | [#86](https://github.com/crismag/KAE-Memory/issues/86) |
| F-012 project isolation | [#87](https://github.com/crismag/KAE-Memory/issues/87) |
| F-013 dependency cycles | [#88](https://github.com/crismag/KAE-Memory/issues/88) |
| F-014 fixture fallback modes | [#89](https://github.com/crismag/KAE-Memory/issues/89) |
| F-015 idempotency under concurrency | [#90](https://github.com/crismag/KAE-Memory/issues/90) |

**The issues carry no labels.** The token that filed them can create issues and
not modify them — `addLabelsToLabelable` and `addComment` are both refused — so
severity, gate and the `finding` label could not be applied. The `finding` and
`verification` labels exist and are unused. Applying them needs a token with
issue-write scope, or a few minutes in the web UI. **Severity and gate for every
finding live in this file**, which is where they were going to be authoritative
anyway; the labels would have made them filterable, not knowable.

F-007 is resolved. F-009 and F-010 are documentation work and stay in the
[documentation plan](documentation-plan/DOCUMENTATION_MANIFEST.md) rather than
becoming issues — filing writing tasks as defects makes both harder to read.

## Severity

| | Meaning |
|---|---|
| **S1** | Unsafe, or invalidates a central claim. Blocks public deployment or any stability claim |
| **S2** | Materially wrong behaviour or a missing capability users will hit |
| **S3** | Limitation worth knowing; documentable as-is |
| **S4** | Unverified but reasonable; needs confirmation before being stated as fact |

## Gate

**`release`** — must be resolved before a stable release or production-readiness
claim. **`deploy`** — before public hosting. **`validate`** — before the claim is
stated as executably proven. **`decide`** — needs a human decision.

---

## S1 — Blocks deployment or a stability claim

### F-001 — A reverse-proxy deployment can run unauthenticated — **FIXED 2026-08-07**

**Severity S1 · was gate `deploy`, `release` · Security**

**Resolved.** The default is now refusal: no tokens means the process does not
start, on any interface. Loopback is no longer read as development, because a
reverse proxy in front of a loopback listener is a public API and the process
cannot see the difference.

A deployment that genuinely wants no authentication sets
`KAE_ALLOW_UNAUTHENTICATED=1` — deliberately, in a variable a reviewer reading
the environment can see, refused off-loopback, and refused for any value that is
not an explicit affirmative so a stray export cannot disable authentication.
Tokens win over the opt-out where both are set.

23 regression tests in `tests/api/test_auth_cannot_fail_open.py`, including the
exact F-001 shape. One superseded test was rewritten rather than deleted: it
asserted that loopback without tokens was allowed, and the belief behind it —
"a developer's laptop is not a deployment" — is true and does not follow from
the bind address. That was the defect.

**This no longer blocks DEP-D4.** The original finding follows, for the record.

---

**Original finding**

`build_auth_policy` refuses to start when bound off-loopback without tokens, and
raises on a malformed `KAE_API_TOKENS` entry. Both guards work. The hole is the
shape they do not cover:

```python
exposed = host not in LOOPBACK
if exposed and not tokens:
    raise InsecureDeploymentError(...)
return AuthPolicy(tokens=tokens, required=bool(tokens))
```

**Behind a reverse proxy the API binds to `127.0.0.1`, so `exposed` is false and
the guard never fires. If `KAE_API_TOKENS` is unset or empty, `required` is
`False` and every request is accepted — while nginx serves the API to the
internet.** The one deployment shape ADR-0024 recommends is the one the guard
does not protect.

It fails **open**, and it is silent: the service starts, `/health` is green, and
requests succeed. Nothing distinguishes it from a working deployment except
trying an unauthenticated call and having it work.

Observed in this project's own deployment: the API answered unauthenticated
requests after the token secret was written in the wrong format, and again after
`systemctl enable --now` failed to restart an already-running unit. Both times
it was found by deliberately testing the negative case, not by any signal.

**Evidence:** `src/kae_memory/api/security.py:119–126` (E1, read directly).
**Affects:** `docs/operations/deployment.md`, `docs/architecture/security-boundaries.md`,
`docs/reference/access-and-mutation-policy.md`.
**Documentation disposition:** public-hosting instructions must not present a
proxied deployment as safe without stating this. The deployment page states the
requirement and the check; it does not describe the configuration as secure.
**Fix direction (not implemented):** a proxied deployment is still exposed. Either
require tokens whenever a trusted-proxy header is configured, or make
`required` default to `True` and force an explicit opt-out for local
development. Both are behaviour changes and belong to the development cycle.
**Do not file this as a public GitHub issue before it is fixed** — this
repository is public.

**Correction to Phase 2A.** The Phase 2A gap register recorded this as "a
malformed value parses to zero tokens and authentication becomes optional".
That is wrong: malformed entries raise. The mechanism above is the accurate one,
and it is narrower and more specific.

---

## S2 — Materially affects users

### F-002 — Cross-session continuity is unproven end to end

**Severity S2 · Gate `validate`**

The claim the product turns on — a later session knows what an earlier one
established — has no end-to-end test. The parts are tested; the composition is
not.

**Evidence:** E4, inferred from tested components. **Affects:**
`docs/examples/cross-session-continuity.md`, `docs/index.md`, README.
**Disposition:** describe continuity from the evidence that exists — durable
storage, retrieval, and context assembly are each tested — and **do not present
it as executably proven** until the validation phase records a transcript.

### F-003 — CockroachDB is unverified at the current schema head

**Severity S2 · Gate `release`**

Parity demonstrated at revision `0009`, 2026-08-04. Head is `0021` — twelve
revisions, several adding unique or check constraints, which is the class of
divergence that produced `0009` in the first place.

**Evidence:** E1 (head counted), E5 (the compatibility claim).
**Affects:** `docs/architecture/persistence-and-providers.md`, configuration.
**Disposition:** documentation says *selectable provider, parity demonstrated at
`0009`, not re-verified since*, and links VG-4. **Never "supports CockroachDB"
unqualified.** Tracked as VG-4; running the 7.5-hour suite is a release
decision.

### F-004 — Reviewer identity is unattested

**Severity S2 · Gate `release`**

`reviewer` is caller-supplied free text on confirm and reject. An agent can
record a human decision nobody made, and nothing detects it.

**Evidence:** E2. **Affects:** `docs/reference/access-and-mutation-policy.md`,
`docs/workflows/review-knowledge.md`, `docs/concepts/provenance-and-evidence.md`.
**Disposition:** documented as a limitation. Provenance is trustworthy about
*what* and *when*, and only as trustworthy as the caller about *who*. Tracked as
VG-3.

### F-005 — Retrieval threshold is fitted to a corpus far smaller than real use

**Severity S2 · Gate `release`**

`MAX_DISTANCE = 0.85`, fitted to twenty queries over thirty-two chunks. The
window between the worst genuine match (0.840) and nearest noise (0.847) is
**0.005 wide**, and one weak query leaked at fitting time.

**Evidence:** E1. **Affects:** `docs/workflows/retrieve-and-search.md`.
**Disposition:** documented as a known limitation with the measured numbers.
Hybrid ranking is the durable answer, not a different constant. Tracked as VG-2.

---

### F-016 — Sign-in rate limiting has no home yet

**Severity S3 · Gate `release` · Security**

Studio's identity is one operator password, so an unlimited sign-in endpoint on
a public address is worth limiting. It currently is not.

**An attempt at the proxy was removed rather than loosened.** nginx sees a URI,
not an outcome: the same location serves `GET /api/session`, which the app calls
on every page load to ask whether a session is still valid. Limiting it
throttled ordinary use, and a rate-limited `503` carries no CORS headers, so the
browser blocks it, the fetch throws, and the app reports the backend as
unreachable. Excluding the method with a `map` on `$request_method` did not take
effect in this nginx build.

It cost real time to diagnose because it degrades under load only: single
requests pass, a browser session fails intermittently, and every symptom points
away from the proxy.

**Where it belongs:** Studio, which knows the difference between a failed
password and a session check without inspecting a URI, and can count failures
per principal rather than per address.

**Until then** the protection is the password: 24 random characters, against
which an unthrottled attacker still gets nowhere. Acceptable for a
single-operator deployment under active development; not acceptable for a
release.

## S3 — Limitations, documentable as they are

### F-006 — Modules are MCP-only, and the reasons are recorded per capability

**Severity S3**

Five capabilities are `agent_only`: `module.define`, `module.relate`,
`module.graph`, `module.context`, `observation.submit`. **Each carries its own
reason in the registry**, which is more than I credited in Phase 2A when I
recorded this as one unresolved justification. They differ:

- `module.define` / `module.relate` — Studio's curation act is
  `recordModuleDecision`, a different contract still unreconciled (N12)
- `module.graph` / `module.context` — the consumer is an implementing agent; a
  Studio view of the same graph is a rendering question, and rendering is
  Studio's
- `observation.submit` — Studio's equivalent is a conversation message, a
  different durable act; both over HTTP would give a client two ways to say one
  thing

**What remains open is narrower than "why":** N12, whether Studio's curation
contract eventually needs HTTP routes. That is a product question, not a gap in
the documentation.

**Disposition:** the generated capability matrix carries each reason verbatim.
Concept pages do not restate them.

### F-007 — `reembedding_service` is on no adapter — ~~open~~ **resolved 2026-08-07**

**Severity S3 · was gate `decide`**

I recorded this as "internal, or unfinished — unknown". It was neither unknown
nor undeclared: the capability registry carries it as `embedding.reembed`,
`Exposure.INTERNAL`, with the reason written out —

> Long-running, restartable, and destructive to get wrong. Driven by
> `scripts/development/reembed-knowledge.py`, where it can be resumed.

That script exists. **This is a deliberate decision, documented at the point of
decision, and I mistook a registry I had not read closely enough for a gap.**

**Disposition:** documented as an internal operational capability, reached by
script, in `docs/operations/`. Not part of the client surface. **D3 is
withdrawn.**

### F-008 — Extraction is asynchronous and can silently run without a model

**Severity S3**

Recording a message queues a run that completes later. Without model access,
extraction falls back to a deterministic fixture, and run summaries then carry
`"model": "deterministic-fixture"`.

**Disposition:** documented prominently in acquisition workflows — a user who
expects synchronous extraction will read an empty result as a failure. The
fixture fallback must be stated, not buried; a system that appears to be
reasoning and is not is worse than one that says it cannot.

### F-009 — No token configuration procedure exists

**Severity S3 · Gate `deploy`** — related to **F-001**

The format is `name:token`, or `name:token:project,project`, semicolon-separated
(`security.py:106–116`, E1). Nothing documents it, and nothing documents
generating or storing a value.

**Disposition:** `docs/reference/configuration.md` documents the format from the
parser. The deployment guide references it. **Both must carry F-001.**

### F-010 — README is still a development document

**Severity S3**

Milestone table M0–M11, code inventory, file-layout table. Survived Phase 1
because it was not under `docs/`.

**Disposition:** rewritten in this phase as an entry point.

---

## S4 — Reasonable, unconfirmed

Each needs a focused check in the validation phase. **None may be stated as fact
until then.**

| # | Claim | Basis | Confirm by |
|---|---|---|---|
| F-011 | Direct database writes bypass domain invariants | Transitions live in Python, not the schema | Write one; assert the resulting state is invalid |
| F-012 | Projects are isolated on every read and write | Repositories are project-scoped | Two projects, similar records, assert no bleed |
| F-013 | Dependency cycles are prevented | `module_service.py` appears to check | Attempt a cycle |
| F-014 | Extraction always falls back to a fixture without a model | Observed once | Run with no model access; check the run summary |
| F-015 | Idempotency holds under concurrency | Unique constraints exist; exercised on PostgreSQL only | Concurrent duplicate submissions |

**F-011 matters most.** It is ADR-0027's central premise, and it is currently
reasoned rather than demonstrated.

---

## Decisions needed

| # | Decision | Blocks |
|---|---|---|
| ~~D1~~ | **Decided 2026-08-07.** A provider-neutral public deployment and operations guide, describing supported topology, configuration, migrations, startup and health — without exposing or recreating private deployment automation | `docs/operations/` proceeds |
| ~~D2~~ | **Decided 2026-08-07.** **No stability or backward-compatibility guarantee at this stage**, stated explicitly rather than left to inference | README and `docs/index.md` say so plainly |
| ~~D3~~ | **Decided 2026-08-07.** F-001 stays private until remediated. Not filed as a public issue | Remaining actionable gaps become public issues |

All open decisions are answered. What remains is work, not direction.

*(D3 — `reembedding_service` — withdrawn 2026-08-07; the registry already
answered it. Numbering closed up.)*

---

## Before a production-readiness claim

Not a roadmap — the minimum that must be true before the words "production
ready", "stable", or "fully supported" may appear:

- **F-001** resolved, with a test covering the proxied shape
- **F-002** proven end to end and recorded
- **F-004** resolved or explicitly accepted in writing
- **F-011** demonstrated rather than reasoned
- **F-003** either re-verified or the compatibility claim withdrawn
- **D2** — answered: no guarantee is claimed, and documentation says so

Until then, documentation describes what exists and what it does not. **That is
not a lesser thing to publish — a system whose limitations are written down is
more usable than one whose limitations are discovered.**
