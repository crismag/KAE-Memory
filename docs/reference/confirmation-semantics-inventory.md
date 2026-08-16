# Confirmation semantics inventory

Every place across the four repositories where a human clicking Confirm is
treated as the mechanism that makes acquired knowledge usable.

This exists because doc 17 of the ecosystem knowledge-synthesis package
(`development/knowledge-synthesis-review/17-KAE-MEMORY-EPISTEMIC-INGESTION-MODEL.md`)
asked for it before anything is changed:

> Implementation should first inventory where `confirmed/unconfirmed`,
> discovery-area assignment, open-question generation, and readiness thresholds
> currently imply human confirmation. Do not simply rename `unconfirmed` to
> `derived`. The behavioral assumptions throughout the lifecycle must be
> identified and corrected.

The rename warning is the reason this document is grouped by *assumption* and
not by file. A file-ordered list invites a search-and-replace. Each group below
names a distinct behaviour, and the corrections are different: one is a query
predicate, one is a prompt sentence, one is a published API contract, and one
is a number printed on a page.

**Scope.** KAE-Memory, KAE-Studio (`src/` and `backend/`), cris-cie-slim,
KAE-Artifacts. Read, not grepped: a token match that turns out to be a delete
dialog, an HTTP status, or a customer's order-confirmation email is listed
under [Excluded](#excluded-and-why) rather than silently dropped, because the
next person to run the same search needs to know it was already looked at.

**Paths** are relative to their own repository's root. Under a repository
subheading the prefix is dropped; where a group is not subdivided the repository
name leads the path.

**Owning rows** are from `EPI-*` in the ecosystem `ACTIVE_CHECKLIST.md`. This
document is `EPI-8` itself.

---

## What counts as an instance

Six behaviours, because they need six different corrections.

| Class | Assumption | Sites | Correction shape |
| --- | --- | --- | --- |
| **A** | `lifecycle == proposed` treated as "needs a human" | 32 | Delete the queue, or re-source it from attention |
| **B** | Readiness or coverage counting confirmed rows | 39 | Change what the calculator counts |
| **C** | An unclassified item presented as user work | 12 | Move the retry loop inside KAE |
| **D** | An extractor's unanswered question stored as a durable project unknown | 28 | Change extraction, then reconcile the backlog |
| **E** | A control whose only meaning is "a person clicked Confirm" | 12 | Repoint at the synthesized object |
| **F** | A contract or API requiring confirmation before something is usable | 28 | Renegotiate with the consumer |

151 sites, counted as entries below rather than as distinct files — a few
entries name a pair that only makes sense read together. Each entry is one
place a person edits.

**A caveat that changes how a third of this reads.** KAE-Memory already has the
three-layer model — `synthesized_objects`, `attention_items`, evidence roles
(`src/kae_memory/domain/synthesis.py`, ADR-0007). ADR-0007 rules that the
legacy confirm/reject path **stays** until synthesizers populate the attention
queue, and marks it transitional in the capability registry. Finding that path
is therefore not finding a defect. Those sites are collected under [Already
ruled on](#already-ruled-on-transitional-by-adr-0007) and are not counted in
the group totals.

---

## A — `lifecycle == proposed` treated as "needs a human"

Owned by **`EPI-1`** (epistemic class replaces the single unconfirmed state)
and **`EPI-7`** (the counts move to Diagnostics).

### KAE-Memory

**`src/kae_memory/application/review_service.py:228-241`** — the origin. Every
`PROPOSED` row in the project is collected and emitted as one
`UNCONFIRMED_KNOWLEDGE` finding at `MAJOR` severity, summarised
`"{n} candidate(s) await human review."` with the recommended action
`"Confirm or reject each candidate. Unconfirmed knowledge never completes an
area."` This is the sentence AWS Compute Lab rendered 803 times. Changing it
means deciding what, if anything, replaces the finding — every consumer below
reads from it.

**`src/kae_memory/application/review_service.py:49`** — `FindingKind.UNCONFIRMED_KNOWLEDGE`
is a first-class finding kind, so the assumption is in the enum and not only in
the branch that populates it. Removing the branch without removing the member
leaves a vocabulary that still says review is owed.

**`src/kae_memory/mcp/tools.py:428`** — `"awaiting_review": ids_for("unconfirmed_knowledge")`
inside `_knowledge_health`, which every `kae_get_project_briefing` response
carries. An agent reading a briefing is told how many rows are owed to a
person.

**`src/kae_memory/mcp/tools.py:360`** — `"awaiting_review": area.proposed_count`
in `_readiness_explanation`, per area. The proposed count is relabelled as a
review backlog at the point of display, which is why the number reads as work
rather than as evidence.

**`src/kae_memory/application/assembly_service.py:311-317`** — proposed
statements included in an assembly are placed in a section literally named
`area_key="unconfirmed"`, `name="Awaiting confirmation"`. A generated context
package therefore contains a heading that describes a queue, inside a document
whose purpose is to describe a project.

**`src/kae_memory/domain/lifecycle.py:34-45`** — the `RETRIEVABLE` docstring
states the premise outright: proposed knowledge is searchable "because hiding it
until confirmation would make review impossible — a reviewer cannot accept what
they cannot see." The behaviour is right and the stated reason is the
assumption. Under the target model the reason is that evidence is evidence,
which is a different justification for the same set.

**`src/kae_memory/mcp/tools.py:2409-2418`** — `kae_answer_clarification`'s
`next_steps` tell the caller "What it produces is proposed knowledge, not
confirmed knowledge. A person confirms it with `kae_confirm_knowledge`." A
person answering a question is told their answer created more review work.

### KAE-Artifacts

**`src/kae_artifacts/domain/artifacts.py:48-60`** — the `Readiness.NEEDS_REVIEW`
state, documented as "can be produced from material nobody has confirmed". Its
only two producers are the two confirmed-count rules in group B. The name
asserts the remedy is a human reading knowledge.

**`src/kae_artifacts/generation/plans.py:187-189`** — `Plan.needs_review`
exposes that subset as a queryable list, surfaced per entry over HTTP at
`src/kae_artifacts/api/app.py:675`. A review queue, derived from lifecycle,
served by a service that does not own the knowledge.

**`src/kae_artifacts/generation/generators.py:126-145`** — `requirements()`
splits the rendered document into `## Confirmed` ("Requirements a person has
agreed to") and `## Proposed` ("Extracted and awaiting review. **These are not
commitments.**"), with the empty state "Nothing is awaiting review." Every
unconfirmed requirement is committed to somebody's repository as a pending
human-review item.

**`src/kae_artifacts/generation/generators.py:334-355`** — `architecture_decisions()`
stamps `**Status:** accepted` only on `CONFIRMED` statements and
`**Status:** proposed — not yet a decision` on everything else. Confirmation is
what promotes an extracted decision into a decision. Pinned by
`tests/test_generators.py:98-105`.

**`src/kae_artifacts/generation/generators.py:45-64`** — `_bullets()`, used by
every generator: `CONFIRMED` prints bare, everything else carries
`**[proposed]**` or `**[assumed]**`. Same shape at `:309-318`. Weakest of the
set on its own — labelling provenance is defensible — and it matters because
`CONFIRMED` is the sole unmarked case, so no amount of evidence lets a
statement read as settled.

**`src/kae_artifacts/generation/generators.py:187-191`** — `development_context()`
renders assumptions under "Treated as true without confirmation. **Check these
before relying on them.**" — an instruction to the reader to go do confirmation
work.

### cris-cie-slim

**`src/cie_slim/kae/projection.py:64-67`** — `CONFIRMED = "validated"`, with the
comment "Everything else is a candidate of some description, and the difference
is the whole point of the review surface." The root definition: the entire
non-validated space exists to feed a review surface.

**`src/cie_slim/kae/projection.py:181-182`** — `Projection.proposed` is a
residual: anything whose lifecycle is not in `DECIDED`. Well-supported
synthesized knowledge and a one-off extraction artefact land in the same bucket.

**`src/cie_slim/kae/projection.py:202-205`** — `established()` returns only
confirmed text, documented "What a person has agreed to. What an interview must
not re-ask." This is the single most load-bearing line in CIE: a proposed row
that synthesis has settled is, by this contract, still fair to ask about again,
so the interview re-interrogates what KAE already knows.

**`src/cie_slim/kae/memory_client.py:102-111`** — `Statement.is_confirmed`
(`lifecycle == "validated"`), documented as a distinction that matters "least of
all to the agent deciding what to ask next" — i.e. explicitly an input to
next-question selection.

**`src/cie_slim/kae/conversation.py:420-435`, `:452-454`** — the turn brief
partitions statements into `ESTABLISHED — confirmed by a person. Never ask
about these again:` and `PROPOSED — derived, not yet confirmed. Useful context;
not agreed.`, and issues short tags `[p1]…[p15]` only to the proposed set so a
person's "yes" can flip them. The tag mechanism has no purpose other than
confirmation.

### KAE-Studio

Three chokepoints carry nearly all of Studio's instances, and they are worth
naming before the list because fixing them is most of the work:
`backend/src/kae_studio/projection.py:128` decides what becomes review work,
`src/services/live/liveServices.ts:670` turns proposed rows into findings, and
`src/lib/counts.ts:78-87` produces the numbers five surfaces render.

**`backend/src/kae_studio/projection.py:128`, `:344-346`** — the origin on this
side. `"proposed": [s for s in statements if s["lifecycle"] not in _DECIDED]`,
where `_DECIDED = {"validated", "rejected", "superseded", "retracted"}` carries
the comment *"Lifecycles a person has already ruled on… None of them belongs on
a review surface."* Membership is defined by whether a human ruled. Everything
below reads this key.

**`src/services/live/liveServices.ts:670-691`** — `findings: raw.proposed.map(...)`,
each given `kind: 'agent_proposal'` and detail text *"Derived from conversation
as X. **Proposed, not confirmed.**"* The Reviews page's entire data source is
the non-decided set.

**`src/services/live/liveServices.ts:853-869`** — `lifecycleStatus()` returns
`'proposed'` for any lifecycle this build does not recognise, commented *"claims
only that nobody has agreed to it"*. An unrecognised epistemic class introduced
by `EPI-1` will arrive as human work by default, which makes this line a
migration hazard rather than only a defect.

**`src/lib/counts.ts:78-79`, `:86`** — `awaitingDecision` is the length of that
findings array; `criticalAwaitingDecision` filters it to critical, and is the
only number the global nav badge shows; `requirementsAwaitingReview` counts
`status === 'proposed'` directly. The phrase "awaiting review" is applied to a
lifecycle value.

**`src/app/shell/AppShell.tsx:95`, `:99`** — the nav badge on `/reviews` is
`criticalAwaitingDecision`. A proposed row of kind `unknown` is the only thing
that can make it appear (see group D).

**`src/pages/dashboard/DashboardPage.tsx:189`, `:200-205`** — the "Needs you"
panel emits *"{n} proposed statement(s) awaiting your decision"* with the verb
"Review them".

**`src/pages/memory/MemoryPage.tsx:136`** — a headline stat tile labelled
`'Awaiting your decision'`.

**`src/app/registries/rooms.ts:226`** — the Reviews room's registered purpose is
*"Accept or refuse what KAE has proposed"*. The room's reason to exist is the
gesture.

**`src/pages/rooms/review/ReviewsRoom.tsx:79-84`, `:232-233`, `:244`, `:321-330`** —
the `agent_proposal` group described as *"Proposed until a person confirms it"*;
header badges `{critical} critical` and `{awaitingDecision} awaiting review`;
the body is a render of proposed rows; and the empty state — *"Nothing is
waiting on you here / No knowledge is currently proposed and awaiting review"* —
equates zero proposed rows with zero outstanding work.

**`src/pages/rooms/review/ProposedStatements.tsx`** (whole file; badge at
`:140`) — a paging and grouping component built specifically so 174 proposed
statements are tolerable to work through, each group headed
`plural(items.length, 'to decide')`. Its docstring at `:6-8` states the design
problem as *"350 buttons on one page"*. The clearest evidence in either
repository that the volume problem was met with better ergonomics rather than a
different model.

**`src/pages/rooms/definition/RequirementsSubflow.tsx:144`, `:490-497`,
`:565-583`, `:498-532`** — the row's next-action block exists only when
`status === 'proposed'`; the summary joins *"{n} confirmed"* and *"{n} awaiting
review"*; a per-category badge renders `{awaiting} need review` in attention
tone or `{items.length} settled` otherwise; and the page's primary navigation is
a status filter (`all | confirmed | proposed | rejected | superseded`) — the
lifecycle used as a workflow stage.

**`src/components/project/nextActionFloor.ts:40-47`** — whenever a project holds
any requirement, the recommended next action is `kind: 'review'`, *"Review what
KAE has derived"*, because *"Statements are waiting for a decision, and
readiness counts what you have confirmed."* This is the default recommendation
for essentially every project in existence.

**`src/components/project/statusVocabulary.tsx:13`, `:38-44`** — `proposed`
renders as a dashed circle in `pending` tone on every screen; `confirmed` gets
the green check. The visual system encodes proposed as not-yet.

**`src/domain/types.ts:12`** — `NodeStatus = 'proposed' | 'confirmed' |
'contested' | 'superseded' | 'rejected' | 'deferred'`. The UI's entire status
vocabulary is the confirmation lifecycle, so `EPI-1` cannot land in Studio
without a second vocabulary beside it.

---

## B — readiness or coverage counting confirmed rows

Owned by **`EPI-5`** (readiness from evidence strength and coherence). ADR-0003
still rules that readiness state is discrete and never a percentage, which
constrains what may replace this.

### KAE-Memory

**`src/kae_memory/domain/readiness.py:1-16`** — the module docstring is the
statement of the model: *"Readiness answers one question — does this project
hold enough confirmed knowledge to generate a useful blueprint?"* and
*"'Confirmed' is the existing `LifecycleState` `VALIDATED`."* Everything below
is an implementation of that sentence, so the sentence is what changes first.

**`src/kae_memory/domain/readiness.py:162`, `:175`** — `AreaDefinition.minimum_confirmed`
and the invariant that refuses a template where it is below 1: *"readiness area
must require at least one confirmed item"*. The schema forbids an area that
could be covered by evidence alone.

**`src/kae_memory/domain/readiness.py:212`, `:218`** — `Claim.minimum_confirmed`
and its matching invariant, added later for divided areas. The assumption was
reproduced when the model was extended, which is the usual sign that it lives in
the vocabulary rather than in one function.

**`src/kae_memory/application/readiness_service.py:93-106`** — `evaluate_area`.
`SUFFICIENT` requires `len(confirmed) >= area.minimum_confirmed`; proposed rows
can only ever reach `PARTIAL`. The docstring gives the reason, and it is a real
one: *"otherwise a project could raise its own readiness simply by generating
more candidates."* Any correction has to answer that objection, not ignore it —
which is why `EPI-5` depends on `EPI-1`. Evidence strength, not row count, is
what makes the objection go away.

**`src/kae_memory/application/readiness_service.py:142-150`** — `_divided_state`
establishes a claim only from the confirmed pool, so `problem_and_value` needs
two separately confirmed statements. The stricter rule shipped as template
version 2; it is stricter along the confirmed axis specifically.

**`src/kae_memory/application/readiness_service.py:186`** — `derive_status`
computes `touched` from `confirmed_count or proposed_count`. A project holding
only unclassified evidence reports `NOT_STARTED` after a full repository
ingest — the AWS Compute Lab symptom in its purest form, since area links are
what make evidence countable at all.

**`src/kae_memory/domain/readiness.py:289-291`** — `AreaResult` carries
`confirmed_count`, `proposed_count`, `minimum_confirmed`. This is the payload
shape every consumer below reads, including Studio, so it is the contract that
propagates the assumption outward.

**`src/kae_memory/application/blueprint_service.py:206`, `:248`** — the
blueprint is built from `list_for_project(project_id, VALIDATED)` and reports
`unassigned_confirmed_count`. A repository-backed project renders an empty
blueprint.

**`src/kae_memory/mcp/tools.py:1533-1536`** — `kae_get_readiness` publishes
`confirmed` and `proposed` per area to every agent. Also
`src/kae_memory/application/assembly_service.py:457-459`, which counts
`confirmed_count` per generated artifact.

**`src/kae_memory/application/capability_readiness_service.py:31`** — marginal,
and included because it is easy to miss. `SPARSE_KNOWLEDGE_THRESHOLD = 40` is
explicitly *not* a gate and a test enforces that. But the percentage it compares
against is the confirmed-count percentage, so a fully-ingested repository with
nothing confirmed still gets the heavier qualification wording. The gate was
removed; the input was not.

### cris-cie-slim

CIE carries a second, entirely independent readiness model. Most of it lives on
the legacy local path, which `src/cie_slim/kae/__init__.py:28-39` documents as
reachable only from `interview_replay.py` — but `session_model.py`,
`interview_artifacts.py` and `cli.py` **are** reachable and are the CLI product.

**`src/cie_slim/session_model.py:296-333`** — `Session.recompute()` derives
per-area `readiness[area] = {ready, covered, required}` and a global
`readiness["project_ready"]` from `answer.extracted_fields`, i.e. from fields a
human answered in an interview. Readiness is a count of human answers by
construction.

**`src/cie_slim/session_model.py:344-348`** — `advance_status()` moves
`in_progress → ready_for_generation` only when `project_ready` holds.

**`src/cie_slim/session_model.py:98`, `:101-108`** — `Assumption.status`
defaults to `"unconfirmed"`; `Decision` is documented as "A confirmed decision"
and carries `confirmed_at`. The data model has no representation for a settled
fact nobody confirmed.

**`src/cie_slim/kae/coverage.py:7-9`, `:73-75`, `:174`, `:230-235`** — the
module contract states *"Coverage is always a function of confirmed facts"*;
`is_ready_for_generation` defaults to `threshold = 1.0`, meaning every required
field; `overall_readiness` is the mean per-area coverage ratio; and the
rendering says "Readiness gate is not yet satisfied."

**`src/cie_slim/kae/conversation_engine.py:264-270`** — the interview
terminates only on `coverage.is_ready_for_generation()`.

**`src/cie_slim/interview.py:85-115`, `:216`** — the next question is the
highest-priority uncovered required field, and the loop exits
`ended_by = "readiness_gate"`. The interview's stopping condition *is* the
confirmed-coverage count.

**`src/cie_slim/scoring.py:60-70`, `:190-196`** — `QualityScore.readiness` and
`blocking_gaps`, surfaced at `cli.py:414` and `cli.py:492`.

**`src/cie_slim/kae/interview_quality.py:331-357`, `:431-434`** — an entire
scoring dimension (`readiness_progression`, weight 0.08) rewards growth in that
fraction and penalises its absence. Also
`src/cie_slim/kae/interview_metrics.py:152`, `:227-286`.

**`src/cie_slim/kae/conversation_summary.py:34-35`, `:123-126`** —
`READINESS_CHECKPOINTS = (0.5, 1.0)`: crossing a confirmed-coverage threshold
schedules a summary whose stated purpose is "confirmation opportunities, not
status reports". The count triggers the confirmation ritual.

### KAE-Artifacts

**`src/kae_artifacts/generation/profiles.py:88-94`** — `_needs_confirmed_knowledge`
returns `NEEDS_REVIEW` for `PROJECT_CONTEXT` when `source.confirmed` is empty.
A project whose every row is proposed is reported as needing review however much
it knows. Returns an empty reason string, so the caller sees the state with no
explanation.

**`src/kae_artifacts/generation/input.py:88-90`** — `GenerationInput.confirmed`,
the only aggregate over statements, filtering to `Confidence.CONFIRMED`. The
counting primitive that feeds the rule above.

**`src/kae_artifacts/generation/profiles.py:97-100`** — `_needs_architecture`
returns `NEEDS_REVIEW` unless a `decision`-kind statement or a statement tagged
`area == "interfaces_and_integrations"` exists. Coverage measured by
classification link: an un-tagged corpus reads as architecturally incomplete.
This is the closest thing in that repo to an `area_link` count.

### KAE-Studio

**`backend/src/kae_studio/projection.py:498-511`** — `_health.areas` maps
Memory's `confirmed_count → confirmed`, `proposed_count → proposed`, and
**`minimum_confirmed → required`**. Every coverage widget in the product is
rendered from that triple, so `EPI-5` changing what Memory counts changes what
Studio can display, and the field names go with it.

**`backend/src/kae_studio/projection.py:122`** — `"confirmed": [s for s in
statements if s["lifecycle"] == "validated"]`, with a comment at `:118-120`
calling the alternative *"the founding failure"*. That judgement is about
unconfirmed *readings* appearing as settled, which stays correct; what changes
under `EPI-1` is that `validated` stops being the only way in.

**`src/services/live/liveServices.ts:890-905`** — `coverageState()` maps an area
to `'thin'` when `area.proposed > 0` and `'missing'` otherwise. Proposed rows can
never make an area strong, whatever they say.

**`src/services/live/liveServices.ts:908-915`** — `coverageDetail()` renders
`"{confirmed} of {required} confirmed · {proposed} awaiting review"`, and
`"{confirmed} confirmed — enough for now"` once sufficient.

**`src/pages/rooms/interview/InterviewRoom.tsx:409-467`** — `CoverageSection`,
the Discovery progress panel, is one row per readiness area coloured by
`coverageState` and captioned by `coverageDetail`. This is the panel a user
watches during an interview.

**`src/pages/rooms/interview/InterviewRoom.tsx:593-603`** — the panel's own
glossary states the assumption in the product's voice: *"**Confirmed** — you
agreed to it. Only confirmed knowledge counts here"*, *"**Awaiting review** —
… It is a candidate until you accept it"*, *"**0 of 1 confirmed** — how many
agreed statements this area needs before it is defined enough to build from."*

**`src/pages/rooms/interview/InterviewRoom.tsx:289`, `:303`** — the "Current
understanding" panel filters stakeholders to `status === 'confirmed'` and
otherwise reads "None confirmed yet."

**`src/pages/rooms/definition/RequirementsSubflow.tsx:250-254`** — *"**Readiness
measures agreement, not effort.** It moves when you confirm things … A long
conversation with nothing confirmed reads 0%, and that is the number working
correctly."* Written deliberately, and it is the paragraph doc 17 is arguing
with.

**`src/components/project/stagePrerequisites.ts:30-63`** and
**`src/components/project/StageReadiness.tsx:48`, `:62`** — every downstream
stage's prerequisites are read off `projection.definition`, which is
confirmed-only, and rendered as *"{met} of {n} prerequisites met"* under
*"{stage} — not ready yet"*. `:43-45` reads *"No confirmed statement has been
classified as the problem yet."*

**`src/components/project/nextActionFloor.ts:27-32`** — `confirmed` is the size
of `projection.definition.*`, and the "nothing established yet" branch keys off
it.

**`src/pages/rooms/planning/FitFor.tsx:36-47`** — renders Memory's
`draftEligible` / `implementationEligible` booleans as *"Enough is established
to draft from"* and *"Safe to build from"*.

**`src/lib/counts.ts:85`** — `confirmedRequirements`, the numerator in every
"N requirements · M confirmed" summary.

**`backend/src/kae_studio/generation_input.py:165-172`** — `_summary()` emits
`"{total} statement(s), {confirmed} confirmed"` from the assembly manifest's
`confirmation_state`.

**`src/pages/rooms/review/QualityReview.tsx:199-201`** — `summarise()` renders
*"{n} areas need more confirmed evidence"* and *"{n} areas have no confirmed
knowledge"*.

**`src/pages/rooms/definition/PreliminaryContextPanel.tsx:82`** — the badge
*"Rests on unconfirmed material"*.

---

## C — an unclassified item presented as user work

Owned by **`EPI-3`** (unclassified is KAE's backlog) with **`EPI-7`** taking
the diagnostics.

**`src/kae_memory/application/review_service.py:243-256`** — every live item
carrying no area link becomes an `UNCLASSIFIED_KNOWLEDGE` finding at `MAJOR`,
recommending *"Assign each item to the area it serves."* This is the 692 items,
and the recommended action is the sentence doc 17 objects to by name: the user
as taxonomy clerk.

**`src/kae_memory/mcp/tools.py:429`** — `"unclassified": ids_for("unclassified_knowledge")`
in the briefing's knowledge-health block, so the count reaches every agent as
part of the project's description.

**`src/kae_memory/agents/prompts.py:47-51`** — `REVIEW_V1` tells the model
*"Readiness counts statements per area, so a statement you leave unclassified is
one the project cannot see it has."* True today, and it is the sentence that
makes classification a scoring act rather than an internal routing decision. It
changes with `EPI-5`, not before: while readiness counts links, the prompt is
accurate.

**`src/kae_artifacts/generation/generators.py:379-394`** — `module_plan()`
groups by `statement.area`, silently drops statements with none, and when no
statement carries an area emits *"no decomposition can be derived. **This needs
a person**"*. Unclassified evidence is converted, verbatim, into assigned human
work. Related silent drop at
`src/kae_artifacts/integration/kae_memory.py:81`, where an item with no `kind`
becomes `"unknown"`, matching no generator's `by_kind()` call — it disappears
from every artifact without being counted anywhere.

**`src/cie_slim/kae/gap_detector.py:147-165`, `:190-195`** — every discovery
field absent from `state.coverage` is mechanically turned into a `Gap` and
rendered as *"**N required field(s) have not been covered.** These must be
resolved before the session is ready for generation."* Absence of a keyword
match is the classifier, and its misses become the user's list.

**`src/cie_slim/session_model.py:245-251`** with **`src/cie_slim/cli.py:920-924`** —
`open_gaps()` / `blocking_gaps()` printed as a to-do list. These are opened
automatically at `src/cie_slim/interview.py:202-211` when a question could not
be asked without duplicating — engine bookkeeping surfacing as user work.

**`src/cie_slim/kae/projection.py:262-294`** — every Memory finding naming an
area, plus every undecided `unknown`, becomes a `Subject` ("Something a question
could usefully be about"). Nothing distinguishes a subject a person must handle
from one synthesis could resolve.

**`src/cie_slim/kae/domain_interview_strategy.py:90-107`** — domain-pack
patterns and risks not *mentioned in the transcript* become `priority_topics`
and `risk_probes`. Non-mention is treated as unresolved user work.

**`KAE-Studio/backend/src/kae_studio/projection.py:217-261`** — `_review()`
passes Memory's findings through verbatim, `unclassified_knowledge` among them,
onto the page whose lead (`src/pages/rooms/review/ReviewsRoom.tsx:229`) reads
"what is waiting on a person". Rendered at
`src/pages/rooms/review/QualityReview.tsx:52-113`, each with its
`recommendedAction`. Studio adds no assumption of its own here — it faithfully
displays Memory's — which is why `EPI-3` fixes this at the source and Studio
inherits the fix.

**`KAE-Studio/src/pages/rooms/interview/ClassificationState.tsx:49-74`** with
**`neverClassified.ts:18-20`** — when `classification?.engine === null` the room
renders *"Nothing has classified this project yet"* and a **"Classify what the
project holds"** button a person must press. The docstring at `:20-27` records
that automation was deliberately not done, so this is a known deferral rather
than an oversight — but the deferred work is billed to the user.

**`KAE-Studio/backend/src/kae_studio/api.py:1089-1146`** — `POST /api/projects/{id}/classify`
is operator-authenticated and cost-bearing, *"Explicit rather than automatic,
and that is a deferral not a judgement."* The honesty is welcome and the
endpoint is still the thing that makes "unclassified" a user task.
`src/hooks/useProject.ts:110-130` is the mutation behind the button.

---

## D — an extractor's unanswered question stored as a durable project unknown

Owned by **`EPI-4`**, which the checklist says to build with `SYN-3c` — same
reconciliation, wider input.

**`src/kae_memory/agents/prompts.py:17-18`** (`REQUIREMENTS_V1`), **`:94-95`**
(`DISCOVERY_V1`), **`:31`** (`ARCHITECTURE_V1`) — the root cause, and it is
three sentences of English, not a data structure: *"if it raises a question it
does not answer, record that as an unknown"*. Every chunk that lacks global
context is instructed to mint a durable `unknown` row. 103 questions from one
repository is this instruction working exactly as written. Correcting it is a
new prompt version (never an edit — ADR-0006), plus reconciliation for the rows
already written.

**`src/kae_memory/agents/deterministic.py:35`** — the offline extractor does the
same lexically, mapping `"tbd"`, `"unclear"`, `"not sure"`, `"?"` to
`KnowledgeKind.UNKNOWN`. A deployment with no model still accumulates unknowns.

**`src/kae_memory/application/review_service.py:258-271`** — every live
`UNKNOWN` row becomes one `OPEN_QUESTION` finding at `MAJOR`, recommending
*"Answer each question and record the answer, or accept it as an assumption."*

**`src/kae_memory/application/clarification_service.py:673`** — `_ASKABLE`
includes `"open_question"`, so each such finding is materialised as a durable
`MessageType.QUESTION` put to a person by `open_questions()`. This is where an
extraction artefact becomes a record in someone's conversation. Note the same
constant already *excludes* `unconfirmed_knowledge` and `unclassified_knowledge`
as "queues of work" — the judgement exists, and `open_question` was not
subjected to it.

**`src/kae_memory/application/blueprint_service.py:231-236`** — every live
`UNKNOWN` row is rendered into `Blueprint.open_questions`, which flows to
`kae_get_project_briefing` and to `GET /blueprint.md`.

**`src/kae_memory/mcp/tools.py:1463`** — `kae_get_open_decisions` returns every
`UNKNOWN` row with `"source": "open_knowledge"` alongside genuine findings, and
the guidance tells the agent *"Do not choose an answer on the project's behalf;
if one blocks the work, report it and stop."* An extractor's local ambiguity can
therefore halt an agent's work.

**`src/cie_slim/kae/memory_client.py:188-200`** — `unknowns()` reads those rows
and documents them as *"Worth more to an interview than most gaps… a specific
question the extraction already found worth asking and could not answer."* The
defect stated as a design virtue, and the reason CIE amplifies rather than
absorbs it.

**`src/cie_slim/kae/projection.py:73`, `:193-194`, `:276-294`** — each undecided
`unknown` becomes a durable addressable `Subject` keyed on the knowledge id, and
`:280-282` removes it only when a person rules on it. Combined with
`src/cie_slim/kae/conversation.py:415-419`, where confirming an unknown means
"yes, this is genuinely undetermined", the only available human act makes the
unknown *more* durable and never resolves it.

**`src/cie_slim/kae/conversation.py:276-280`** — the system prompt forbids the
model from answering an open question on the project's behalf, even where the
evidence would support an answer. Prompt-level enforcement of the assumption.

**`src/cie_slim/question_backlog.py:1-32`, `:66-78`** with
**`src/cie_slim/workflow_runner.py:386-392`** — facts a checkpoint could not
establish are mapped through `GAP_QUESTIONS` into prose questions, accumulated
across a run, and persisted to `open_questions.md` and `checkpoints.json`.

**`prompts/gap_reviewer.md:16`, `:23-27`** with
**`templates/OpenQuestions.template.md:30-33`** — the gap reviewer is instructed
to find *"Assumptions that were never confirmed by the user"* and emit them with
stable `Q-n` ids into `## Assumptions To Confirm`. Lack of confirmation alone
qualifies an item as a tracked project question. Also
`src/cie_slim/model_client.py:98-116`.

**`src/kae_artifacts/generation/input.py:47-59`** with
**`src/kae_artifacts/generation/generators.py:67-74`**, fed from
**`src/kae_artifacts/integration/kae_memory.py:153`** — Memory's
`open_questions[]` is rendered verbatim into **twelve of thirteen** generated
documents, under headings that assign the work: *"## Decide before building"*
(`:193-195`), *"## Blocked on a decision"* (`:234-236`), *"## Decisions still
outstanding"* (`:364-366`), *"Do not decide these on the project's behalf …
**stop and ask**"* (`:212-217`). No filtering, and no provenance distinction
between a question a person asked and one an extractor could not resolve.

**`src/kae_artifacts/domain/identity.py:68`, `:83`** via
**`src/kae_artifacts/application/services.py:77`** — `open_questions` is folded
into the input digest, so one new extractor question invalidates every
outstanding plan. Extractor uncertainty is a first-class change to what the
project knows.

**`KAE-Studio/src/services/live/liveServices.ts:680`** — the amplifier:
`severity: (s.kind === 'unknown' ? 'critical' : 'minor')`. An extractor saying
"I could not determine this from this chunk" is graded **critical**, which is
the only severity the nav attention badge counts (group A). One line converts
extraction uncertainty into a red number on every page of the application.

**`KAE-Studio/src/services/live/liveServices.ts:1038-1047`** with
**`src/lib/counts.ts:72`, `:87`** — `CATEGORY_FOR_KIND` maps Memory kind
`unknown` → category `open_question`, and `counts.openQuestions` counts that
category. The single path from an extractor's local gap to a durable
project-level open-question figure.

**`KAE-Studio/src/domain/types.ts:202`** — `open_question` is a
`RequirementCategory`, sitting beside functional and security. An extraction
artefact is a kind of requirement in the type system.

**`KAE-Studio/src/pages/rooms/definition/RequirementsSubflow.tsx:145-150`** —
for `category === 'open_question'` the row reads *"Answer this, or record it as
an assumption — it is a gap KAE found."*

**`KAE-Studio/backend/src/kae_studio/projection.py:515-537`** with
**`src/services/live/liveServices.ts:651-663`** — `_questions()` turns Memory's
clarification *candidates* into `openQuestions` entries carrying
`asked = bool(q.get("asked_id"))`, and the client defaults `asked: q.asked ?? true`.
Candidates nobody was ever shown are carried as decisions a person owes.
`src/domain/types.ts:296-310` documents `asked: false` as *"a candidate …
never asked"* and keeps it in the list regardless.

**`KAE-Studio/src/pages/rooms/interview/InterviewRoom.tsx:470-518`, `:701-713`** —
`OpenDecisionRow` and the "Open decisions / {N} open" panel render those
candidates, and `:497-507` renders never-asked ones as "Not asked yet" rather
than omitting them. Also `src/pages/dashboard/DashboardPage.tsx:206-211`
("{n} open decision(s)" → "Decide them") and
`src/services/live/liveServices.ts:1226-1244`, which reports
`questionsAsked / questionsAnswered / questionsDeferred` over the same set.

**`KAE-Studio/src/pages/rooms/definition/PreliminaryContextPanel.tsx:134-166`,
`:194-212`** — material and deferrable unknowns as a durable severity-ranked
list, each marked "Not yet asked" or "Asked · {disposition}".

**`KAE-Studio/backend/src/kae_studio/generation_input.py:131-139`** —
`open_questions` built from the assembly manifest's `unresolved_critical_gaps`,
each with `question` / `area` / `blocks`, written into the generated development
package. This is where a Memory gap becomes a durable unknown inside somebody
else's repository — the same handoff KAE-Artifacts performs in twelve documents.

---

## E — a control whose only meaning is "a person clicked Confirm"

Owned by **`EPI-6`** (no adapter reaches a review queue without reconciliation)
and, for Studio's surfaces, **`EPI-7`**.

KAE-Memory has no UI; it exposes the controls the UIs bind to, and ADR-0007
rules those transitional — see [Already ruled on](#already-ruled-on-transitional-by-adr-0007).
What follows is everything outside that ruling.

**`src/cie_slim/cli.py:559-569`** — `_interactive_gap_prompt()` blocks the
workflow on `Continue past this gap? [y/N]:`, with `EOFError → False`, so a
non-interactive run is blocked by default. A keystroke is the only thing that
lets acquisition proceed.

**`src/cie_slim/cli.py:418-437`, `:1045`** — strict generation exits 1 while
`score.blocking_gaps` is non-empty. The only release is a human passing
`--allow-assumptions`, which then writes one `Assumption` row per gap with the
reason "Generation proceeded under --allow-assumptions." The flag's entire
semantic content is "a person accepted this".

**`src/cie_slim/kae/knowledge_model.py:218-229`** — `promote_to_solution_mode()`
is documented as *"the only sanctioned way to unlock artifact generation. It
must be called by the user-facing layer after explicit user confirmation —
never automatically by the KAE engine."* Echoed at
`src/cie_slim/kae/conversation_engine.py:451-460` and
`src/cie_slim/kae/__init__.py:48-53`.

**`src/cie_slim/kae/conversation.py:207-217`, `:355-363`** — `Move.provenance`
exists, per its own docstring, so *"a person's 'yes, that holds' become a
recorded fact rather than a sentence"*. A purpose-built channel whose only
consumer is a confirmation act on proposed rows.

**`src/cie_slim/kae/skills.py:171-178`** — the `reflect_for_confirmation` skill
fires when *"enough has accumulated that a compact reading is worth confirming
before going further"*. Accumulation of proposed material is the trigger for
asking a person to confirm.

### KAE-Studio

Studio holds the actual buttons. These are the controls ADR-0007 keeps as
transitional on Memory's side — but Studio is where they are *presented as the
project's primary work*, and that presentation is not what ADR-0007 preserved.

**`src/pages/rooms/review/ReviewsRoom.tsx:155-184`** — `FindingCard` renders
Confirm (`confirm.mutate(finding.id)`) and Reject (`reject.mutate({findingId,
reason, expectedVersion})`) on every `agent_proposal` finding.

**`src/pages/rooms/definition/RequirementsSubflow.tsx:160-187`** — the same pair
inline on each proposed requirement row.

**`src/pages/rooms/interview/InterviewRoom.tsx:111-157`, `:225-227`** —
`ConfirmReading`: a "Yes — confirm {N}" button that on success renders
*"Confirmed — N statements now part of what this project holds."* Mounted
whenever a turn carries `message.provenance`, so every reflective turn in an
interview becomes a confirmation prompt.

**`src/hooks/useProject.ts:88-108`** — `useConfirmReading`, whose docstring
names the defect it closes: *"Discovery Progress stayed at '0 of 1
confirmed'."* It invalidates the projection so readiness moves on confirmation
— the mechanical link between the button and the number in group B. Also
`:223-247` (`useConfirmFinding` / `useRejectFinding`).

**`src/domain/types.ts:224-236`** — `Requirement.version` exists solely so a
rejection can be issued against the wording a person actually read, *"without it
this page could only ever send a person somewhere else to decide"*. A field whose
whole purpose is the gesture.

**`backend/src/kae_studio/api.py:1157-1203`** — `POST /api/projects/{id}/recommendations`:
*"**The click is the decision** — nothing asks afterwards whether they meant
it"*, writing `kae_recommended_accepted` or `unresolved_alternative` from which
button was pressed.

**`src/pages/rooms/architecture/ModulesSubflow.tsx:152-200`, `:230-300`,
`:356-400`** — `CurationBar` offers accept / rename / split / merge / reject
over modules whose `proposalState` is `proposed`. Live only against the mock:
`recordModuleDecision` raises `CapabilityUnavailable` on the live adapter
(`src/services/live/liveServices.ts:1246-1251`), so this is a designed surface
with no backend, and correcting it is cheaper now than after it acquires one.

---

## F — a contract or API requiring confirmation before something is usable

Owned by **`EPI-1`** for the meaning and **`EPI-2`** (contextual source
authority) for what replaces it. These are the entries with consumers outside
the repository that holds them, so each needs a negotiated change rather than an
edit.

**`src/kae_memory/domain/lifecycle.py:47-53`** — `AUTHORITATIVE = frozenset({VALIDATED})`,
documented *"What may be treated as established fact… a caller building a
blueprint must not silently include statements nobody confirmed."* One line, and
it is the definition the rest of this section implements. Under `EPI-1` it
becomes a function of epistemic class, provenance and source authority, not a
one-member set.

**`src/kae_memory/application/memory_service.py:1387-1390`** —
`retrieve_knowledge` defaults `lifecycle=VALIDATED`. Every caller that does not
name a lifecycle silently gets confirmed rows only. The default is the contract.

**`src/kae_memory/agents/roles.py:140-179`** and
**`src/kae_memory/worker/execution.py:169-185`** — the architecture agent
consumes `VALIDATED` only, and a project with nothing confirmed completes with
`{"items_written": 0, "reason": "no_confirmed_knowledge"}`. A fully-ingested
repository produces no architecture decisions. Both paths encode it separately,
so both change.

**`src/kae_memory/agents/prompts.py:25-32`** — `ARCHITECTURE_V1`: *"The confirmed
requirements are your only authoritative input."* The restriction is in the
prompt as well as the query, which is the pattern throughout: correcting the
predicate without the prompt leaves a model that declines to use what it is
given.

**`src/kae_memory/application/assembly_service.py:286-289`** — every statement
drawn from the blueprint is stamped `inclusion_class=CONFIRMED`,
`lifecycle=VALIDATED`. Proposed statements enter only when `include_proposed` is
set, and then only in the `unconfirmed` section (group A).

**`src/kae_memory/application/assembly_service.py:330-343`** — the warnings a
caller sees: *"No confirmed knowledge for {areas}. This assembly does not cover
them."* and *"Nothing was assembled: no confirmed knowledge serves this purpose
yet."* This is what a repository-backed project gets back today.

**`src/kae_memory/mcp/tools.py:443-445`** — `kae_get_project_briefing`'s own
contract: *"Everything here is counted or computed from confirmed knowledge."*
Published to every agent that reads the tool description.

**`docs/concepts/knowledge-lifecycle.md:107-117`** — the published statement of
the rule: *"Context assembly draws on confirmed knowledge only — an unconfirmed
candidate never reaches a generated document"* and *"An area reaches
`sufficient` only on confirmed items meeting its minimum."* Correct as
documentation of today. It is the paragraph that has to be rewritten last, once
the behaviour it describes has changed.

**`src/cie_slim/kae/knowledge_model.py:8-14`, `:118-126`** — the module contract:
*"Every field value is sourced from a confirmed user statement, not inferred."*
`mode` is *"the only field that gates solution generation"*.

**`src/cie_slim/kae/conversation_engine.py:523-540`** — `assert_knowledge_mode()`
raises `RuntimeError` at the boundary of any code-, schema- or contract-producing
function while the session is in acquisition mode.

**`src/cie_slim/interview_artifacts.py:283-324`** — `NOT_READY_BANNER`:
*"⚠️ **NOT IMPLEMENTATION-READY** … Treat the content below as provisional
context only — **do not build from it** until the gaps in `quality_report.md`
are resolved."* Prepended to `ImplementationContext.md` and `CopilotPrompt.md`
whenever `readiness["project_ready"]` is false — that is, whenever the
confirmed-field count is short. **`src/cie_slim/output_audit.py:81-90`** makes
it an enforced gate: the package audit *fails* if the watermark is missing while
readiness is blocked.

**`src/cie_slim/quality_reports.py:66-77`, `:104-111`** — a `## Generation gate`
section reading *"**Blocked.** … Strict generation is refused until these are
covered"*, and *"Assumptions are not confirmed answers. **Each should be
confirmed with the user before it is relied on.**"*

**`src/cie_slim/context_builder.py:96-103`, `:121-133`, `:179`** — *"Content
marked **Assumption** must be confirmed before use"*; each section labelled
`**Confirmed.**` or `Not established.` with no synthesized middle; every
component checklist ending `- [ ] No assumption was implemented without
confirmation.`

**`src/cie_slim/kae/conversation.py:273-275`** — the system prompt: *"**State
only what ESTABLISHED supports.** Anything under PROPOSED or OPEN QUESTIONS is
not settled, and summarising it as though it were tells the person their project
holds something it does not."* The prompt-level statement of the whole
assumption, and the reason the interviewer cannot report what KAE has learned.

**`src/kae_artifacts/integration/kae_memory.py:40-49`, `:87-94`** — the
`_LIFECYCLE` map is the contract between the two services:
`confirmed`/`accepted`/`settled` → `CONFIRMED`, everything else → `PROPOSED`.
**It contains a live defect independent of this migration**: ADR-0007's
vocabulary is `proposed → validated/rejected/superseded`, and `"validated"` is
not a key — it falls through the `.get(..., PROPOSED)` default at line 91. Every
validated Memory row currently renders as `**[proposed]**` and, in
`architecture_decisions`, as "not yet a decision". `rejected` and `superseded`
map to `PROPOSED` too, so ruled-out knowledge is published as merely
unconfirmed.

**`src/kae_artifacts/generation/profiles.py:131`, `:145`** — plan-entry `inputs`
prose: `("Confirmed project knowledge",)`, `("Confirmed requirements", "Open
questions")`, returned by `GET /v1/profiles` and in every plan body. The
published statement of what an artifact requires.

**`src/kae_artifacts/api/app.py:97`** — `StatementIn.confidence` defaults to
`Confidence.PROPOSED`. A caller omitting the field gets a package in which
nothing reads as fact.

**`src/kae_artifacts/application/services.py:72-79`, `:194-201`** with
**`src/kae_artifacts/domain/identity.py:63-86`** — `digest_of` folds
`confidence.value` into the input digest, and `generate_from_plan` refuses with
"this plan was proposed against a different input" when it moves. Confirming one
item invalidates every outstanding plan.

### KAE-Studio

**`backend/src/kae_studio/definition.py:144`, `:180-186`** — `if
statement.get("lifecycle") != "validated": continue`. The Definition block —
the product's answer to *"what does my project hold"* — is composable only from
confirmed rows, and `_joined()` applies the same filter to problem and value.
With `stagePrerequisites.ts` reading off it (group B), this one predicate gates
every downstream stage in the UI.

**`backend/src/kae_studio/memory_client.py:417-433`** — `context(...,
include_proposed: bool = False)`. Generation context excludes proposed
statements by default, because *"a package generated from them by default would
turn 'somebody said this once' into a document an implementer follows."* The
concern is real and survives `EPI-1`; what changes is that it should key on
epistemic class and evidence strength rather than on whether a person clicked.

**`backend/src/kae_studio/generation_input.py:46-51`, `:101`, `:122`** —
`_CONFIDENCE` maps `validated → confirmed` and everything else, including
anything unrecognised, to `proposed`. Memory's validated lifecycle is the only
route to `confirmed` confidence in a generated package, and this is the mirror
of the same defect in `KAE-Artifacts/.../integration/kae_memory.py:40-49`.

**`src/pages/rooms/definition/RequirementsSubflow.tsx:234-238`** — the product
contract in the product's own words: *"Everything derived from your conversation
arrives *proposed*. **It becomes part of what the project holds only when you
confirm it**, on the Reviews page."*

**`src/services/interfaces.ts:92-101`, `:136-146`, `:421-424`** — the service
ports: `ProjectMemoryClient.confirmFinding` / `rejectFinding` as first-class
methods; `InterviewProvider.confirmReading` documented *"**The click is the
confirmation** … everything it was built from becomes confirmed knowledge"*; and
the source-ingestion contract *"the text becomes durable evidence, extraction
proposes candidates, a person confirms."* That last sentence is precisely the
pipeline doc 17 replaces, written as an interface comment.

**`src/services/live/liveServices.ts:1277-1291`, `:1380-1387`** — the client is
typed against `POST /knowledge/{id}/confirm`, `.../reject`, and
`POST /knowledge/confirm` for sets.

**`backend/src/kae_studio/memory_client.py:527-532`, `:571-584`, `:586-615`** —
`confirm_knowledge`, `confirm_knowledge_set` (all-or-nothing), and
`reject_knowledge` with `expected_version`, each taking a named human reviewer.

**`backend/src/kae_studio/api.py:1148-1155`, `:1205-1230`, `:1232-1252`,
`:240-256`** — the HTTP surface. Confirm requires an authenticated operator as
reviewer; set-confirm is documented *"**The UI action is the confirmation.**"*;
reject 422s without a reason and an `expected_version >= 1` because *"a
rejection must name the version the reviewer read"*; and `ConfirmSetIn` caps
`knowledge_ids` at 200 because a larger request *"is a caller confirming a
project by accident."* That cap is the clearest evidence in the codebase that
volume was already understood as a hazard, and was met with a limit rather than
a different model.

---

## Already ruled on: transitional by ADR-0007

These match the search and are **not** defects. ADR-0007 keeps the legacy
confirm path until synthesizers populate the attention queue, and each site
already carries the label. Listed so a later pass does not re-find them and
file them as work.

- `src/kae_memory/capabilities.py:119-160` — `knowledge.confirm`,
  `knowledge.confirm_set` and `knowledge.reject` are declared
  *"Transitional: relay a person's decision to accept an extracted candidate
  row. Not the attention queue (ADR-0007)."* The registry is generated into
  `docs/reference/capability-matrix.md`, so the disclaimer is published.
- `src/kae_memory/application/memory_service.py:1145-1163`, `:1165-1224`,
  `:1226-1273` — `confirm_knowledge`, `confirm_knowledge_set`,
  `reject_knowledge`, each documented as confirming an extracted row and not the
  attention queue.
- `src/kae_memory/mcp/tools.py:1957`, `:2034` — `kae_confirm_knowledge` and
  `kae_reject_knowledge`, which require a named `reviewer` precisely so an agent
  cannot manufacture a human decision.
- `src/kae_memory/domain/synthesis.py:1-12`, `:59-72` — the three-layer
  vocabulary, and the instruction not to reuse `LifecycleState` as either
  synthesized-object approval or attention.
- `src/kae_memory/api/routers/synthesis.py:1-8`, `:181-240` and
  `src/kae_memory/application/synthesis_service.py:306-380` — the attention
  queue exists over HTTP, with `put_attention` documented *"Extraction does not
  call this. A later attention engine does."* The surface is built and unfed,
  which is what `EPI-6` and Phase 4 are for.

The distinction that matters for planning: **the confirm path is a deliberate
keep; the readiness path, the unknown pipeline, and the finding generation are
not.** Nothing in ADR-0007 sanctions `minimum_confirmed`, `UNCONFIRMED_KNOWLEDGE`
findings, or `open_question` materialisation.

---

## Excluded, and why

Matches that do not encode the assumption. Recorded so the same search does not
have to be repeated.

**Deliberate counter-examples in KAE-Memory — protect these.** They are the
shape the rest should move toward.

- `src/kae_memory/domain/maturity.py:1-52` — maturity is unordered by
  construction, with `MATURITY_IS_UNORDERED` and a test existing purely so that
  anyone about to add a comparison finds the reasoning first. The docstring
  names the failure it avoids: *"That is the readiness gate again, wearing a
  third set of words."*
- `src/kae_memory/domain/generation.py:63-121`, `:153-177` — every generation
  mode's default inclusion set contains `PROPOSED`, and an import-time guard
  refuses a mode that includes nothing. Qualification replaces refusal:
  `qualifications()` returns the sentences that keep an unconfirmed package
  honest instead of blocking it.
- `src/kae_memory/application/capability_readiness_service.py:1-12` — *"knowledge
  quality never appears as a block"*, enforced by test. Its input is still the
  confirmed-count percentage, which is why the threshold appears in group B, but
  the structure is right.
- `src/kae_memory/application/preliminary_context_service.py:217-220` —
  unconfirmed candidates are *always* included, explicitly to serve a project
  where nobody has confirmed anything.
- `src/kae_memory/application/clarification_service.py:673-680` — `_ASKABLE`
  already excludes `unconfirmed_knowledge` and `unclassified_knowledge` as
  *"queues of work"*. Half of `EPI-3` is already ruled, in one constant.
- `src/kae_memory/domain/lifecycle.py:34-45` — `RETRIEVABLE` includes
  `PROPOSED`, so search is not confirmation-gated. Only the stated reason
  appears in group A.
- `src/cie_slim/kae/conversation.py:220-231`, `:365-370`, `:586-604` —
  `next_action` is reasoned by the model per turn and explicitly is not a
  ranking, and `ACTION_KINDS` includes `review/decide/configure/generate` so it
  cannot collapse into "answer the interviewer". **Nothing in CIE computes
  `next_action` from a proposed-row count**, which is the specific thing
  ADR-0007 warned about.
- `src/cie_slim/kae/memory_client.py:211-234` — `gaps()` deliberately reads
  `GET /clarifications/candidates` rather than `POST /clarifications`, so
  reading gaps does not materialise questions. A prior fix for a close relative
  of `EPI-4`.
- `src/cie_slim/kae/conversation.py:149-172`, `:332-341` — `Conclusion` grading
  exists to stop *"treating every inference as needing agreement… how a project
  accumulates eighty-one things to review and settles none of them."* The
  correct model, already present in the conversational layer and with no
  counterpart in the readiness layer.
- `src/cie_slim/checkpoint_engine.py:98` — `integrations_known_or_marked_unknown`
  accepts "marked unknown" as satisfying coverage. The desired shape.
- `KAE-Artifacts/README.md:208`, `docs/context/PROJECT_CONTEXT.md:27,39` —
  explicitly disclaims owning KAE readiness (*"it does not invent KAE
  readiness"*). The correct boundary posture; keep the wording.
- `KAE-Studio/backend/src/kae_studio/api.py:240-248` — the 200-id cap on
  `ConfirmSetIn`, guarding against *"the 'inference silently becomes
  user-confirmed' failure the directive forbids"*. Listed in group F because it
  is part of the confirm contract, and noted here because the instinct behind it
  is the right one and should survive whatever replaces the endpoint.

**Different concern, same word.**

- `src/kae_memory/domain/observation.py:260-278` — `OperationalState.PROPOSED /
  ACTIVE`, and `src/kae_memory/api/schemas.py:1564`. This is a person settling a
  *reported work-status record* ("the deploy is done"), not extracted knowledge.
  `AUTO_CONFIRMING` at `:250-257` even allows execution evidence to settle one
  without a person, which is the target model in miniature.
- `src/kae_memory/domain/modules.py:51` — `ModuleState.PROPOSED`. Defining a
  module is a design act; `src/kae_memory/mcp/tools.py:791-793` explains that an
  agent confirming its own module proposals is the promotion FR-005 forbids.
- `src/kae_memory/domain/assumptions.py:62` — assumption acceptance. Doc 17
  keeps this: an assumption is *supposed* to require someone to take
  responsibility.
- `src/kae_memory/domain/synthesis.py:68` — `SynthesizedLifecycle.PROPOSED_CHANGE`
  is the new model's own vocabulary.
- `KAE-Artifacts/src/kae_artifacts/domain/approval.py` (whole file),
  `application/services.py:350-374`, `api/app.py:589-596`,
  `domain/publication.py:42`, `docs/decisions/ADR-0002-approval-is-evidence-not-a-flag.md` —
  a person authorising a **write to somebody else's repository**, bound to a
  preview checksum. Consent to mutate a destination, not a claim about truth.
- `KAE-Artifacts/src/kae_artifacts/generation/profiles.py:103-114`,
  `domain/artifacts.py:48-56` (`BLOCKED`), `plans.py:125-135` — the only hard
  generation gate in that repo, and it fires on a missing repository name. No
  lifecycle input.
- `KAE-Artifacts/src/kae_artifacts/publishers/github.py:266`,
  `publishers/port.py:117`, `domain/preview.py:46,62` — "the provider did not
  confirm" is durability acknowledgement; "proposed change" is an un-applied
  diff.
- `KAE-Artifacts/src/kae_artifacts/domain/validation.py:14-25` — the `WARNING`
  docstring mentions knowledge nobody confirmed, but no check in
  `validation/checks.py` inspects confidence. Documented intent, unimplemented;
  the fix is a docstring edit.
- `src/cie_slim/embeddings.py:131-143`, `ai_interview.py:264-276`,
  `interview_quality.py:99-101` — `candidate` means a candidate *question
  string* under duplicate detection.
- `src/cie_slim/vibe_validator.py:121-123` — `status must be 'candidate'` is
  vibe-pack maturity, a separate artifact lifecycle.
- `src/cie_slim/kae/interview_metrics.py:177`, `:272` — `field_targeted or
  "unknown"` is a metrics sentinel.
- `src/cie_slim/**` `"unknown <thing>"` in `KeyError` / `ValueError` messages
  (`cli.py`, `session_model.py`, `workflow_registry.py`, `prompt_router.py`,
  and others) — error prose.
- `src/cie_slim/kae/interview_fixtures.py` and `domain_packs/*/*.yaml` — "order
  confirmation email", "booking confirmed": domain content inside fixtures.
- `src/cie_slim/vibe/**`, `examples/**`, `out/**` — separate agent skill-pack
  corpus and generated output.
- KAE-Artifacts `api/app.py` `status` hits — HTTP status codes and run status.
- `KAE-Studio/src/pages/setup/SetupPage.tsx:190,252,416,528` — `'confirmed'` is
  a `Badge` colour tone. `KAE-Studio/backend/src/kae_studio/api.py:100-120`,
  `:700-725` — `state='confirmed'`, `confirmed_by=operator.name` on *setup
  configuration*: a person typed a repository URL, which is not extracted
  knowledge.
- `KAE-Studio` — roughly forty `confirm.isPending`, `classify.isPending`, `busy`
  sites are React Query in-flight flags, and
  `src/pages/rooms/interview/InterviewRoom.tsx:68` is message delivery state.
- `KAE-Studio/src/pages/rooms/planning/GeneratePackage.tsx:78,139-157,202`,
  `src/domain/types.ts:453` — `ArtifactReadiness = 'ready' | 'needs_review' |
  'blocked'` is KAE-Artifacts' per-file plan readiness surfaced through Studio.
  Borderline: the underlying `NEEDS_REVIEW` *is* in group A, on the Artifacts
  side where it is produced. Studio only displays it.
- `KAE-Studio/src/pages/rooms/planning/GeneratePackage.tsx:701-760`,
  `src/domain/types.ts:575-595` (`awaiting_approval`),
  `backend/src/kae_studio/api.py:604-655` (`/api/decode`) — approving a document
  write to a destination, and confirming an upload preview before ingesting
  bytes. Same word, different act, as in KAE-Artifacts.
- `KAE-Studio/src/app/registries/rooms.ts:66,175,217` — `'awaiting-capability'`
  is a surface saying its own backend does not exist yet.
- `KAE-Studio/src/services/live/liveServices.ts:1112-1129`,
  `src/domain/types.ts:984`, `backend/src/kae_studio/projection.py:333` —
  deliverable states, read-only module status display, and a pagination envelope
  key named `candidates`.
- `KAE-Studio/src/services/mock/**` (roughly thirty `status: 'proposed'` in
  `fixtures/ministryReporting.ts`; `mockServices.ts:287-300`, `:394-400`) —
  offline demo fixtures. They encode the model faithfully and are not product
  logic; they will need updating with it.
- `KAE-Studio` — `area_link` / `areaLink` and `needs_review` (outside
  `ArtifactReadiness`) have **zero** non-comment occurrences, and
  `minimum_confirmed` appears only at `backend/src/kae_studio/projection.py:494`,
  `:504`. Studio never sees an area link; it sees the counts they produced.

**Related but out of scope.**

- `src/cie_slim/kae/coverage.py:199-200` — an unrecognised field id from
  extraction is silently dropped. Data loss, and the opposite of surfacing
  unclassified work; worth its own row, not this one.
- `KAE-Artifacts/CLAUDE_FULL_IMPLEMENTATION_PROMPT.md:50,122,313` — the original
  build prompt that specified `NEEDS_REVIEW` and "preserve evidence state
  (confirmed/assumed/proposed)". Historical, not live, and recorded here because
  it is where the assumption entered that repository.

---

## What tests pin this

Not defects, and they will fail first. In KAE-Memory, 89 test files reference
confirmation vocabulary; the ones that assert the behaviour rather than use it
are `tests/readiness/test_readiness_service.py`,
`tests/readiness/test_readiness_scoring.py`, `tests/readiness/test_claims.py`,
`tests/readiness/test_review_findings.py`,
`tests/readiness/test_blueprint_and_trace.py`,
`tests/retrieval/test_lifecycle_filtering.py`,
`tests/application/test_clarification.py`,
`tests/application/test_clarification_lifecycle.py`,
`tests/application/test_assembly.py`. In KAE-Artifacts,
`tests/test_generators.py:97-105`, `tests/test_config_and_integration.py:188-207`,
`tests/test_pipeline.py:184-192`, `tests/conftest.py:38-44`. In KAE-Studio,
`backend/tests/test_confirmation_gesture.py` and
`e2e/acceptance/journey.py:244-260` fail the moment confirmation stops being the
mechanism, and `backend/tests/test_definition.py:127-133` asserts positively
that a proposed statement must **not** reach the Definition — the one test that
has to be rewritten rather than retargeted.

`EPI-0` — AWS Compute Lab as a named regression case — is what makes these
replaceable rather than merely deletable. Until it exists, changing a readiness
test means asserting a new number with nothing to check it against.

---

## What could not be determined

**Whether the AWS Compute Lab figures reproduce from these sites.** The 803 /
692 / 103 counts come from a screenshot. Every mechanism that could produce them
is inventoried above, and no fixture ties a specific mechanism to a specific
number. `EPI-0` exists for exactly this and the checklist says to start there;
this document deliberately does not guess at attribution.

**Which stored `unknown` rows are extractor artefacts and which are real.**
Group D identifies where they are minted, not how many of the existing rows
would survive reconciliation. Answering it needs the corpus, and doc 17 already
rules that where epistemic state cannot safely be reconstructed, legacy state is
preserved and reconciliation rebuilds progressively.

**What replaces `minimum_confirmed`.** The objection in
`readiness_service.py:93-106` is sound — a project must not raise its own score
by generating candidates — and nothing in doc 17 or ADR-0007 specifies the
evidence-strength measure that answers it while honouring ADR-0003's rule that
state is discrete. `EPI-5` owns the design; this inventory found the sites and
not the replacement.

**Whether any consumer outside these four repositories reads the confirmed
counts.** `AreaResult`'s shape and `GET /readiness` are public, and the search
covered four repositories by instruction. An external agent binding to
`confirmed` / `proposed` would break silently.

**Whether Studio's deployed behaviour matches its checked-in code.** Everything
in the Studio sections was read from source. No instance was run, so the shapes
`projection.py` produces are reasoned from the code and not observed on a live
project.

**How much of cris-cie-slim's legacy path is live.**
`src/cie_slim/kae/__init__.py:28-39` states that the `kae/` local knowledge
model is reachable only from `interview_replay.py`, which is itself imported by
nothing — yet `session_model.py`, `interview_artifacts.py` and `cli.py` are
reachable and carry the same readiness gate. Group B lists both. Which of them
a correction has to touch depends on whether the CLI is still a shipped product,
which is a product question this scan cannot answer.
