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

**Resolved in substance, still open on GitHub.** The filing token can create
issues and not modify them, so nothing below can be closed from here.
[#80](https://github.com/crismag/KAE-Memory/issues/80) (F-002),
[#86](https://github.com/crismag/KAE-Memory/issues/86) (F-011),
[#87](https://github.com/crismag/KAE-Memory/issues/87) (F-012),
[#88](https://github.com/crismag/KAE-Memory/issues/88) (F-013),
[#89](https://github.com/crismag/KAE-Memory/issues/89) and
[#90](https://github.com/crismag/KAE-Memory/issues/90) are all closed as of
2026-08-07, though not all the same way. F-002, F-011, F-012 and F-013 are
answered by new tests in `tests/integration/`. **F-014 is withdrawn** — the
claim was wrong about the code. **F-015 needed nothing** — proof already existed
and this register had not found it. All five still need closing by hand.

| Finding | Issue |
|---|---|
| ~~F-002 cross-session continuity~~ **resolved** | [#80](https://github.com/crismag/KAE-Memory/issues/80) |
| F-003 CockroachDB parity | [#81](https://github.com/crismag/KAE-Memory/issues/81) |
| F-004 reviewer identity | [#83](https://github.com/crismag/KAE-Memory/issues/83) |
| F-005 retrieval threshold | [#82](https://github.com/crismag/KAE-Memory/issues/82) |
| F-006 / N12 module curation | [#85](https://github.com/crismag/KAE-Memory/issues/85) |
| F-008 fixture-fallback visibility | [#84](https://github.com/crismag/KAE-Memory/issues/84) |
| ~~F-011 direct-write bypass~~ **resolved** | [#86](https://github.com/crismag/KAE-Memory/issues/86) |
| ~~F-012 project isolation~~ **resolved** | [#87](https://github.com/crismag/KAE-Memory/issues/87) |
| ~~F-013 dependency cycles~~ **resolved** | [#88](https://github.com/crismag/KAE-Memory/issues/88) |
| ~~F-014 fixture fallback modes~~ **withdrawn — claim was wrong** | [#89](https://github.com/crismag/KAE-Memory/issues/89) |
| ~~F-015 idempotency under concurrency~~ **already proven** | [#90](https://github.com/crismag/KAE-Memory/issues/90) |
| F-018 extraction loss · **S1** — *disclosed, not repaired* | not filed |
| ~~F-019 reviewer is a fixture~~ · **the three real causes are fixed** in code, **not deployed** | not filed |
| ~~F-020 staleness not surfaced~~ · recalculation half built | not filed |
| ~~F-021 a project cannot be deleted~~ **closed** — `project.delete`, T0.2, `9c2dc23` | not filed |
| F-022 more unreachable capabilities — **eight, not ten** | not filed |

**F-018 to F-022 are not filed as issues.** They are recorded here and need
filing by someone with issue-write scope. None is security-sensitive, so unlike
F-001 there is no reason to keep them private — they are unfiled only because
this session had no authorisation to open public issues, not because they should
stay here.

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

### F-002 — Cross-session continuity is unproven end to end — ~~open~~ **resolved 2026-08-07**

**Severity S2 · Gate `validate`**

**The original finding overstated the gap.** It said the claim "has no
end-to-end test". It had one: `tests/agents/test_collaboration.py` (AT-006) runs
a requirements agent in a discovery session, confirms a rule, discards the
process, and has an architecture agent in a *second* session derive from
confirmed knowledge alone. That is the composition, and it passed the whole time.

What was genuinely missing is the other half of continuity — the part about
*not* carrying things forward — and the last hop to a consumer.

**Closed by**
[`tests/integration/test_cross_session_continuity.py`](../tests/integration/test_cross_session_continuity.py).
A first session records a message, extracts three statements, and a person
confirms two and rejects one. A second session — new service instances, a new
session record, nothing carried in memory — then reads the project through the
ordinary path, **without naming the first session or its run**.

It covers only what AT-006 does not, so the two do not overlap:

* the rejected statement does **not** come back — continuity that resurrects
  discarded candidates silently undoes a person's decision, which is worse than
  no continuity at all;
* the rejection is still readable *as a decision*, so the second session can
  tell "we said no to this" from "nobody has considered this";
* provenance survives, so a later reader can distinguish agreement from
  assertion;
* it reaches the **assembled package**, not just a database query — the consumer
  is an agent reading assembled context, so that last hop is part of the claim.

**Consequence:** continuity may now be described as executably proven. The
qualification previously required in `docs/index.md` and the README no longer
applies. [#80](https://github.com/crismag/KAE-Memory/issues/80) is resolved in
substance; the filing token cannot close issues (see *Tracking*), so it needs a
minute in the web UI.

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

### F-017 — CI's lint and format gates were failing, and had been silently — **FIXED 2026-08-07**

**Severity S3 · Gate `release` · Tooling**

`ruff check .` reported 16 errors and `ruff format --check .` named three files,
so two of CI's four gates were red before any of this session's work. Nothing in
the code had changed to cause it.

**The cause is an unpinned linter.** `pyproject.toml` asked for `ruff>=0.6` and
resolved 0.16, which added rules (`RUF043` among them) that the existing code
had never been written against. A dependency range that admits new rules makes
the build a function of when it last resolved, and "the gate went red on its own"
is indistinguishable from "someone broke it" once it has been red for a while.

The three unformatted files were all from the most recent commits, which is the
other half of it: once a gate is red for an unrelated reason, it stops reporting
the related ones.

**Fixed.** All 16 resolved and everything formatted. `RUF002` is now ignored with
a reason — it flags en dashes in docstrings as confusable characters, and in
prose like `N30–N32` the en dash is correct typography; the rule exists for
homoglyphs in identifiers. The three `RUF043` sites became raw strings, which
says the metacharacters are intended rather than escaping them and changing what
matches. One nested `if` was flattened by naming the condition. No behaviour
changed: the suite passed and mypy was clean. (It was 1728 tests then; 1885 now.)

**Not done, and worth a decision:** the range is still `ruff>=0.6`. Pinning it
makes the gate reproducible and moves upgrades into a deliberate step; leaving
it means this recurs on some future release. That is a workflow preference, so
it is recorded rather than chosen.

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

---

## Found by the reference corpus, 2026-08-07

Grouped by **how they were found** rather than by severity, because that is the
useful fact about them: four real projects were loaded — two working
repositories, one public repository, and a written specification — totalling
1,575 statements, and these five appeared within hours.

Nothing here was reachable by the previous test data. The best of the old
fixtures held 78 items, half of them open questions, and every one of these
findings needs volume or real technical documentation to surface at all.

Severities are stated per finding and two of them are S1.

### F-018 — Extraction silently loses a third to two-thirds of real content

**Severity S1 · Gate `release` · Correctness**

Measured by loading four real projects, 2026-08-07. Abandon rate by corpus:

| Corpus | Succeeded | Abandoned | Rate |
|---|---|---|---|
| AWS Compute Lab — 57 docs of Python/AWS tooling | 62 | 35 | **36%** |
| php-dbo-gateway — 19 docs of a PHP security gateway | 39 | 30 | **43%** |
| Plane — README, SECURITY, CONTRIBUTING, analysis | 6 | 11 | **65%** |
| A prose-only specification, written for the purpose | 15 | 6 | **29%** |

Every abandoned chunk is `retry_budget_exhausted` after three attempts, each
failing `verify_quotes`: *"item N cites a quote that does not occur in the
source"*. The cited fragments are directory trees, code fences and tables —
`_normalise` collapses whitespace and casefolds, which survives reflowed prose
and not box-drawing characters.

**The batch rule amplifies it.** `verify_quotes` fails the whole batch on one
unverifiable citation, so every good item in that chunk is discarded with it.
That is defensible for prose and not obviously right at a 36% loss rate.

**S1 because everything downstream inherits it.** Requirements, readiness,
definition, coverage and any future baseline are computed over between a third
and two-thirds of what the project actually said. The loss is silent: the only
trace is a run status.

**Not fully diagnosed.** Structured content is directional, not total — the
prose-only corpus still lost 29% and nothing explains it yet. Do not assume one
cause. **Evidence:** the four reference projects on the deployment.
**Drives:** EM-7.

### F-019 — Review never ran, readiness never recalculated, and the reviewer degraded silently

*(Originally titled "The shipped reviewer is a fixture, so eight of ten areas
can never populate". That title named the symptom and the wrong cause; the
correction inside supersedes it, and PPA/REVIEW-01 in the ecosystem register
carries the full account. **The fixes are local — the deployment still runs
2026-08-07/08 code**, so on the running system every word of the original
finding remains observable.)*

**Severity S1 · Gate `release`**

Review assigns knowledge to discovery areas; readiness counts per area. The
configured reviewer is `deterministic-review-fixture`, which classifies only
where a knowledge kind leaves no choice.

> **Corrected 2026-08-09, and the cause was not what this said.** The original
> text blamed `KAE_REVIEW` having no live adapter on the deployment.
> `KAE_REVIEW=bedrock` had in fact been set since 2026-08-08 03:48 UTC, with the
> worker restarted at 04:05. Running the pass by hand against the live host
> found **three independent links in series**, so fixing any one alone changed
> nothing:
>
> 1. **Nothing triggered review.** `POST /review/runs` worked and no caller ever
>    called it — the project had 25 knowledge revisions and zero review runs.
>    Fixed by `82e9bf8`: a knowledge-writing run asks for review once it is the
>    last run standing, enqueued in the transaction that marks it succeeded.
> 2. **Nothing recalculated readiness.** `knowledge_revision: 0` against
>    `current_knowledge_revision: 25`, `is_stale: true` — see F-020. The review
>    run now recalculates.
> 3. **The reviewer degraded silently.** All 178 statements went in one request
>    and it returned `provider_timeout`; the run recorded
>    `offline_by_kind_after_reviewer_error` and reported **succeeded**. Fixed by
>    `524b2b1`: batched, with partial degradation reported per batch.

Measured over four projects holding 1,575 statements: **only
`users_and_stakeholders` and `constraints_and_assumptions` ever populate.** 242
requirements, 197 rules, 66 goals and 36 decisions are assigned nowhere, because
deciding whether a requirement belongs to *Functional requirements* or *Scope
and boundaries* is a judgement the fixture will not make.

**Consequence:** readiness is not wrong, it is *correct about two areas out of
ten*. Definition Health, Requirements Coverage, and the ten-to-seven mapping
ruled in D-A all read from area assignment, so each is capped at describing a
fifth of the taxonomy however well it is built.

**Why exactly two, and why it is structural.** Across `SOFTWARE_TEMPLATE`,
exactly **two of eight knowledge kinds map to a single area** — `actor` →
`users_and_stakeholders`, `assumption` → `constraints_and_assumptions`. Goal,
rule, constraint, requirement and decision each map to between two and five, so
the offline classifier declines all of them. Correctly: guessing manufactures
coverage a user then has to unpick (ADR-0015).

So a deployment without a review model does not get *partial* coverage. It gets
two areas, and only where those two kinds happen to appear.

**The ceiling is 16%.** Those two areas carry weight 1.0 each against a template
total of 12.5, so a project perfect in both and silent everywhere else reports
16%. Both are mandatory, so `implementation_eligible` — which requires every
mandatory area sufficient — is unreachable offline whatever else is true.
**`KAE_REVIEW` is not an optimisation**, and rebalancing the template to make more kinds
unambiguous would trade classification precision for offline capability — a
decision nobody has taken. Pinned by
`tests/integration/test_thin_vertical_proof.py::TestTheOfflineClassifierIsStructurallyLimited`,
which names the two kinds rather than counting them.

**Distinct from F-004.** That is about attesting the *human* who confirms; this
is about the *model* that classifies. **Drives:** EM-6b.

### F-020 — Readiness staleness is available and not surfaced — *half closed*

**Recalculation is built** (`82e9bf8`): a review run now recalculates readiness,
so the snapshot no longer sits at revision 0 of 25 indefinitely. What remains is
the *disclosure* half — Studio still renders a snapshot without saying whether it
is current. Not deployed.

**Severity S3**

`ReadinessResponse` carries `is_stale`, and since EM-1 it carries both the
snapshot's revision and the project's current one. Studio renders a stale
snapshot without saying so.

Found when review assigned 19 and 40 areas across two projects and the
projection still reported every area empty — the assignment had worked and the
snapshot predated it. Recalculating produced the first non-zero readiness the
system has ever reported.

Same class as the old revision field: a value that is real, stale, and
presented as current. **Folded into** the Wave 2 projection work rather than
carried separately.

### F-021 — A project cannot be deleted without violating a foreign key — **CLOSED**

**`project.delete` exists** (`capabilities.py`), shipped as T0.2 in `9c2dc23`:
enumerate, protect, dry-run, delete in dependency order inside a transaction —
not a SQL script, because every FK is `NO ACTION`. The finding below is the
account of why it was needed, kept for that.

**Severity S2 · Gate `release`**

Nine tables reference `projects` — `agent_runs`, `discovery_blockers`,
`knowledge_area_links`, `knowledge_chunks`, `knowledge_provenance_links`,
`knowledge_relationships`, `messages`, `readiness_snapshots`, `sessions` — and
**every one is `NO ACTION`, not `CASCADE`**. `DELETE FROM projects` therefore
fails on a foreign-key violation.

~~There is no delete and no archive on any adapter.~~ Delete now exists.
`ProjectStatus.ARCHIVED` is still modelled in the domain with nothing setting
it — archive is genuinely absent, delete is not. So removing a project today means
hand-ordered SQL against production, which is exactly the direct-write path
ADR-0027 and F-011 exist to discourage.

Found while trying to clear 55 test projects holding 261 knowledge items and 720
messages. **Drives:** T0.2.

### F-022 — More capabilities are modelled and reachable by nothing

**Severity S2**

Found by walking the application services and asking whether anything can call
them. Beyond the four originally known — reembedding (F-007), modules (F-006),
assumptions (N45) and `enqueue_review` (EM-5). **Two of those four have since
gained callers:** `enqueue_review` is called by extraction (`82e9bf8`), and
assumption `origin` reached the HTTP schema (`80d2c40`).

- **Run interrupt and resume.** The domain models an interrupted run resuming
  and no caller can request either, so a stalled run is restarted by hand.
- **Review history** — modelled, served by nothing.
- **Setup writes** — `set_value`, `register_target`, `record_connection`,
  `resolve_target`. The reads are exposed; the writes are not.
- **The assumption lifecycle** — `reject` and `retire`, N45's remainder.
- **Embedding migration and chunking** — no CLI, no route, no tool; run from a
  Python shell.
- **`ModuleService.graph`** — the module-graph tool calls `list_modules` and
  `build_order`; nothing asks for the graph object.

**Eight outstanding**, not ten. The pattern matters more than any single entry:
a service method with passing unit tests looks healthy from below, and the
parity test checks that *declared* capabilities exist rather than that *existing*
behaviour is declared.

**The check this finding asked for could not have found it.** T0.6 proposed a
test walking the services asking *"is this declared on an adapter"* — that test
already existed (`test_no_unreachable_capability.py`) and passed throughout,
because these capabilities *are* declared; they are simply uncalled. The
replacement is field-level: `test_no_field_left_behind.py` (`4f39f6a`) asserts a
domain field reaching a response, and KAE-Artifacts has an equivalent for
generator reachability (`350a2c6`).

**Separately:** `reject_knowledge`, `correct_knowledge` and `supersede_knowledge`
on `MemoryService` are the older half of a pair. Adapters call `review_reject`
and its siblings, which record the reviewer and reason. Both paths work. A
second correct-looking path is how a caller bypasses an audit trail without
noticing; deleting them is its own change.

## S4 — Reasonable, unconfirmed — ~~open~~ **checked 2026-08-07**

Each claim's "confirm by" column has been run rather than argued, in
[`tests/integration/test_unproven_claims.py`](../tests/integration/test_unproven_claims.py).
**Four held. One did not.**

| # | Claim | Outcome |
|---|---|---|
| F-011 | Direct database writes bypass domain invariants | **Confirmed.** A `rejected → validated` transition the domain refuses is accepted by the table, and the resulting row is indistinguishable from honest confirmed knowledge downstream |
| F-012 | Projects are isolated on every read and write | **Confirmed**, including the case that would actually leak: two projects holding *identical* text, where a global collapse key would have merged them |
| F-013 | Dependency cycles are prevented | **Confirmed** for direct and three-hop cycles; the refusal leaves no partial edge behind, and a diamond is correctly still allowed |
| F-014 | Extraction always falls back to a fixture without a model | **Wrong — see below** |
| F-015 | Idempotency holds under concurrency | **Was already proven.** The register missed an existing test — see below |

**F-011 matters most, and it holds.** It is ADR-0027's central premise: going
around the application contracts really does lose the invariants, so the ADR is
describing a live gap rather than a theoretical one. The test is written to be
deleted if a future schema constraint closes it — a database that enforces the
transition beats a document asking people to.

### F-015 was already proven, and the register did not know

`tests/application/test_message_idempotency.py` has run eight concurrent
submissions of one idempotency key against the real engine since ADR-0018, and
asserts something **stricter** than this register asked for: exactly one
submission creates the record and the other seven resolve to a replay. Not "one
row survived" — one *writer* won and the rest were told so.

Nothing was added for F-015. A duplicate was written, found redundant on
reading the existing suite, and removed. Recorded because the failure here was
the register's, not the code's: an S4 entry was opened for a claim that had
executable proof, which is the same error as leaving a real gap unlisted, run
the other way.

### F-014 was not a finding, it was a misreading

The claim — "extraction *always falls back* to a fixture without a model" —
describes silent degradation, and that is not what the code does:

* the deterministic fixture is the **default**; Bedrock is opt-in through
  `KAE_EXTRACTION=bedrock`;
* an opt-in that cannot be satisfied **raises** (`default_extractor` refuses
  without a resolvable region) rather than quietly returning the fixture;
* the only component that degrades is the **reviewer**, and it labels itself in
  the run summary as `offline_by_kind_after_reviewer_error`.

So there was no silent fallback to disprove. There is a safe default and a loud
failure, which is the better behaviour and was simply never written down. The
original note was formed by reading `agents/deterministic.py` and inferring the
worker's policy from it. **This does not weaken F-008**, which says something
different and true: a run *can* complete on the fixture, and the run summary is
the only place that says so.

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
