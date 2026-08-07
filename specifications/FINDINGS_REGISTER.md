# Findings and action register

Everything credible found while documenting KAE-Memory: defects, limitations,
missing capability, verification gaps, unresolved decisions.

**This register exists so that documenting the system honestly does not require
fixing it first.** A known limitation, written down, is documentable. A hidden
one is not. Nothing here is normalised, and nothing is closed by being described.

It is also the handoff. When work returns to Studio–CIE–KAE productisation, this
is the list that goes with it — with evidence, impact, and priority attached.

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

### F-001 — A reverse-proxy deployment can run unauthenticated

**Severity S1 · Gate `deploy`, `release` · Security**

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

## S3 — Limitations, documentable as they are

### F-006 — Modules are MCP-only, for an unresolved reason

**Severity S3 · Gate `decide`**

`kae_define_module`, `kae_relate_modules`, `kae_get_module_graph` are declared
`agent_only`. **This is a decision, not a defect** — but its justification (N12,
Studio's curation contract unreconciled) is itself open.

**Disposition:** documented as MCP-only by decision. Do not imply HTTP support is
coming; do not imply oversight.

### F-007 — `reembedding_service` is on no adapter

**Severity S3 · Gate `decide`**

Present in `application/`, absent from the capability registry and both
adapters. Internal, or unfinished — unknown.

**Disposition:** **not documented** until decided. An undocumented internal
service is correct; an advertised one that cannot be called is not.

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
| D1 | How deep may the public deployment guide go, given the working example is private? | Depth of `docs/operations/deployment.md` |
| D2 | Is any version or interface stability claimed? | README, `docs/index.md` — documentation implies stability by existing |
| D3 | Is `reembedding_service` internal or unfinished? | F-007 |
| D4 | Should F-001 be filed publicly, or handled privately until fixed? | Issue creation. **Recommendation: privately.** This repository is public |

---

## Before a production-readiness claim

Not a roadmap — the minimum that must be true before the words "production
ready", "stable", or "fully supported" may appear:

- **F-001** resolved, with a test covering the proxied shape
- **F-002** proven end to end and recorded
- **F-004** resolved or explicitly accepted in writing
- **F-011** demonstrated rather than reasoned
- **F-003** either re-verified or the compatibility claim withdrawn
- **D2** answered

Until then, documentation describes what exists and what it does not. **That is
not a lesser thing to publish — a system whose limitations are written down is
more usable than one whose limitations are discovered.**
