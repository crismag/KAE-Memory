# Epistemic knowledge model

How KAE-Memory separates what a source showed, what KAE inferred, what an authority
settled, what is current, and what needs a person.

The ecosystem direction is defined by
[Doc 17](https://github.com/crismag/KAE-Ecosystem/blob/main/development/knowledge-synthesis-review/17-KAE-MEMORY-EPISTEMIC-INGESTION-MODEL.md)
and the
[knowledge-layers contract](https://github.com/crismag/KAE-Ecosystem/blob/main/contracts/KNOWLEDGE_LAYERS.md).
This page records how that direction maps onto KAE-Memory and where the implementation is
still transitional.

## Governing rule

Acquired knowledge is evidence, not a human task. Extraction may create thousands of
observations without creating thousands of attention items. Human attention appears only
after reconciliation identifies a material issue that requires authority or information
KAE cannot obtain responsibly.

## Independent dimensions

One status cannot say everything important about a claim.

| Dimension | Question | Examples |
|---|---|---|
| Formation | How was it formed? | observed, derived, assumed, proposed |
| Authority | Who or what may settle it, for what scope? | none, source policy, human |
| Evidence role | How does this row participate now? | active, supporting, conflicting, noise |
| Currency | Is it applicable at this revision/time? | current, superseded, historical |
| Confidence | How strongly is it supported? | calibrated score plus method/version |
| Materiality | What happens if it is wrong? | consequence, reversibility, affected capability |

Acceptance is an authority event, not a new formation. An observed repository fact remains
observed after a person accepts it. A derived recommendation remains derived after it is
adopted. Its authority changes; its origin does not.

Likewise, `conflicting` and `noise` are evidence roles, not methods of knowing.
`superseded` and `historical` describe currency. Keeping these axes independent prevents a
reconciliation pass from rewriting provenance or an acceptance action from erasing how a
claim was formed.

## Current persisted model

KAE-Memory currently persists three layers:

1. `knowledge_items`, versions, provenance links, chunks, and project-source coordinates
   preserve extracted evidence.
2. `synthesized_objects` plus evidence bindings preserve the compact current model.
3. `attention_items` preserve the material issues presented to a person.

Evidence roles and reconciliation events record how evidence participates and make reruns
idempotent. Domain-specific synthesizers build goals, actors, rules, assumptions,
requirements, constraints, decisions, and unknown themes.

The authoritative project state should remain a **projection** over these records rather
than becoming a fourth mutable copy. A future projection manifest should pin:

- project-model revision;
- object revisions;
- evidence frontier and source revisions;
- authority-policy version;
- reconciliation and synthesizer versions;
- active conflicts, assumptions, and material unknowns.

That manifest is the stable handoff for readiness, assembled context, Studio, CIE, and
KAE-Artifacts.

## What is transitional

`KnowledgeItem.lifecycle` still records proposed, validated, rejected, or superseded.
Legacy Confirm/Reject routes and Studio surfaces still use it. This lifecycle is not the
attention queue and must not be repurposed as the synthesized model's approval lifecycle.

Readiness also remains partly confirmation-based: grounded evidence can reach evidenced or
interpreted states, but only validated rows currently make a normal area sufficient. That
is current behavior, not the target epistemic contract.

The current synthesized-object authority is `working_model | human`. This protects human
corrections from silent working-model overwrite, but it cannot yet represent contextual
source authority, an attested principal, effective time, or authority scope.

The current `EpistemicClass` projection also exposes `accepted` as a convenient summary
when a row is validated. Target storage and public contracts should not let that summary
replace the row's observed or derived formation; acceptance belongs on the authority axis.

## Storage improvements

### Preserve the existing backbone

Do not replace evidence, synthesized objects, bindings, attention, or reconciliation
events. They correctly separate accumulated observations from the compact model and human
work.

### Add scoped authority events

Authority needs an append-oriented record containing:

- object or claim identity;
- authority basis: human decision, project policy, legal/policy source, or another defined
  basis;
- authenticated principal or policy identifier;
- claim scope, such as current implementation, intended behavior, normative policy, or
  future decision;
- effective interval;
- decision rationale and superseded authority event;
- evidence/model revision considered.

A source type is not sufficient authority by itself. A repository is strong evidence for
current implementation and weak evidence for future intent. An ADR can settle architecture
without proving the deployed topology still matches it.

### Version synthesized objects

The current object identity should remain stable, but each changed statement or structured
domain payload should be an immutable revision. Evidence bindings and authority events pin
the revision they concern. Consumers can then reproduce what the model said at any project
revision instead of seeing only the latest overwrite.

### Track source-revision currency

Each observation needs a coordinate to the source revision and location that produced it.
Incremental ingestion compares source snapshots so additions, modifications, deletions,
renames, and moves update currency. Evidence absent from a later repository revision stays
historical but cannot remain silently current.

Where project time differs from acquisition time, preserve both. Ingesting an old document
today does not make its claims newly effective today.

### Preserve derivation replay

Derived claims record their supporting evidence, rationale, model/tool and prompt version,
policy version, input fingerprint, and confidence method. A bare confidence number is not
portable evidence: calibration and the producing method are part of its meaning.

### Keep sensitive and adversarial content outside authority

Repository and document content is untrusted data. Text resembling system instructions
does not change KAE policy. Ingestion must apply archive/path safety, type and size bounds,
secret and personal-data handling, source licensing/retention policy, and explicit
instruction/data separation before model processing.

## Readiness target

Readiness answers “sufficient for which action?” A result should pin the project-model
revision and identify:

- the target action or capability;
- required claims and their evidence/authority states;
- blocking conflicts, assumptions, and unknowns;
- source and synthesis freshness;
- blockers versus advisory limitations;
- the reason the result changed.

Current repository evidence may satisfy claims about implementation discovery without a
confirmation click. Product-scope or future-direction claims may still require human
authority. The requirement belongs to the claim, not to every row in the database.

## Human-attention contract

An attention item has a stable semantic identity and records:

- the material consequence;
- why KAE cannot resolve it;
- affected decisions or capabilities;
- evidence and model links;
- priority basis and recommendation;
- valid resolution actions and closure condition.

Identical reruns update or replay the item rather than creating duplicates. Evidence that
resolves an informational gap may close it automatically. Authority gaps remain until the
required authority acts.

## Migration sequence

1. Continue writing legacy lifecycle while new projections are verified.
2. Backfill only what provenance supports; classify missing provenance as undetermined.
3. Publish formation, authority, role, and currency separately at adapter boundaries.
4. Build the versioned authoritative-state projection manifest.
5. Move readiness, context assembly, Studio, CIE, and Artifacts to that manifest.
6. Stop creating new row-level review work.
7. Retire legacy Confirm/Reject surfaces only after active consumers have migrated.

## Verification

The AWS Compute Lab regression pins repository commit, ingestion scope, and processing
versions. It should prove that unchanged replay creates no duplicates, removed evidence
does not stay current, every model assertion is traceable, unclassified evidence remains a
diagnostic rather than user work, and no attention item exists merely because an extracted
row lacks confirmation.

Related concepts:

- [Knowledge lifecycle](knowledge-lifecycle.md)
- [Provenance and evidence](provenance-and-evidence.md)
- [Clarifications and unknowns](clarifications-and-unknowns.md)
