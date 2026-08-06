# KAE-Memory readiness handoff

Status: **autonomous run complete**, 2026-08-05.
Register: [`NEXT_PHASE_CHECKLIST.md`](../09_development/NEXT_PHASE_CHECKLIST.md).
Suite at handoff: **1,659 passing**, mypy strict clean across 205 source files,
full run 57 seconds.

This closes the "Final Stages Part 2" directive. The run stopped where it was
told to: at work that needs manual product testing, KAE-Studio integration, or
live AWS/GitHub validation.

---

## 1. What was completed

Eleven targets and three proofs, in five milestones.

**Milestone A — the sparse-project gap.** The capability failure a manual test
found, closed end to end.

| Target | What it closed |
| --- | --- |
| N36 | A question can be responded to without being decided |
| N44 | Preliminary context composes what four subsystems each held |
| N20.2 | A deliverable reproduces the claim it made, not only the bytes |
| N43 | Observations classified by meaning, behind the existing protocol |
| *proof* | `test_sparse_project_journey.py` — the whole path, 22 assertions |

**Milestone B — configuration governance.** N7 and N8: a governed settings
system with a committed defaults file, a contract per setting, three-layer
precedence, and traceable effective values; plus a narrow message catalog for
what more than one adapter says.

**Milestone C — headless.** N9 surveyed, N10 superseded ADR-0009 with ADR-0026,
N11 removed `frontend/`. The one load-bearing thing in that directory — the
OpenAPI contract guard — moved out first and became stricter.

**Milestone D — preliminary setup.** N24–N28: setup vocabulary, a setup-question
lifecycle with its own model, typed project configuration, a publication target
registry, and a provider authorisation boundary. Migration `0020`.

**Milestone E — rendering and publication.** N21 renderer and verification, N29
attempt history, N30 local provider, N41 the eight sparse-project scenarios.
Migration `0021`.

## 2. What was verified, and how

Everything claimed above has a test that would fail if it stopped being true.
The verification worth naming is where it is *not* obvious:

**The model-backed path is proved by provenance, not by output.** The discovery
run exists, is identified by role rather than position, and names the stored
message it will read. Asserting anything about what a model produces would be
asserting its taste, and would fail on a better answer.

**Adapter parity is asserted at the seam.** A tool or route that is not in the
capability registry fails the suite, in both directions. That check is why the
twelve-capability gap N1 found cannot recur silently.

**The contract guard survived its own directory being deleted**, and is stricter
than what it replaced: whole-document comparison in the ordinary test command
rather than a CI job needing Node.

**Credential absence is asserted on serialised bodies**, not on objects. There
is no credential column anywhere in the schema; the test checks the text that
actually travels.

## 3. What was deliberately not built, and why

| Not built | Reason |
| --- | --- |
| Administrative and project-level settings override layers | Both need an authorisation model this repository does not have. Plumbing before authority is a system overridable by whoever reaches it first. |
| A settings UI, a policy framework, database-backed configuration | Ruled out by the focus file, and each would have grown past the slice that needed it. |
| Mechanical message centralisation | Ruled out. Four hundred keys nobody reads is worse than the duplication it removes; a test bounds the catalog at twenty. |
| Transfer of the six frontend panels to Studio | The focus file rules out copying the old UI wholesale. The *requirements* are mapped to the capabilities that already serve them. |
| A fourth `Provider` value | A target a project could choose and nothing could honour. |
| Configuration fields beyond the six that have readers | The "exists with no caller" pattern this repository shipped three times. |

## 4. Blocked on manual product testing

**Nothing is blocked on it, and one thing would benefit.** The Milestone A
journey is proved in-process against the deterministic path. Running the same
journey with a live extraction provider would show whether the N46 discovery
prompt reads an ordinary product sentence usefully — which is a question about
prompt quality, not about whether the path exists.

Suggested manual test: repeat the original *Manual Test — Sparse Inbox*
session. The four gaps it found are closed; what it would now measure is
whether the output is *good*, which is the next honest question.

## 5. Blocked on KAE-Studio integration

- **N33** — Studio setup and target-management contracts.
- **N39** — Studio generate-with-assumptions workflow.
- **Phase K** — Studio integration, which the directive scoped out of this run.
- **N23**'s last step — "open the result in Studio".

Studio at `e530753` has its own service interfaces and a mock layer, and does
**not** yet call this API. The backend side of every contract it needs exists
and is registered; what is missing is a client.

One thing to carry across, from ADR-0026: ADR-0009 warned that domain
vocabulary had drifted three times and that hand-written TypeScript interfaces
are never reconciled once written. That risk did not disappear with the
frontend — it crossed a repository boundary, where it is harder to see.
`specifications/openapi.json` is the mitigation, and Studio generating its
client from it rather than hand-writing interfaces is the recommendation.

## 6. Blocked on live AWS, GitHub, or S3 validation

- **N31 — S3 provider.** Its acceptance criteria are statements about what S3
  does, not about what our code sends. A stub proves the request shape and
  nothing else.
- **N32 — GitHub provider.** More sharply: "existing user edits are never
  silently overwritten" is a claim about behaviour under concurrent edits, and
  the failure it prevents — quietly destroying someone's commit — is exactly
  what a fake client cannot reproduce.
- **N22 — Remote MCP tenancy.** Implementable offline, not verifiable offline:
  the failure mode is a session outliving its authorisation, and a
  single-process test cannot produce one honestly.
- **N23 — End-to-end in deployment.** Every step but the last two is proved
  in-process.

**Everything around these is complete.** Registering an S3 or GitHub target
today succeeds, reports itself unavailable with a reason, and a publication
attempt against it produces a recorded attempt with `error_category: provider`
and "not implemented in this version". That is the honest state, and it is
reachable, inspectable, and tested.

## 7. Known defects and risks

**No known defects.** The suite is green and mypy is clean.

Risks worth carrying forward, in order of how likely they are to bite:

1. **The renderer produces thin documents.** `_markdown` renders a heading,
   counts, and a caveat — enough to prove determinism and hashing, not enough to
   be a useful deliverable. Making it richer is safe (the hash covers content,
   and a change to the renderer is visible in `renderer_version`), but it has
   not been done.
2. **`_state_for` in the setup service is a judgement.** Which state a project
   is "in" is derived from what exists, and reasonable people would order the
   branches differently. It is tested per state, not argued for.
3. **The local provider's collision behaviour is refuse-by-default.** Correct,
   and it means a re-publication of an unchanged deliverable fails rather than
   being a no-op. If that turns out to be annoying in practice, the fix is to
   compare hashes and treat an identical write as success — deliberately not
   done ahead of the need.
4. **`unknown_overrides` cannot distinguish a typo from an unmigrated knob.**
   It reports rather than refuses, and `_UNGOVERNED` is a hand-maintained list.
   It will go stale before anyone notices.
5. **Two pre-existing `E501` lint findings** in `capability_readiness_service.py`
   and `capabilities.py`. Untouched by this run; they predate it.

## 8. Decisions taken during this run

Each of these was a judgement call made without asking, and each is reversible.

**TOML rather than YAML for committed defaults.** The focus file's placement
table names YAML. `tomllib` is in the standard library and is read-only, which
is the exact shape of a file the application never writes. YAML would have added
a dependency to gain nothing.

**Deferred questions are held back from the asking list, not from the record.**
N36's acceptance had two halves pulling opposite ways — "a preserved answer" and
"not re-asked until a trigger fires". Both are implemented: the question stays
unresolved and is counted in `deferred`, and `include_deferred` is how a caller
sees it.

**`reproduces_uncertainty` is reported apart from `publication_eligible`.** A
record from before N20.2 can still be re-rendered byte for byte. Folding the new
check into eligibility would have withdrawn a real capability over a bookkeeping
change.

**The two classification integrity notes stayed two keys.** They looked like
drift and were not: a read cannot change an operational status and must not deny
having done so, because a caveat about an action nobody took reads as
reassurance about the wrong thing.

**`SetupService` holds four records rather than four services.** They are one
workflow — a question becomes a value, a value names a target, a target
publishes through a connection — and splitting them would have put the seams
where every caller has to know the order.

**`DeliverableService` constructs its own provisional context.** N38 shipped a
model no adapter built and every deliverable carried `qualification: null`. A
field each router had to remember would have failed the same way, silently.

## 9. Recommended next sequence

1. **Repeat the manual sparse-inbox test.** It is the cheapest way to find out
   whether the closed gaps produce a *good* result, and it needs nobody but you.
2. **N31 or N30-in-anger.** If a local target is enough for the first real
   deliverable, publish one and see what the document is missing. That answers
   risk 1 above with evidence rather than opinion.
3. **Studio's client, generated from `specifications/openapi.json`.** It
   unblocks N33, N39, and the last step of N23 at once, and it is the mitigation
   ADR-0009 asked for and ADR-0026 carried forward.
4. **N32 before N31, if publishing matters sooner than archiving.** GitHub is
   where a deliverable gets read; S3 is where it gets kept.
5. **N22 last.** Remote MCP is the only item here whose absence costs nothing
   today: stdio works, and the trust boundary it replaces is a process.

---

## What this run did not touch

Per the directive: no multi-agent platform, no CIE functionality in Memory, no
KAE-Studio implementation, no `crazy_factory` repair, no AWS provisioning, no
CockroachDB optimisation, no real external publication, and Phase K left
unimplemented. No test writes outside `tmp_path`. No live credential was used or
required at any point.
